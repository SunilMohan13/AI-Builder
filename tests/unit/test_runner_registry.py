"""Registry-driven runner: topic routing, failure isolation, no substitution.

The rule these tests defend: a live source that cannot run must report why,
and must never quietly serve a fixture under a live banner.
"""

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aeropulse_common.topics import (
    OBSERVATION_AQ,
    OBSERVATION_FIRE,
    OBSERVATION_RASTER,
    OBSERVATION_WEATHER,
)
from aeropulse_connector_app.registry import SPECS_BY_ID, SourceSpec, topic_for
from aeropulse_connector_app.runner import SourceStatus, run_cycle
from aeropulse_connector_sdk.base import DataConnector
from aeropulse_connector_sdk.contracts import (
    ConnectorMetadata,
    FetchRequest,
    HealthStatus,
    RawRecord,
    SourceAsset,
)
from aeropulse_connector_sdk.live_http import CircuitOpenError
from aeropulse_connector_sdk.testing import FixtureMissingError
from aeropulse_contracts.fire import FireObservation, FireProperties
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    Quality,
)
from aeropulse_contracts.raster import RasterObservation

T0 = datetime(2026, 9, 8, 5, 15, tzinfo=UTC)
NO_CONFIG = Path("does-not-exist.yaml")


def _aq() -> Observation:
    return Observation(
        observation_id="obs_1",
        source_id="stub",
        source_record_id="rec_1",
        observed_at=T0,
        received_at=T0,
        location=Location(lat=28.6, lon=77.2),
        measurement=Measurement(parameter="pm25", value=101.0, unit="ug/m3"),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider="Stub", connector_version="1.0.0"),
    )


def _weather() -> MeteorologicalObservation:
    return MeteorologicalObservation(
        observation_id="met_1",
        source_id="stub",
        source_record_id="rec_2",
        observed_at=T0,
        received_at=T0,
        location=Location(lat=28.6, lon=77.2),
        parameter="weather",
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider="Stub", connector_version="1.0.0"),
    )


def _raster() -> RasterObservation:
    return RasterObservation(
        observation_id="ras_1",
        source_id="stub",
        source_record_id="rec_3",
        product_id="stub_product",
        acquisition_time=T0,
        processing_time=T0,
        bbox=(77.0, 28.0, 77.5, 28.5),
        resolution="point",
        object_uri="",
        checksum="",
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider="Stub", connector_version="1.0.0"),
    )


class StubConnector(DataConnector):
    """Emits a caller-supplied set of contracts, or raises."""

    def __init__(self, outputs=None, *, error: Exception | None = None, live: bool = False) -> None:
        self._outputs = outputs or []
        self._error = error
        self._live = live

    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            connector_id="stub",
            provider="Stub",
            version="1.0.0",
            data_type="observation",
            transport="https",
        )

    def discover(self) -> list[SourceAsset]:
        return []

    def is_live(self) -> bool:
        return self._live

    def fetch(self, request: FetchRequest) -> Iterator[RawRecord]:
        if self._error is not None:
            raise self._error
        yield RawRecord(
            source_id="stub",
            source_record_id="rec",
            payload={},
            fetched_at=T0,
        )

    def normalize(self, record: RawRecord) -> Sequence[object]:
        return list(self._outputs)

    def health_check(self) -> HealthStatus:
        return HealthStatus(connector_id="stub", healthy=True, checked_at=T0)


def _spec(connector: StubConnector, **kwargs) -> SourceSpec:
    return SourceSpec(
        source_id=kwargs.pop("source_id", "stub"),
        factory=lambda _path: connector,
        fixture_rel=None,
        **kwargs,
    )


def test_topic_is_derived_from_the_contract_type() -> None:
    assert topic_for(_aq()) == OBSERVATION_AQ
    assert topic_for(_weather()) == OBSERVATION_WEATHER
    assert topic_for(_raster()) == OBSERVATION_RASTER


def test_unknown_contract_type_is_rejected() -> None:
    with pytest.raises(TypeError):
        topic_for(object())


def test_one_source_can_emit_several_topics() -> None:
    """The reason Open-Meteo could not be wired into the previous runner."""
    published: list[str] = []
    connector = StubConnector([_aq(), _weather(), _raster()])

    result = run_cycle(
        Path("fixtures"),
        lambda topic, _env: published.append(topic),
        sources_config=NO_CONFIG,
        specs=(_spec(connector),),
    )

    assert result.counts()["stub"] == 3
    assert set(published) == {OBSERVATION_AQ, OBSERVATION_WEATHER, OBSERVATION_RASTER}


def test_missing_fixture_degrades_one_source_and_keeps_the_cycle() -> None:
    broken = _spec(
        StubConnector(error=FixtureMissingError(Path("fixtures/gone.json"))), source_id="broken"
    )
    healthy = _spec(StubConnector([_aq()]), source_id="healthy")

    result = run_cycle(
        Path("fixtures"),
        lambda _t, _e: None,
        sources_config=NO_CONFIG,
        specs=(broken, healthy),
    )

    statuses = {run.source_id: run.status for run in result.runs}
    assert statuses["broken"] is SourceStatus.FIXTURE_MISSING
    assert statuses["healthy"] is SourceStatus.REPLAY
    assert result.counts()["healthy"] == 1


def test_an_upstream_failure_isolates_to_its_own_source() -> None:
    failing = _spec(StubConnector(error=RuntimeError("upstream 503")), source_id="failing")
    healthy = _spec(StubConnector([_aq()]), source_id="healthy")

    result = run_cycle(
        Path("fixtures"),
        lambda _t, _e: None,
        sources_config=NO_CONFIG,
        specs=(failing, healthy),
    )

    statuses = {run.source_id: run.status for run in result.runs}
    assert statuses["failing"] is SourceStatus.DEGRADED
    assert statuses["healthy"] is SourceStatus.REPLAY


