"""A region's transport setup for the plume engine (APAC LLD 8.2, 8.4).

Shared by the cycle and the citizen analyzer, so a plume seeded from a
citizen report runs with exactly the inputs a cycle plume would. The hazard
profile that sets the level weights and horizons is the region's first
hazard with plume defaults. Population and gazetteer come from onboarding
files next to the pack; without them footprints still run, and exposure and
arrivals say why they are missing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from aeropulse_contracts import FieldStatus, MeteoForecast, MeteorologicalObservation
from aeropulse_regions import HazardProfile, RegionCatalog, RegionPack
from aeropulse_regions.models import PlumeDefaults

from aeropulse_intelligence.plume.engine import PlumeInputs
from aeropulse_intelligence.plume.outputs import Place, PopulationIndex
from aeropulse_intelligence.plume.uncertainty import measure
from aeropulse_intelligence.plume.wind import WindField, forecast_wind

#: Onboarding outputs (LLD 4.1 pack layout).
GAZETTEER_FILE = "gazetteer.parquet"
POPULATION_FILE = "population_h3r8.parquet"
#: Setting: place radius when the gazetteer has no ``radius_km`` column.
DEFAULT_PLACE_RADIUS_KM = 5.0


def transport_profile(catalog: RegionCatalog, region_id: str) -> HazardProfile | None:
    """The region's first hazard that runs a plume."""
    return next((h for h in catalog.hazards_for(region_id) if h.plume_defaults is not None), None)


def load_population(region_dir: Path, pack: RegionPack) -> PopulationIndex | None:
    path = region_dir / POPULATION_FILE
    if pack.population is None or not path.is_file():
        return None
    frame = pd.read_parquet(path)
    year = int(frame["year"].iloc[0]) if "year" in frame and len(frame) else None
    cells = dict(zip(frame["grid_id"].astype(str), frame["population"].astype(float), strict=True))
    return PopulationIndex.from_cells(cells, source=pack.population.source, year=year)


def load_places(region_dir: Path, pack: RegionPack) -> list[Place] | None:
    path = region_dir / GAZETTEER_FILE
    if pack.gazetteer is None or not path.is_file():
        return None
    places: list[Place] = []
    for row in pd.read_parquet(path).to_dict(orient="records"):
        raw = row.get("population")
        population = float(raw) if raw is not None and pd.notna(raw) else None
        if population is not None and population < pack.gazetteer.min_population:
            continue
        radius = row.get("radius_km")
        places.append(
            Place(
                place_id=str(row["place_id"]),
                name=str(row["name"]),
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                radius_km=float(radius) if radius is not None else DEFAULT_PLACE_RADIUS_KM,
                population=population,
            )
        )
    return places


@dataclass(frozen=True)
class RegionTransport:
    region_id: str
    pack: RegionPack
    defaults: PlumeDefaults
    population: PopulationIndex | None
    places: list[Place] | None
    field_status: list[FieldStatus] = field(default_factory=list)

    @classmethod
    def load(cls, catalog: RegionCatalog, region_id: str) -> RegionTransport | None:
        """``None`` when no hazard in the region runs a plume."""
        profile = transport_profile(catalog, region_id)
        if profile is None or profile.plume_defaults is None:
            return None
        pack = catalog.get(region_id)
        region_dir = catalog.region_dir(region_id)
        population = load_population(region_dir, pack)
        places = load_places(region_dir, pack)
        status: list[FieldStatus] = []
        if population is None:
            status.append(
                FieldStatus(
                    field="plumes.exposure",
                    reason=f"population raster not built for {region_id} ({POPULATION_FILE})",
                )
            )
        if places is None:
            status.append(
                FieldStatus(
                    field="plumes.arrivals",
                    reason=f"gazetteer not built for {region_id} ({GAZETTEER_FILE})",
                )
            )
        return cls(region_id, pack, profile.plume_defaults, population, places, status)

    @property
    def forward_hours(self) -> tuple[float, ...]:
        return tuple(self.defaults.horizons_hours)

    def inputs(self, wind: WindField, **extra: Any) -> PlumeInputs:
        return PlumeInputs(
            wind=wind,
            domain=self.pack.source_domain.bbox,
            display=self.pack.geometry.bbox,
            population=self.population,
            places=self.places or (),
            **extra,
        )

    def forward_inputs(
        self,
        forecasts: Sequence[MeteoForecast],
        weather: Sequence[MeteorologicalObservation],
        at: datetime,
    ) -> PlumeInputs | None:
        """Forward-run inputs at ``at``; ``None`` when no wind covers the window."""
        wind = forecast_wind(
            forecasts,
            as_of=at,
            start=at,
            end=at + timedelta(hours=max(self.forward_hours)),
            level_weights=self.defaults.release_level_weights,
            observed=weather,
        )
        if wind.empty:
            return None
        return self.inputs(
            wind,
            uncertainty=measure(forecasts, weather),
            level_weights=self.defaults.release_level_weights,
        )
