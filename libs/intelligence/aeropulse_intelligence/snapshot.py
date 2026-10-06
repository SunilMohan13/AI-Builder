"""In-memory observation snapshot used to build grid features without a database.

The snapshot indexes itself on first use. Without an index the feature builder
rescans every observation for every grid-hour, which is unnoticeable for the
single-hour snapshots the live path produces but quadratic for the multi-hour
windows that backfill, replay and training use: a 90-day, 5-site window is
roughly 10k grid-hours against 65k observations, which does not complete in a
usable time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from aeropulse_contracts.fire import FireObservation
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import Observation
from aeropulse_contracts.raster import RasterObservation
from aeropulse_geospatial.grid import to_grid_id

#: Sources whose air quality is model output rather than a ground measurement.
#: Open-Meteo serves CAMS-derived values — its own provider string says so, and
#: AGENTS.md forbids presenting them as station accuracy. Its corridor sites
#: share H3 cells with real stations, so without an explicit rule the cell's
#: value for an hour came down to list order.
MODEL_DERIVED_SOURCES = frozenset({"openmeteo", "cams"})


def _hour(ts: datetime) -> datetime:
    """Floor a timestamp to the UTC hour."""
    aware = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return aware.replace(minute=0, second=0, microsecond=0)


def precedence(obs: Observation) -> tuple[bool, datetime]:
    """Rank an observation for the same cell-hour.

    Ground truth outranks model output; within a tier, the newest wins. This
    is a total order over the fields involved, so the winner does not depend
    on the order observations arrived in.
    """
    return (obs.source_id not in MODEL_DERIVED_SOURCES, obs.observed_at)


@dataclass
class FeatureSnapshot:
    """Point-in-time observations available to ``build_features``."""

    air_quality: list[Observation] = field(default_factory=list)
    fires: list[FireObservation] = field(default_factory=list)
    weather: list[MeteorologicalObservation] = field(default_factory=list)
    rasters: list[RasterObservation] = field(default_factory=list)
    generated_at: datetime | None = None

    _aq_by_cell_hour: dict[tuple[str, datetime], list[Observation]] | None = field(
        default=None, repr=False, compare=False
    )
    _pm25_by_cell: dict[str, dict[datetime, float]] | None = field(
        default=None, repr=False, compare=False
    )
    _weather_by_hour: dict[datetime, list[MeteorologicalObservation]] | None = field(
        default=None, repr=False, compare=False
    )
    _rasters_by_hour: dict[datetime, list[RasterObservation]] | None = field(
        default=None, repr=False, compare=False
    )
    #: hour -> [(grid_id, lat, lon, pm25)], for the neighbour field. Indexed by
    #: hour rather than scanned per cell because the neighbour lookup is
    #: otherwise the one remaining O(cells x observations) path in the builder.
    _pm25_cells_by_hour: dict[datetime, list[tuple[str, float, float, float]]] | None = field(
        default=None, repr=False, compare=False
    )
    _indexed_sizes: tuple[int, int, int] | None = field(default=None, repr=False, compare=False)

    def _sizes(self) -> tuple[int, int, int]:
        return (len(self.air_quality), len(self.weather), len(self.rasters))

    def _ensure_index(self) -> None:
        """Build the lookup indices, rebuilding if the lists were mutated."""
        if self._aq_by_cell_hour is not None and self._indexed_sizes == self._sizes():
            return

        aq_index: dict[tuple[str, datetime], list[Observation]] = {}
        pm25_index: dict[str, dict[datetime, float]] = {}
        pm25_cell_index: dict[datetime, dict[str, tuple[str, float, float, float]]] = {}
        # Tracks which observation currently owns each cell-hour, so a later
        # one only replaces it when it genuinely outranks it.
        pm25_winner: dict[tuple[str, datetime], tuple[bool, datetime]] = {}
        for obs in self.air_quality:
            cell = obs.grid_id or to_grid_id(obs.location.lat, obs.location.lon)
            # Cache the resolved cell so repeated H3 lookups are avoided.
            obs.grid_id = cell
            bucket = _hour(obs.observed_at)
            aq_index.setdefault((cell, bucket), []).append(obs)
            if obs.measurement.parameter == "pm25":
                rank = precedence(obs)
                key = (cell, bucket)
                if key in pm25_winner and rank <= pm25_winner[key]:
                    continue
                pm25_winner[key] = rank
                pm25_index.setdefault(cell, {})[bucket] = obs.measurement.value
                pm25_cell_index.setdefault(bucket, {})[cell] = (
                    cell,
                    obs.location.lat,
                    obs.location.lon,
                    obs.measurement.value,
                )

        weather_index: dict[datetime, list[MeteorologicalObservation]] = {}
        for wx in self.weather:
            weather_index.setdefault(_hour(wx.observed_at), []).append(wx)

        raster_index: dict[datetime, list[RasterObservation]] = {}
        for raster in self.rasters:
            raster_index.setdefault(_hour(raster.acquisition_time), []).append(raster)

        self._aq_by_cell_hour = aq_index
        self._pm25_by_cell = pm25_index
        self._weather_by_hour = weather_index
        self._rasters_by_hour = raster_index
        self._pm25_cells_by_hour = {
            bucket: list(cells.values()) for bucket, cells in pm25_cell_index.items()
        }
        self._indexed_sizes = self._sizes()

    def pm25_cells_at(self, hour: datetime) -> list[tuple[str, float, float, float]]:
        """Return every cell observing PM2.5 in one hour, with its location.

        Args:
            hour: Hour-floored timestamp.

        Returns:
            ``(grid_id, lat, lon, pm25)`` per observing cell, empty when none.
        """
        self._ensure_index()
        assert self._pm25_cells_by_hour is not None
        return self._pm25_cells_by_hour.get(_hour(hour), [])

    def air_quality_at(self, grid_id: str, hour: datetime) -> list[Observation]:
        """Return this cell's observations for one hour.

        Args:
            grid_id: H3 cell.
            hour: Hour-floored timestamp.

        Returns:
            Matching observations, empty when the cell-hour was not observed.
        """
        self._ensure_index()
        assert self._aq_by_cell_hour is not None
        return self._aq_by_cell_hour.get((grid_id, _hour(hour)), [])

    def pm25_history(self, grid_id: str) -> dict[datetime, float]:
        """Return this cell's PM2.5 by hour bucket.

        Args:
            grid_id: H3 cell.

        Returns:
            Hour bucket to value. Callers must apply their own time cut-off.
        """
        self._ensure_index()
        assert self._pm25_by_cell is not None
        return self._pm25_by_cell.get(grid_id, {})

    def weather_within(
        self, hour: datetime, max_age_hours: float
    ) -> list[MeteorologicalObservation]:
        """Return weather observations within a time tolerance of an hour.

        Args:
            hour: Hour-floored target timestamp.
            max_age_hours: Inclusive tolerance in hours.

        Returns:
            Candidate observations.
        """
        self._ensure_index()
        assert self._weather_by_hour is not None
        target = _hour(hour)
        span = int(max_age_hours)
        found: list[MeteorologicalObservation] = []
        for offset in range(-span, span + 1):
            key = target.fromtimestamp(target.timestamp() + offset * 3600, tz=UTC)
            found.extend(self._weather_by_hour.get(key, []))
        return found

    def rasters_at(self, hour: datetime) -> list[RasterObservation]:
        """Return raster samples acquired in one hour.

        Args:
            hour: Hour-floored timestamp.

        Returns:
            Matching raster observations.
        """
        self._ensure_index()
        assert self._rasters_by_hour is not None
        return self._rasters_by_hour.get(_hour(hour), [])
