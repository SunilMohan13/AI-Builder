"""Decide, per family and region, whether a model or the rule answers (LLD APAC 7.7).

Every ``model_serving.yaml`` entry is checked once, at startup. An entry is
refused, and the rule answers with ``degraded=true``, when any of these fail:

- the region is in the catalog and the family is a trained one;
- the gate report reads, names the same family and model version, was built on
  the current ``ml-features`` version and feature names, is servable (not
  synthetic data), and says this region passed;
- an entry that claims ``calibrated`` has a gate report that agrees;
- the artifact exists and its SHA-256 matches the one the report pins, and the
  loaded model names the same family, version and features.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aeropulse_common.errors import ModelServingError, TrainingError
from aeropulse_contracts import MODEL_FAMILIES, GateReport, ServedModel
from aeropulse_contracts.feature_spec import ML_FEATURE_VERSION
from aeropulse_intelligence.source_evidence import method_version
from aeropulse_observability import get_logger
from aeropulse_regions import RegionCatalog
from pydantic import ValidationError

from aeropulse_ml.datasets.base import NON_SERVABLE_KINDS
from aeropulse_ml.models.artifacts import load_model
from aeropulse_ml.models.base import FittedModel, ModelPlugin
from aeropulse_ml.models.registry import get_plugin
from aeropulse_ml.serving.artifacts import ArtifactReader, LocalArtifactReader
from aeropulse_ml.serving.config import (
    SERVING_FILENAME,
    ServingConfig,
    ServingEntry,
    load_serving_config,
)
from aeropulse_ml.serving.rules import RULE_VERSIONS

log = get_logger(__name__)

#: Families that are a deterministic method by design, not a fallback.
HEURISTIC_FAMILIES = frozenset({"source_likelihood"})


@dataclass(frozen=True)
class Served:
    """What answers one family in one region, and why."""

    family: str
    region_id: str
    model_version: str
    degraded: bool
    degraded_reason: str | None
    calibrated: bool
    feature_version: str | None = None
    plugin: ModelPlugin | None = None
    model: FittedModel | None = None

    @property
    def uses_model(self) -> bool:
        return self.model is not None

    def to_contract(self) -> ServedModel:
        return ServedModel(
            family=self.family,
            model_version=self.model_version,
            feature_version=self.feature_version,
            degraded=self.degraded,
            degraded_reason=self.degraded_reason,
            calibrated=self.calibrated,
        )


@dataclass(frozen=True)
class Refusal:
    entry: ServingEntry
    reason: str


class ModelResolver:
    """Load-time checks on ``model_serving.yaml``, then O(1) lookups."""

    def __init__(
        self,
        config: ServingConfig,
        catalog: RegionCatalog,
        *,
        reader: ArtifactReader | None = None,
    ) -> None:
        self._catalog = catalog
        self._reader = reader or LocalArtifactReader()
        self._served: dict[tuple[str, str], Served] = {}
        self._refused: dict[tuple[str, str], Refusal] = {}
        for entry in config.entries:
            key = (entry.family, entry.region_id)
            try:
                self._served[key] = self._load(entry)
            except ModelServingError as exc:
                self._refused[key] = Refusal(entry, exc.message)
                log.warning(
                    "model_serving_entry_refused",
                    family=entry.family,
                    region_id=entry.region_id,
                    model_version=entry.model_version,
                    reason=exc.message,
                )

    @classmethod
    def from_config_dir(
        cls,
        catalog: RegionCatalog,
        *,
        config_dir: Path | None = None,
        reader: ArtifactReader | None = None,
    ) -> ModelResolver:
        """Read ``<config_dir>/model_serving.yaml``; relative URIs resolve from its parent."""
        root = config_dir or catalog.config_dir
        config = load_serving_config(root / SERVING_FILENAME)
        return cls(config, catalog, reader=reader or LocalArtifactReader(root.resolve().parent))

    @property
    def refusals(self) -> list[Refusal]:
        return list(self._refused.values())

    def resolve(self, family: str, region_id: str) -> Served:
        if family not in MODEL_FAMILIES:
            raise ModelServingError(f"unknown model family: {family!r}")
        self._catalog.get(region_id)
        served = self._served.get((family, region_id))
        if served is not None:
            return served
        if family in HEURISTIC_FAMILIES:
            return Served(
                family=family,
                region_id=region_id,
                model_version=method_version(self._catalog.hazards_for(region_id)),
                degraded=False,
                degraded_reason=None,
                calibrated=False,
            )
        return Served(
            family=family,
            region_id=region_id,
            model_version=RULE_VERSIONS[family],
            degraded=True,
            degraded_reason=self._rule_reason(family, region_id),
            calibrated=False,
        )

    def served_models(self, region_id: str) -> list[ServedModel]:
        """One line per family; never empty, at least the rule is listed."""
        return [self.resolve(f, region_id).to_contract() for f in MODEL_FAMILIES]

    def _rule_reason(self, family: str, region_id: str) -> str:
        refusal = self._refused.get((family, region_id))
        if refusal is not None:
            return f"model {refusal.entry.model_version} refused: {refusal.reason}"
        pack = self._catalog.get(region_id)
        if pack.ground_truth == "none" or not pack.ground_truth_sources:
            return "no ground truth in this region"
        if family != "pm25_forecast" and self._catalog.aqi_for(region_id).status != "confirmed":
            return "AQI standard unconfirmed: no hazard threshold for this region"
        return f"no model passed the gate for {region_id}"

    def _load(self, entry: ServingEntry) -> Served:
        if entry.region_id not in self._catalog.packs:
            raise ModelServingError(f"unknown region {entry.region_id!r}")
        try:
            plugin = get_plugin(entry.family, self._catalog)
        except TrainingError as exc:
            raise ModelServingError(exc.message) from exc
        if not plugin.trained:
            raise ModelServingError(f"{entry.family} is a heuristic and is never served as a model")
        report = self._report(entry.gate_report_uri)
        _check_report(entry, plugin, report)
        if report.artifact_sha256 is None:
            raise ModelServingError("gate report pins no artifact SHA-256")
        path = self._reader.local_path(entry.artifact_uri)
        model = load_model(path, expected_sha256=report.artifact_sha256)
        _check_model(entry, report, model)
        return Served(
            family=entry.family,
            region_id=entry.region_id,
            model_version=entry.model_version,
            feature_version=report.ml_feature_version,
            degraded=False,
            degraded_reason=None,
            calibrated=entry.calibrated,
            plugin=plugin,
            model=model,
        )

    def _report(self, uri: str) -> GateReport:
        path = self._reader.local_path(uri)
        try:
            return GateReport.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as exc:
            raise ModelServingError(f"gate report unreadable: {exc}") from exc


def _check_report(entry: ServingEntry, plugin: ModelPlugin, report: GateReport) -> None:
    if report.family != entry.family:
        raise ModelServingError(f"gate report is for {report.family}, not {entry.family}")
    if report.model_version != entry.model_version:
        raise ModelServingError(
            f"gate report is for {report.model_version}, entry names {entry.model_version}"
        )
    if report.ml_feature_version != ML_FEATURE_VERSION:
        raise ModelServingError(
            f"feature version {report.ml_feature_version} differs from current {ML_FEATURE_VERSION}"
        )
    if tuple(report.feature_names) != plugin.feature_set.names:
        raise ModelServingError("gate report feature names differ from the current feature set")
    if report.dataset.kind in NON_SERVABLE_KINDS:
        raise ModelServingError(f"trained on {report.dataset.kind} data")
    if not report.servable:
        raise ModelServingError(f"gate report is not servable: {report.servable_reason}")
    gate = report.region(entry.region_id)
    if gate is None:
        raise ModelServingError(f"gate report has no result for {entry.region_id}")
    if not gate.passed:
        detail = "; ".join(gate.failures[:3]) or "no reason recorded"
        raise ModelServingError(f"{entry.region_id} failed its gate: {detail}")
    if entry.calibrated and not (report.calibrated and gate.calibrated):
        raise ModelServingError(
            f"entry claims calibrated, gate report does not for {entry.region_id}"
        )


def _check_model(entry: ServingEntry, report: GateReport, model: FittedModel) -> None:
    if model.family != entry.family or model.model_version != entry.model_version:
        raise ModelServingError(
            f"artifact holds {model.family} {model.model_version}, entry names "
            f"{entry.family} {entry.model_version}"
        )
    if model.ml_feature_version != report.ml_feature_version or list(model.feature_names) != list(
        report.feature_names
    ):
        raise ModelServingError("artifact features differ from its gate report")
