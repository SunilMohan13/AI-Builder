"""In-memory replay of the Punjab → Delhi episode used by the UI.

When Timescale is not configured the API still has to answer every `/api/v1`
route the Live toggle hits. This seed writes contract-valid events, grid
features, evidence, forecast, graph and citizen reports so Demo and Live
render the same operator story. It is labelled fixture replay, not an
operational ingest.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aeropulse_contracts.citizen import CitizenReport
from aeropulse_contracts.event import EventEvidence, EventSeverity, EventStatus, PollutionEvent
from aeropulse_contracts.feature import FEATURE_VERSION, GridFeature, SourceLikelihood
from aeropulse_contracts.lineage import EvidenceGraph, LineageEdge, LineageVertex
from aeropulse_geospatial.grid import grid_center, neighbors, to_grid_id
from aeropulse_intelligence.engine import EventStore
from aeropulse_intelligence.forecast import forecast_event

HERO_EVENT_ID = "EVT-1024"
EPISODE_TIME = datetime(2026, 9, 8, 8, 30, tzinfo=UTC)

# (event_id, status, severity, lat, lon, pm25, pm10, detection, source, forecast, impact)
_EVENTS: list[
    tuple[str, EventStatus, EventSeverity, float, float, float, float, float, float, float, float]
] = [
    (
        HERO_EVENT_ID,
        EventStatus.ACTIVE,
        EventSeverity.HIGH,
        30.90,
        75.40,
        185.0,
        240.0,
        0.94,
        0.82,
        0.89,
        0.91,
    ),
    (
        "EVT-1025",
        EventStatus.ACTIVE,
        EventSeverity.CRITICAL,
        28.61,
        77.21,
        210.0,
        268.0,
        0.91,
        0.68,
        0.85,
        0.94,
    ),
    (
        "EVT-1026",
        EventStatus.CONFIRMED,
        EventSeverity.MEDIUM,
        29.39,
        76.97,
        95.0,
        128.0,
        0.78,
        0.71,
        0.72,
        0.65,
    ),
    (
        "EVT-1027",
        EventStatus.FORECASTING,
        EventSeverity.MEDIUM,
        28.21,
        76.28,
        118.0,
        268.0,
        0.83,
        0.76,
        0.71,
        0.58,
    ),
    (
        "EVT-1028",
        EventStatus.DECLINING,
        EventSeverity.HIGH,
        28.98,
        77.02,
        152.0,
        196.0,
        0.88,
        0.64,
        0.81,
        0.79,
    ),
]

_LIKELIHOODS: dict[str, SourceLikelihood] = {
    HERO_EVENT_ID: SourceLikelihood(
        biomass_burning=0.78,
        regional_transport=0.62,
        industrial=0.11,
        traffic=0.07,
        dust=0.04,
    ),
    "EVT-1025": SourceLikelihood(
        biomass_burning=0.12,
        regional_transport=0.58,
        industrial=0.34,
        traffic=0.72,
        dust=0.18,
    ),
    "EVT-1026": SourceLikelihood(
        biomass_burning=0.08,
        regional_transport=0.14,
        industrial=0.81,
        traffic=0.15,
        dust=0.22,
    ),
    "EVT-1027": SourceLikelihood(
        biomass_burning=0.05,
        regional_transport=0.41,
        industrial=0.12,
        traffic=0.19,
        dust=0.84,
    ),
    "EVT-1028": SourceLikelihood(
        biomass_burning=0.52,
        regional_transport=0.79,
        industrial=0.16,
        traffic=0.28,
        dust=0.09,
    ),
}

_HERO_EVIDENCE = [
    ("ev_1", "firms_fire", "42 active fire detections in Punjab corridor", 0.91),
    ("ev_2", "cpcb_anomaly", "PM2.5 increased 68% across 6 stations within 30 min", 0.96),
    ("ev_3", "sentinel5p_no2", "Elevated NO₂ column over source region", 0.84),
    ("ev_4", "imd_wind", "SE wind 14 km/h aligned with transport corridor", 0.94),
    ("ev_5", "cams_transport", "Regional transport signal supports plume movement", 0.78),
    ("ev_6", "forecast_advection", "Plume trajectory toward Delhi NCR within 6h", 0.89),
    ("ev_7", "citizen_report", "Geotagged smoke photo near Sangrur, 11 km from fire cluster", 0.62),
    (
        "ev_8",
        "modis_aod_gap",
        "AOD retrieval unavailable over source region — 78% cloud cover",
        0.41,
    ),
]


def seed_replay_episode(store: EventStore | None = None) -> None:
    """Populate the current process store with the UI hero episode if it is empty."""
    from aeropulse_api.event_store import current_store

    target = store if store is not None else current_store()
    if target.events:
        return
    _seed_grid(target)
    _seed_events(target)
    _seed_forecast(target)
    _seed_graph(target)
    _seed_citizen(target)
    _seed_alerts(target)


def _seed_alerts(store: EventStore) -> None:
    """Raise alerts for the seeded HIGH/CRITICAL events.

    Alerts are normally produced worker-side. Seeding them here means the
    notification drawer has something to show against a database-free API,
    matching how events, forecasts and citizen reports are already seeded.
    """
    from aeropulse_intelligence.alerts import alert_from_event

    for event_id, event in store.events.items():
        alert = alert_from_event(event, store.evidence.get(event_id, []))
        if alert is not None:
            store.alerts[alert.alert_id] = alert


def _seed_grid(store: EventStore) -> None:
    punjab = (30.90, 75.40)
    delhi = (28.61, 77.21)
    samples = 36
    for i in range(samples):
        t = i / (samples - 1)
        lat = punjab[0] + (delhi[0] - punjab[0]) * t
        lon = punjab[1] + (delhi[1] - punjab[1]) * t
        # High at the Punjab source, a Haryana trough, then the NCR spike.
        if t < 0.35:
            pm25 = 185 + 20 * (t / 0.35)
        elif t < 0.7:
            pm25 = 205 - 45 * ((t - 0.35) / 0.35)
        else:
            pm25 = 160 + 50 * ((t - 0.7) / 0.3)
        _put_cell(
            store,
            lat,
            lon,
            pm25,
            fire_count=24 if t < 0.25 else 0,
            fire_frp=82.0 if t < 0.25 else 0.0,
        )
        origin = to_grid_id(lat, lon)
        for neighbor in neighbors(origin, k=1)[:4]:
            nlat, nlon = grid_center(neighbor)
            _put_cell(store, nlat, nlon, max(40.0, pm25 - 18), fire_count=0, fire_frp=0.0)


def _put_cell(
    store: EventStore,
    lat: float,
    lon: float,
    pm25: float,
    *,
    fire_count: int,
    fire_frp: float,
) -> None:
    grid_id = to_grid_id(lat, lon)
    if grid_id in store.latest_features:
        return
    center_lat, center_lon = grid_center(grid_id)
    # Dominant likelihood follows the corridor: biomass in Punjab, traffic in NCR.
    biomass = max(0.05, min(0.85, (center_lat - 28.4) / 3.0))
    traffic = max(0.05, min(0.75, (28.9 - center_lat) / 2.2 + 0.2))
    feature = GridFeature(
        grid_id=grid_id,
        timestamp=EPISODE_TIME,
        center_lat=center_lat,
        center_lon=center_lon,
        pm25=round(pm25, 1),
        pm10=round(pm25 * 1.28, 1),
        no2=round(pm25 * 0.22, 1),
        wind_u=-2.1,
        wind_v=3.4,
        wind_speed=4.0,
        temperature=25.1,
        humidity=42.0,
        boundary_layer_height=420.0,
        fire_count=fire_count,
        fire_frp=fire_frp,
        fire_confidence=0.91 if fire_count else None,
        upwind_fire_score=0.72 if fire_count else 0.18,
        population=12_400.0 if center_lat < 28.9 else 3_800.0,
        pm25_estimate=round(pm25, 1),
        estimate_confidence=0.82,
        anomaly_score=0.78 if pm25 >= 121 else 0.22,
        source_likelihood=SourceLikelihood(
            biomass_burning=round(biomass, 2),
            regional_transport=0.55,
            industrial=0.14,
            traffic=round(traffic, 2),
            dust=0.08,
        ),
        quality_score=0.88,
        source_count=4,
        missing_feature_count=2,
        feature_version=FEATURE_VERSION,
    )
    store.latest_features[grid_id] = feature
    store.features[grid_id] = feature


def _seed_events(store: EventStore) -> None:
    for event_id, status, severity, lat, lon, pm25, _pm10, det, src, fcst, impact in _EVENTS:
        grid_id = to_grid_id(lat, lon)
        _put_cell(
            store,
            lat,
            lon,
            pm25,
            fire_count=42 if event_id == HERO_EVENT_ID else 0,
            fire_frp=82.0 if event_id == HERO_EVENT_ID else 0.0,
        )
        feature = store.latest_features[grid_id]
        feature.source_likelihood = _LIKELIHOODS[event_id]
        if event_id == HERO_EVENT_ID:
            feature.fire_count = 42
            feature.fire_frp = 82.0
        evidence = _evidence_for(event_id, grid_id)
        event = PollutionEvent(
            event_id=event_id,
            status=status,
            severity=severity,
            created_at=EPISODE_TIME,
            updated_at=EPISODE_TIME,
            geometry=f"POINT({lon} {lat})",
            grid_ids=[grid_id],
            pollutants=["PM2.5", "PM10"],
            detection_confidence=det,
            source_confidence=src,
            forecast_confidence=fcst,
            impact_confidence=impact,
            overall_confidence=round((det + src + fcst + impact) / 4, 2),
            evidence_ids=[item.evidence_id for item in evidence],
            model_versions=["baseline-idw-0.1", "source-likelihood-0.1", "wind-advection-0.1"],
            feature_version=FEATURE_VERSION,
            evidence_freshness=0.94,
            sensor_coverage=0.81,
        )
        store.events[event_id] = event
        store.evidence[event_id] = evidence
        store.open_by_grid[grid_id] = event_id


def _evidence_for(event_id: str, grid_id: str) -> list[EventEvidence]:
    if event_id != HERO_EVENT_ID:
        return [
            EventEvidence(
                evidence_id=f"{event_id}_cpcb",
                evidence_type="cpcb_anomaly",
                grid_id=grid_id,
                summary=f"Station PM2.5 corroborates {event_id}",
                quality_score=0.8,
            )
        ]
    return [
        EventEvidence(
            evidence_id=eid,
            evidence_type=kind,
            grid_id=grid_id,
            summary=summary,
            quality_score=quality,
        )
        for eid, kind, summary, quality in _HERO_EVIDENCE
    ]


def _seed_forecast(store: EventStore) -> None:
    event = store.events[HERO_EVENT_ID]
    origin = event.grid_ids[0]
    feature = store.latest_features[origin]
    forecast = forecast_event(
        event,
        origin_grid_id=origin,
        origin_lat=feature.center_lat,
        origin_lon=feature.center_lon,
        pm25=feature.pm25 or 185.0,
        wind_u=feature.wind_u,
        wind_v=feature.wind_v,
        boundary_layer_height=feature.boundary_layer_height,
    )
    store.forecasts[HERO_EVENT_ID] = forecast
    event.forecast_confidence = 0.89


def _seed_graph(store: EventStore) -> None:
    now = EPISODE_TIME
    vertices = [
        LineageVertex(
            id=HERO_EVENT_ID,
            type="PollutionEvent",
            properties={"label": "Agricultural burning event"},
        ),
        LineageVertex(id="firms", type="Fire", properties={"label": "FIRMS"}),
        LineageVertex(id="cpcb", type="Observation", properties={"label": "CPCB"}),
        LineageVertex(id="sentinel5p", type="Satellite", properties={"label": "Sentinel-5P"}),
        LineageVertex(id="imd", type="Weather", properties={"label": "IMD"}),
        LineageVertex(id="cams", type="Model", properties={"label": "CAMS"}),
        LineageVertex(id="forecast", type="Forecast", properties={"label": "Forecast"}),
    ]
    edges = []
    for index, vertex in enumerate(vertices[1:]):
        edges.append(
            LineageEdge(
                edge_id=f"edge_{vertex.id}",
                edge_type="supports",
                from_id=vertex.id,
                to_id=HERO_EVENT_ID,
                confidence=0.9 - index * 0.04,
                evidence_ids=[f"ev_{index + 1}"],
                model_version="event-engine-0.1",
                created_at=now,
            )
        )
    store.graphs[HERO_EVENT_ID] = EvidenceGraph(
        event_id=HERO_EVENT_ID,
        vertices=vertices,
        edges=edges,
    )


def _seed_citizen(store: EventStore) -> None:
    reports = [
        ("cit_cr1", 28.65, 77.18, "haze", "Heavy haze over Delhi", "haze", "pending"),
        ("cit_cr4", 29.39, 76.97, "haze", "Visibility reduced — Panipat", "haze", "pending"),
        ("cit_cr5", 29.69, 76.99, "smoke", "Smoke plume visible — Karnal", "smoke", "accepted"),
        ("cit_cr9", 30.24, 75.84, "smoke", "Field burning observed — Sangrur", "smoke", "accepted"),
    ]
    for report_id, lat, lon, observation_type, notes, cv_class, moderation in reports:
        correlated = HERO_EVENT_ID if moderation == "accepted" else None
        store.citizen_reports[report_id] = CitizenReport(
            report_id=report_id,
            lat=lat,
            lon=lon,
            observed_at=EPISODE_TIME,
            observation_type=observation_type,
            notes=notes,
            cv_class=cv_class,  # type: ignore[arg-type]
            moderation=moderation,  # type: ignore[arg-type]
            grid_id=to_grid_id(lat, lon),
            correlated_event_id=correlated,
        )
