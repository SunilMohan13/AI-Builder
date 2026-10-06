"""Day-1 APAC contracts reject the mixes the design forbids."""

from datetime import UTC, datetime

import pytest
from aeropulse_contracts.citizen_analysis import VisualObservation
from aeropulse_contracts.meteo_forecast import MeteoForecast
from aeropulse_contracts.observation import Location, Provenance, ProvenanceClass
from aeropulse_contracts.region_snapshot import RegionSnapshot
from pydantic import ValidationError


def test_forecast_rejects_issued_after_valid() -> None:
    with pytest.raises(ValidationError):
        MeteoForecast(
            forecast_id="mfc",
            source_id="openmeteo",
            source_record_id="s",
            issued_at=datetime(2026, 9, 8, 6, tzinfo=UTC),
            valid_at=datetime(2026, 9, 8, 5, tzinfo=UTC),
            location=Location(lat=1.3, lon=103.8),
            provenance=Provenance(
                provider="Open-Meteo",
                connector_version="1",
                provenance_class=ProvenanceClass.MODEL_DERIVED,
            ),
        )


def test_snapshot_cannot_be_demo() -> None:
    with pytest.raises(ValidationError):
        RegionSnapshot(
            region_id="sg-singapore",
            cycle_time=datetime(2026, 9, 8, tzinfo=UTC),
            pack_version="abc",
            mode="demo",  # type: ignore[arg-type]
        )


def test_visual_summary_rejects_a_concentration() -> None:
    with pytest.raises(ValidationError):
        VisualObservation(
            visual_class="haze",
            visual_certainty="low",
            likely_source_type="unknown",
            image_quality="fair",
            scene_summary="PM2.5 is 180 µg/m³ over the harbour",
            model_name="test-model",
        )