def test_open_circuit_is_reported_distinctly() -> None:
    spec = _spec(StubConnector(error=CircuitOpenError("stub")), source_id="tripped")

    result = run_cycle(
        Path("fixtures"), lambda _t, _e: None, sources_config=NO_CONFIG, specs=(spec,)
    )

    assert result.runs[0].status is SourceStatus.CIRCUIT_OPEN


def test_live_source_without_its_credential_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No silent fixture substitution: a missing key must be visible."""
    published: list[str] = []
    spec = _spec(
        StubConnector([_aq()], live=True),
        source_id="needs_key",
        live_capable=True,
        credential_setting="firms_map_key",
    )

    result = run_cycle(
        Path("fixtures"),
        lambda topic, _e: published.append(topic),
        sources_config=NO_CONFIG,
        specs=(spec,),
    )

    assert result.runs[0].status is SourceStatus.NOT_CONFIGURED
    assert published == []
    assert result.counts()["needs_key"] == 0


def test_disabled_source_is_skipped_and_reported(tmp_path: Path) -> None:
    config = tmp_path / "sources.yaml"
    config.write_text("sources:\n  - {id: stub, enabled: false}\n")
    spec = _spec(StubConnector([_aq()]))

    result = run_cycle(Path("fixtures"), lambda _t, _e: None, sources_config=config, specs=(spec,))

    assert result.runs[0].status is SourceStatus.DISABLED
    assert result.counts()["stub"] == 0


def test_cycle_persists_source_health_from_the_run() -> None:
    """The runner owns source_health; the worker must not attribute every batch to CPCB."""

    class _Repo:
        def __init__(self) -> None:
            self.rows: list[tuple] = []

        def get_checkpoint(self, source_id: str) -> str | None:
            return None

        def upsert_checkpoint(self, source_id: str, cursor: str) -> None:
            return None

        def upsert_source_health(self, source_id: str, records: int, status: str, **kwargs) -> None:
            self.rows.append((source_id, records, status, kwargs))

    repo = _Repo()
    spec = _spec(StubConnector([_aq()]), source_id="healthy")

    result = run_cycle(
        Path("fixtures"),
        lambda _t, _e: None,
        sources_config=NO_CONFIG,
        specs=(spec,),
        repo=repo,
    )

    assert result.runs[0].status is SourceStatus.REPLAY
    assert repo.rows[0][0] == "healthy"
    assert repo.rows[0][1] == 1
    assert repo.rows[0][2] == "REPLAY"
    assert repo.rows[0][3]["processing_mode"] == "replay"


def test_cycle_reports_the_newest_observation_for_the_watermark() -> None:
    spec = _spec(StubConnector([_aq(), _weather()]))

    result = run_cycle(
        Path("fixtures"), lambda _t, _e: None, sources_config=NO_CONFIG, specs=(spec,)
    )

    assert result.runs[0].max_observed_at == T0


def test_registry_covers_every_configured_source() -> None:
    """A source in config/sources.yaml with no spec would silently never run."""
    import yaml

    config = yaml.safe_load(Path("config/sources.yaml").read_text())
    configured = {s["id"] for s in config["sources"]}
    # `population` is a gridded reference layer read directly by the risk
    # endpoint, not an ingested stream; it has no connector implementation.
    configured.discard("population")

    assert configured <= set(SPECS_BY_ID), f"unregistered: {configured - set(SPECS_BY_ID)}"


def test_firms_is_live_capable() -> None:
    """YAML live_capable: true is load-bearing only if SOURCE_SPECS agrees."""
    assert SPECS_BY_ID["firms"].live_capable is True
    assert SPECS_BY_ID["firms"].credential_setting == "firms_map_key"


def test_yaml_live_capable_agrees_with_source_specs() -> None:
    """A yaml/registry split would replay FIRMS under a live banner."""
    import yaml

    config = yaml.safe_load(Path("config/sources.yaml").read_text())
    yaml_live = {
        row["id"]: bool(row.get("live_capable", False))
        for row in config["sources"]
        if row["id"] in SPECS_BY_ID
    }
    for source_id in ("openaq", "openmeteo", "firms"):
        assert yaml_live[source_id] is True
        assert SPECS_BY_ID[source_id].live_capable is True
    assert yaml_live["imd"] is False
    assert SPECS_BY_ID["imd"].live_capable is False


def test_fire_contract_routes_to_the_fire_topic() -> None:
    fire = FireObservation(
        observation_id="fire_1",
        source_id="stub",
        source_record_id="rec_f",
        observed_at=T0,
        received_at=T0,
        location=Location(lat=30.2, lon=75.5),
        fire=FireProperties(frp=12.5, confidence=0.8, sensor="VIIRS"),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider="Stub", connector_version="1.0.0"),
    )
    assert topic_for(fire) == OBSERVATION_FIRE


def test_fixtures_root_points_at_the_fixtures_directory(tmp_path: Path, monkeypatch) -> None:
    """Image copies fixtures to /app/fixtures; SourceSpec joins cpcb/stations.json onto that."""
    from aeropulse_connector_app.main import _fixtures_root

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    monkeypatch.chdir(tmp_path)
    if Path("/app/fixtures").is_dir():
        pytest.skip("running inside an image that already has /app/fixtures")
    assert _fixtures_root() == fixtures
