"""Replay GeoJSON used when Timescale has no operational rows.

Coordinates and magnitudes match the UI Punjab → Delhi episode so Demo and
Live paint the same corridor. These are fixture observations, not a live
ingest cycle.
"""

from __future__ import annotations

from aeropulse_geospatial.grid import to_grid_id

# 2026-09-08 08:30Z episode clock, aligned with connector fixtures and the UI.
OBSERVED_AT = "2026-09-08T08:30:00Z"
FIRE_AT = "2026-09-08T08:32:00Z"
WEATHER_AT = "2026-09-08T08:30:00Z"

# CPCB-like stations along the transport path. Values are µg/m³ PM2.5.
_STATIONS: list[tuple[str, float, float, float]] = [
    ("Punjab — Ludhiana", 30.901, 75.857, 186.0),
    ("Punjab — Sangrur", 30.241, 75.842, 198.0),
    ("Punjab — Patiala", 30.340, 76.385, 172.0),
    ("Haryana — Ambala", 30.378, 76.780, 164.0),
    ("Haryana — Karnal", 29.686, 76.990, 158.0),
    ("Haryana — Panipat", 29.391, 76.970, 151.0),
    ("Haryana — Sonipat", 28.993, 77.018, 168.0),
    ("Delhi — ITO", 28.628, 77.241, 210.0),
    ("Delhi — RK Puram", 28.563, 77.187, 204.0),
    ("Delhi — Anand Vihar", 28.650, 77.316, 218.0),
    ("Ghaziabad — Indirapuram", 28.641, 77.370, 196.0),
    ("Faridabad — Sector 16", 28.409, 77.317, 174.0),
]

# FIRMS-like detections around the Punjab stubble cluster.
_FIRE_SEEDS: list[tuple[float, float, float, float]] = [
    (30.241, 75.842, 82.4, 0.91),
    (30.268, 75.810, 64.0, 0.88),
    (30.215, 75.880, 71.2, 0.86),
    (30.290, 75.760, 48.5, 0.81),
    (30.180, 75.900, 55.0, 0.84),
    (30.310, 75.920, 39.8, 0.79),
    (30.150, 75.780, 44.1, 0.77),
    (30.330, 75.830, 58.6, 0.85),
    (30.200, 75.950, 36.2, 0.74),
    (30.275, 75.700, 51.0, 0.82),
    (30.355, 75.880, 29.4, 0.71),
    (30.120, 75.840, 41.8, 0.80),
    (30.400, 75.740, 33.0, 0.73),
    (30.225, 75.650, 47.6, 0.83),
    (30.165, 75.990, 22.8, 0.69),
    (30.380, 76.020, 27.5, 0.70),
    (30.090, 75.720, 38.9, 0.76),
    (30.245, 76.050, 31.2, 0.72),
    (30.420, 75.800, 19.6, 0.66),
    (30.280, 76.100, 24.0, 0.68),
    (30.050, 75.860, 35.4, 0.75),
    (30.360, 75.650, 42.7, 0.81),
    (30.190, 75.600, 28.1, 0.70),
    (30.320, 76.150, 21.3, 0.67),
]

_WEATHER: list[tuple[float, float, float, float, float]] = [
    (30.90, 75.85, -1.8, 3.6, 24.2),
    (30.34, 76.38, -2.0, 3.5, 24.8),
    (29.69, 76.99, -2.1, 3.4, 25.1),
    (28.99, 77.02, -2.2, 3.2, 25.6),
    (28.63, 77.24, -2.1, 3.4, 26.1),
    (28.41, 77.32, -1.9, 3.1, 26.4),
]


def _point(lon: float, lat: float, properties: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": properties,
    }


def air_quality_features() -> list[dict]:
    """CPCB-shaped PM2.5 points for the replay episode."""
    features = []
    for name, lat, lon, value in _STATIONS:
        features.append(
            _point(
                lon,
                lat,
                {
                    "source_id": "cpcb",
                    "parameter": "pm25",
                    "value": value,
                    "unit": "ug/m3",
                    "observed_at": OBSERVED_AT,
                    "quality_flag": "valid",
                    "quality_score": 0.92,
                    "grid_id": to_grid_id(lat, lon),
                    "station_name": name,
                },
            )
        )
    return features


def fire_features() -> list[dict]:
    """FIRMS-shaped detections for the Punjab cluster."""
    features = []
    for index, (lat, lon, frp, confidence) in enumerate(_FIRE_SEEDS):
        features.append(
            _point(
                lon,
                lat,
                {
                    "source_id": "firms",
                    "frp": frp,
                    "confidence": confidence,
                    "sensor": "VIIRS",
                    "observed_at": FIRE_AT,
                    "quality_score": confidence,
                    "grid_id": to_grid_id(lat, lon),
                    "detection_id": f"firms_replay_{index}",
                },
            )
        )
    return features


def weather_features() -> list[dict]:
    """IMD-shaped wind samples along the corridor."""
    features = []
    for lat, lon, wind_u, wind_v, temperature in _WEATHER:
        features.append(
            _point(
                lon,
                lat,
                {
                    "source_id": "imd",
                    "wind_u": wind_u,
                    "wind_v": wind_v,
                    "temperature": temperature,
                    "humidity": 42.0,
                    "pressure": 1008.0,
                    "boundary_layer_height": 420.0,
                    "observed_at": WEATHER_AT,
                    "quality_score": 0.9,
                    "grid_id": to_grid_id(lat, lon),
                },
            )
        )
    return features
