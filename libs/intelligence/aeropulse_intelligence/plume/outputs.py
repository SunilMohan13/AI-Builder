"""What an ensemble run means for people and places (APAC LLD 8.2-8.4).

- Footprints: particles binned to H3 cells (resolution 8 inside the display
  area, coarser outside); P50 / P90 are the smallest cell sets holding that
  share of the airborne weight.
- Exposure: population inside the P90 footprint. Labelled "estimated
  population potentially exposed (simulated)" by the caller.
- Arrivals: probability that particles pass within a place's radius, and the
  median first-arrival time among those that do.
- Source candidates (backward): fire clusters inside the back-trajectory
  footprint with the share of particles passing over each. "Likely source
  region", never "caused by".
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import h3
import numpy as np
from aeropulse_contracts import FireCluster
from aeropulse_contracts.plume import PlaceArrival, PlumeHorizon, SourceCandidate

from aeropulse_intelligence.geometry import bearing_deg, haversine_km
from aeropulse_intelligence.plume.ensemble import Domain, EnsembleRun
from aeropulse_intelligence.plume.geo import haversine_km as haversine_km_vec

#: Settings.
INNER_RESOLUTION = 8
OUTER_RESOLUTION = 6
#: Resolution at which a back-trajectory "passes over" a fire cluster.
SOURCE_RESOLUTION = 6
#: Cumulative-share tolerance so float sums at exactly 0.5 / 0.9 behave.
_EPS = 1e-9


@dataclass(frozen=True)
class Place:
    """A gazetteer place (onboarding output)."""

    place_id: str
    name: str
    lat: float
    lon: float
    radius_km: float
    population: float | None = None


@dataclass(frozen=True)
class PopulationIndex:
    """Population per H3 cell, queryable at any coarser or finer resolution.

    ``fine[r]`` sums every population cell at resolution ``>= r`` into its
    resolution-``r`` parent. ``coarse[r]`` keeps cells at resolution ``r`` so a
    finer footprint cell takes ``people / 7^(dr)`` of its coarse ancestor (H3's
    aperture-7 area share).
    """

    source: str
    year: int | None
    fine: Mapping[int, Mapping[str, float]] = field(default_factory=dict)
    coarse: Mapping[int, Mapping[str, float]] = field(default_factory=dict)

    @classmethod
    def from_cells(
        cls,
        cells: Mapping[str, float],
        *,
        source: str,
        year: int | None,
        resolutions: Iterable[int] = (INNER_RESOLUTION, OUTER_RESOLUTION),
    ) -> PopulationIndex:
        targets = sorted(set(resolutions))
        fine: dict[int, dict[str, float]] = {r: defaultdict(float) for r in targets}
        coarse: dict[int, dict[str, float]] = defaultdict(dict)
        for cell, people in cells.items():
            r = h3.get_resolution(cell)
            for target in targets:
                if r >= target:
                    parent = cell if r == target else h3.cell_to_parent(cell, target)
                    fine[target][parent] += float(people)
            if r < max(targets):
                coarse[r][cell] = float(people)
        return cls(source=source, year=year, fine=fine, coarse=dict(coarse))

    def people_in(self, cell: str) -> float:
        r = h3.get_resolution(cell)
        total = float(self.fine.get(r, {}).get(cell, 0.0))
        for coarse_r, cells in self.coarse.items():
            if coarse_r < r:
                ancestor = h3.cell_to_parent(cell, coarse_r)
                total += cells.get(ancestor, 0.0) / 7.0 ** (r - coarse_r)
        return total


def _inside(lat: float, lon: float, display: Domain) -> bool:
    min_lon, min_lat, max_lon, max_lat = display
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def _cell(lat: float, lon: float, display: Domain) -> str:
    res = INNER_RESOLUTION if _inside(lat, lon, display) else OUTER_RESOLUTION
    return h3.latlng_to_cell(lat, lon, res)


def _smallest_share(weights: Mapping[str, float], share: float) -> list[str]:
    total = sum(weights.values())
    if total <= 0:
        return []
    ranked = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))
    out: list[str] = []
    cumulative = 0.0
    for cell, w in ranked:
        out.append(cell)
        cumulative += w
        if cumulative / total >= share - _EPS:
            break
    return out


def horizon_footprint(run: EnsembleRun, horizon_hours: float, display: Domain) -> PlumeHorizon:
    """P50 / P90 cells and the centreline point at one horizon."""
    k = run.step_for(horizon_hours)
    active = run.active[k]
    lat, lon, w = run.lat[k][active], run.lon[k][active], run.weight[k][active]
    weights: dict[str, float] = defaultdict(float)
    for la, lo, wi in zip(lat.tolist(), lon.tolist(), w.tolist(), strict=True):
        weights[_cell(la, lo, display)] += wi
    remaining = float(np.clip(run.weight[k].mean(), 0.0, 1.0))
    return PlumeHorizon(
        horizon_hours=float(horizon_hours),
        p50_cells=_smallest_share(weights, 0.5),
        p90_cells=_smallest_share(weights, 0.9),
        centroid_lat=float(np.median(lat)) if lat.size else None,
        centroid_lon=float(np.median(lon)) if lon.size else None,
        weight_remaining=remaining,
    )


def exposed_population(p90_cells: Sequence[str], population: PopulationIndex) -> float:
    """People inside the P90 footprint; a fine cell under a coarse one counts once."""
    cells = set(p90_cells)
    total = 0.0
    for cell in cells:
        r = h3.get_resolution(cell)
        if any(h3.cell_to_parent(cell, c) in cells for c in range(r) if c >= OUTER_RESOLUTION):
            continue
        total += population.people_in(cell)
    return total


def place_arrivals(
    run: EnsembleRun, places: Sequence[Place], max_hours: float
) -> list[PlaceArrival]:
    """Places the ensemble reaches by ``max_hours``, most likely first."""
    if not places:
        return []
    k_max = run.step_for(max_hours)
    plat = np.array([p.lat for p in places])
    plon = np.array([p.lon for p in places])
    radius = np.array([p.radius_km for p in places])
    n = run.lat.shape[1]
    first = np.full((n, len(places)), np.inf)
    weight_at = np.zeros((n, len(places)))
    for k in range(1, k_max + 1):
        d = haversine_km_vec(run.lat[k][:, None], run.lon[k][:, None], plat[None, :], plon[None, :])
        hit = (d <= radius[None, :]) & run.active[k][:, None] & np.isinf(first)
        first = np.where(hit, run.hours[k], first)
        weight_at = np.where(hit, run.weight[k][:, None], weight_at)
    out: list[PlaceArrival] = []
    for j, place in enumerate(places):
        arrived = np.isfinite(first[:, j])
        if not arrived.any():
            continue
        out.append(
            PlaceArrival(
                place_id=place.place_id,
                name=place.name,
                lat=place.lat,
                lon=place.lon,
                probability=float(np.clip(weight_at[arrived, j].sum() / n, 0.0, 1.0)),
                eta_hours_median=float(np.median(first[arrived, j])),
                population=place.population,
            )
        )
    out.sort(key=lambda a: (-a.probability, a.place_id))
    return out


def _source_cell(cluster: FireCluster) -> str:
    if h3.is_valid_cell(cluster.parent_cell) and (
        h3.get_resolution(cluster.parent_cell) == SOURCE_RESOLUTION
    ):
        return cluster.parent_cell
    return h3.latlng_to_cell(cluster.lat, cluster.lon, SOURCE_RESOLUTION)


def swept_cells(run: EnsembleRun) -> dict[str, int]:
    """Particles that passed over each source-resolution cell at any step."""
    n = run.lat.shape[1]
    visited: list[set[str]] = [set() for _ in range(n)]
    for k in range(1, run.lat.shape[0]):
        for i in np.flatnonzero(run.active[k]).tolist():
            visited[i].add(
                h3.latlng_to_cell(float(run.lat[k, i]), float(run.lon[k, i]), SOURCE_RESOLUTION)
            )
    counts: dict[str, int] = defaultdict(int)
    for cells in visited:
        for cell in cells:
            counts[cell] += 1
    return dict(counts)


def source_candidates(
    run: EnsembleRun,
    fires: Sequence[FireCluster],
    origin_lat: float,
    origin_lon: float,
) -> list[SourceCandidate]:
    """Fire clusters inside the back-trajectory footprint, by particle share.

    The footprint is the swept area, not one horizon: the smallest set of
    source-resolution cells holding 90% of all particle passes.
    """
    if not fires:
        return []
    counts = swept_cells(run)
    footprint = set(_smallest_share({c: float(v) for c, v in counts.items()}, 0.9))
    n = run.lat.shape[1]
    out: list[SourceCandidate] = []
    for cluster in fires:
        cell = _source_cell(cluster)
        if cell not in footprint:
            continue
        share = counts.get(cell, 0) / n
        if share <= 0:
            continue
        out.append(
            SourceCandidate(
                fire_cluster_id=cluster.cluster_id,
                particle_fraction=float(share),
                distance_km=round(
                    haversine_km(origin_lat, origin_lon, cluster.lat, cluster.lon), 3
                ),
                bearing_deg=round(bearing_deg(origin_lat, origin_lon, cluster.lat, cluster.lon), 1),
                frp_total=cluster.frp_total,
            )
        )
    out.sort(key=lambda c: (-c.particle_fraction, c.fire_cluster_id))
    return out
