"""Timescale persistence for observations, events, forecasts, and lineage."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from aeropulse_contracts.alert import Alert
from aeropulse_contracts.event import EventEvidence, PollutionEvent
from aeropulse_contracts.feature import GridFeature
from aeropulse_contracts.fire import FireObservation
from aeropulse_contracts.forecast import ForecastResult
from aeropulse_contracts.lineage import EvidenceGraph
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import Observation
from aeropulse_contracts.prediction import GridPrediction
from aeropulse_contracts.raster import RasterObservation

UPSERT_AQ = """
INSERT INTO air_quality_observation (
    time, observation_id, source_id, source_record_id, station_id, grid_id,
    parameter, value, unit, quality_flag, quality_score, latitude, longitude,
    raw_uri, dedup_key
) VALUES (
    %(time)s, %(observation_id)s, %(source_id)s, %(source_record_id)s, %(station_id)s,
    %(grid_id)s, %(parameter)s, %(value)s, %(unit)s, %(quality_flag)s, %(quality_score)s,
    %(latitude)s, %(longitude)s, %(raw_uri)s, %(dedup_key)s
)
ON CONFLICT (dedup_key, time) DO NOTHING
"""

UPSERT_FIRE = """
INSERT INTO fire_observation (
    time, observation_id, source_id, source_record_id, grid_id, frp, confidence,
    sensor, quality_score, latitude, longitude, raw_uri, dedup_key
) VALUES (
    %(time)s, %(observation_id)s, %(source_id)s, %(source_record_id)s, %(grid_id)s,
    %(frp)s, %(confidence)s, %(sensor)s, %(quality_score)s, %(latitude)s, %(longitude)s,
    %(raw_uri)s, %(dedup_key)s
)
ON CONFLICT (dedup_key, time) DO NOTHING
"""

UPSERT_WX = """
INSERT INTO weather_observation (
    time, observation_id, source_id, source_record_id, grid_id, wind_u, wind_v,
    temperature, humidity, pressure, boundary_layer_height, quality_score,
    latitude, longitude, raw_uri, dedup_key
) VALUES (
    %(time)s, %(observation_id)s, %(source_id)s, %(source_record_id)s, %(grid_id)s,
    %(wind_u)s, %(wind_v)s, %(temperature)s, %(humidity)s, %(pressure)s,
    %(boundary_layer_height)s, %(quality_score)s, %(latitude)s, %(longitude)s,
    %(raw_uri)s, %(dedup_key)s
)
ON CONFLICT (dedup_key, time) DO NOTHING
"""

UPSERT_GRID_FEATURE = """
INSERT INTO grid_feature (
    time, grid_id, feature_version, center_lat, center_lon, pm25, pm10,
    station_distance, wind_u, wind_v, wind_speed, wind_direction, temperature,
    humidity, pressure, boundary_layer_height, fire_count, fire_frp,
    fire_confidence, upwind_fire_score, pm25_estimate, estimate_confidence,
    anomaly_score, quality_score, source_count, missing_feature_count, payload
) VALUES (
    %(time)s, %(grid_id)s, %(feature_version)s, %(center_lat)s, %(center_lon)s,
    %(pm25)s, %(pm10)s, %(station_distance)s, %(wind_u)s, %(wind_v)s,
    %(wind_speed)s, %(wind_direction)s, %(temperature)s, %(humidity)s,
    %(pressure)s, %(boundary_layer_height)s, %(fire_count)s, %(fire_frp)s,
    %(fire_confidence)s, %(upwind_fire_score)s, %(pm25_estimate)s,
    %(estimate_confidence)s, %(anomaly_score)s, %(quality_score)s,
    %(source_count)s, %(missing_feature_count)s, %(payload)s::jsonb
)
ON CONFLICT (time, grid_id) DO UPDATE SET
    feature_version = EXCLUDED.feature_version,
    pm25 = EXCLUDED.pm25,
    pm10 = EXCLUDED.pm10,
    station_distance = EXCLUDED.station_distance,
    wind_u = EXCLUDED.wind_u,
    wind_v = EXCLUDED.wind_v,
    wind_speed = EXCLUDED.wind_speed,
    wind_direction = EXCLUDED.wind_direction,
    temperature = EXCLUDED.temperature,
    humidity = EXCLUDED.humidity,
    pressure = EXCLUDED.pressure,
    boundary_layer_height = EXCLUDED.boundary_layer_height,
    fire_count = EXCLUDED.fire_count,
    fire_frp = EXCLUDED.fire_frp,
    fire_confidence = EXCLUDED.fire_confidence,
    upwind_fire_score = EXCLUDED.upwind_fire_score,
    pm25_estimate = EXCLUDED.pm25_estimate,
    estimate_confidence = EXCLUDED.estimate_confidence,
    anomaly_score = EXCLUDED.anomaly_score,
    quality_score = EXCLUDED.quality_score,
    source_count = EXCLUDED.source_count,
    missing_feature_count = EXCLUDED.missing_feature_count,
    payload = EXCLUDED.payload
"""

UPSERT_GRID_PREDICTION = """
INSERT INTO grid_prediction (
    time, grid_id, model_version, pm25_estimate, prediction_interval_low,
    prediction_interval_high, confidence
) VALUES (
    %(time)s, %(grid_id)s, %(model_version)s, %(pm25_estimate)s,
    %(prediction_interval_low)s, %(prediction_interval_high)s, %(confidence)s
)
ON CONFLICT (time, grid_id, model_version) DO UPDATE SET
    pm25_estimate = EXCLUDED.pm25_estimate,
    prediction_interval_low = EXCLUDED.prediction_interval_low,
    prediction_interval_high = EXCLUDED.prediction_interval_high,
    confidence = EXCLUDED.confidence
"""

UPSERT_SHADOW_PREDICTION = """
INSERT INTO shadow_prediction (
    time, grid_id, model_name, model_version, stage, shadow_value,
    champion_value, feature_hash, feature_completeness, error, payload
) VALUES (
    %(time)s, %(grid_id)s, %(model_name)s, %(model_version)s, %(stage)s,
    %(shadow_value)s, %(champion_value)s, %(feature_hash)s,
    %(feature_completeness)s, %(error)s, %(payload)s
)
ON CONFLICT (time, grid_id, model_name, model_version) DO UPDATE SET
    stage = EXCLUDED.stage,
    shadow_value = EXCLUDED.shadow_value,
    champion_value = EXCLUDED.champion_value,
    feature_hash = EXCLUDED.feature_hash,
    feature_completeness = EXCLUDED.feature_completeness,
    error = EXCLUDED.error,
    payload = EXCLUDED.payload
"""

UPSERT_RASTER = """
INSERT INTO raster_observation (
    acquisition_time, observation_id, source_id, source_record_id, product_id,
    processing_time, min_lon, min_lat, max_lon, max_lat, crs, resolution,
    object_uri, checksum, cloud_fraction, quality_score, sample_aod, sample_no2,
    sample_pm25, payload
) VALUES (
    %(acquisition_time)s, %(observation_id)s, %(source_id)s, %(source_record_id)s,
    %(product_id)s, %(processing_time)s, %(min_lon)s, %(min_lat)s, %(max_lon)s,
    %(max_lat)s, %(crs)s, %(resolution)s, %(object_uri)s, %(checksum)s,
    %(cloud_fraction)s, %(quality_score)s, %(sample_aod)s, %(sample_no2)s,
    %(sample_pm25)s, %(payload)s::jsonb
)
ON CONFLICT (acquisition_time, observation_id) DO UPDATE SET
    processing_time = EXCLUDED.processing_time,
    object_uri = EXCLUDED.object_uri,
    checksum = EXCLUDED.checksum,
    quality_score = EXCLUDED.quality_score,
    payload = EXCLUDED.payload
"""

UPSERT_ALERT = """
INSERT INTO alert (
    alert_id, event_id, severity, recipient_group, message_template, message,
    evidence, channel, created_at, expires_at
) VALUES (
    %(alert_id)s, %(event_id)s, %(severity)s, %(recipient_group)s,
    %(message_template)s, %(message)s, %(evidence)s::jsonb, %(channel)s,
    %(created_at)s, %(expires_at)s
)
ON CONFLICT (alert_id) DO UPDATE SET
    severity = EXCLUDED.severity,
    message = EXCLUDED.message,
    evidence = EXCLUDED.evidence,
    expires_at = EXCLUDED.expires_at
"""


UPSERT_EVENT = """
INSERT INTO pollution_event (
    event_id, event_type, status, severity, created_at, updated_at, geometry,
    grid_ids, pollutants, detection_confidence, source_confidence,
    forecast_confidence, impact_confidence, overall_confidence, evidence_ids,
    model_versions, feature_version, evidence_freshness, sensor_coverage, payload
) VALUES (
    %(event_id)s, %(event_type)s, %(status)s, %(severity)s, %(created_at)s,
    %(updated_at)s, %(geometry)s, %(grid_ids)s, %(pollutants)s,
    %(detection_confidence)s, %(source_confidence)s, %(forecast_confidence)s,
    %(impact_confidence)s, %(overall_confidence)s, %(evidence_ids)s,
    %(model_versions)s, %(feature_version)s, %(evidence_freshness)s,
    %(sensor_coverage)s, %(payload)s::jsonb
)
ON CONFLICT (event_id) DO UPDATE SET
    status = EXCLUDED.status,
    updated_at = EXCLUDED.updated_at,
    payload = EXCLUDED.payload
"""


class TimescaleRepository:
    """psycopg-backed observation and intelligence repository."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def upsert_air_quality(self, observation: Observation) -> bool:
        """Insert air quality; return False on duplicate key."""
        with self.conn.cursor() as cur:
            cur.execute(
                UPSERT_AQ,
                {
                    "time": observation.observed_at,
                    "observation_id": observation.observation_id,
                    "source_id": observation.source_id,
                    "source_record_id": observation.source_record_id,
                    "station_id": observation.source_record_id.split("_")[0],
                    "grid_id": observation.grid_id,
                    "parameter": observation.measurement.parameter,
                    "value": observation.measurement.value,
                    "unit": observation.measurement.unit,
                    "quality_flag": observation.quality.quality_flag,
                    "quality_score": observation.quality.quality_score,
                    "latitude": observation.location.lat,
                    "longitude": observation.location.lon,
                    "raw_uri": observation.provenance.raw_object_uri,
                    "dedup_key": observation.dedup_key,
                },
            )
            inserted = cur.rowcount == 1
        self.conn.commit()
        return inserted

    def upsert_fire(self, observation: FireObservation) -> bool:
        """Insert fire observation; return False on duplicate key."""
        with self.conn.cursor() as cur:
            cur.execute(
                UPSERT_FIRE,
                {
                    "time": observation.observed_at,
                    "observation_id": observation.observation_id,
                    "source_id": observation.source_id,
                    "source_record_id": observation.source_record_id,
                    "grid_id": observation.grid_id,
                    "frp": observation.fire.frp,
                    "confidence": observation.fire.confidence,
                    "sensor": observation.fire.sensor,
                    "quality_score": observation.quality.quality_score,
                    "latitude": observation.location.lat,
                    "longitude": observation.location.lon,
                    "raw_uri": observation.provenance.raw_object_uri,
                    "dedup_key": observation.dedup_key,
                },
            )
            inserted = cur.rowcount == 1
        self.conn.commit()
        return inserted

    def upsert_weather(self, observation: MeteorologicalObservation) -> bool:
        """Insert weather observation; return False on duplicate key."""
        with self.conn.cursor() as cur:
            cur.execute(
                UPSERT_WX,
                {
                    "time": observation.observed_at,
                    "observation_id": observation.observation_id,
                    "source_id": observation.source_id,
                    "source_record_id": observation.source_record_id,
                    "grid_id": observation.grid_id,
                    "wind_u": observation.wind_u,
                    "wind_v": observation.wind_v,
                    "temperature": observation.temperature,
                    "humidity": observation.humidity,
                    "pressure": observation.pressure,
                    "boundary_layer_height": observation.boundary_layer_height,
                    "quality_score": observation.quality.quality_score,
                    "latitude": observation.location.lat,
                    "longitude": observation.location.lon,
                    "raw_uri": observation.provenance.raw_object_uri,
                    "dedup_key": observation.dedup_key,
                },
            )
            inserted = cur.rowcount == 1
        self.conn.commit()
        return inserted

    def upsert_grid_feature(self, feature: GridFeature) -> None:
        """Insert or refresh one grid-hour feature row (LLD §13/§20)."""
        with self.conn.cursor() as cur:
            cur.execute(
                UPSERT_GRID_FEATURE,
                {
                    "time": feature.timestamp,
                    "grid_id": feature.grid_id,
                    "feature_version": feature.feature_version,
                    "center_lat": feature.center_lat,
                    "center_lon": feature.center_lon,
                    "pm25": feature.pm25,
                    "pm10": feature.pm10,
                    "station_distance": feature.station_distance,
                    "wind_u": feature.wind_u,
                    "wind_v": feature.wind_v,
                    "wind_speed": feature.wind_speed,
                    "wind_direction": feature.wind_direction,
                    "temperature": feature.temperature,
                    "humidity": feature.humidity,
                    "pressure": feature.pressure,
                    "boundary_layer_height": feature.boundary_layer_height,
                    "fire_count": feature.fire_count,
                    "fire_frp": feature.fire_frp,
                    "fire_confidence": feature.fire_confidence,
                    "upwind_fire_score": feature.upwind_fire_score,
                    "pm25_estimate": feature.pm25_estimate,
                    "estimate_confidence": feature.estimate_confidence,
                    "anomaly_score": feature.anomaly_score,
                    "quality_score": feature.quality_score,
                    "source_count": feature.source_count,
                    "missing_feature_count": feature.missing_feature_count,
                    "payload": json.dumps(feature.model_dump(mode="json")),
                },
            )
        self.conn.commit()

    def upsert_grid_prediction(self, prediction: GridPrediction) -> None:
        """Insert or refresh one grid-hour PM2.5 prediction row (LLD §13/§20)."""
        with self.conn.cursor() as cur:
            cur.execute(
                UPSERT_GRID_PREDICTION,
                {
                    "time": prediction.timestamp,
                    "grid_id": prediction.grid_id,
                    "model_version": prediction.model_version,
                    "pm25_estimate": prediction.pm25_estimate,
                    "prediction_interval_low": prediction.prediction_interval_low,
                    "prediction_interval_high": prediction.prediction_interval_high,
                    "confidence": prediction.confidence,
                },
            )
        self.conn.commit()

    def upsert_shadow_prediction(self, prediction: Any) -> None:
        """Record one challenger's output beside the champion's.

        Rows carrying an ``error`` are written rather than skipped: a
        challenger that produced nothing all season is a finding, and dropping
        those rows would make it look identical to one never registered.

        Args:
            prediction: A ``ShadowPrediction`` from ``aeropulse_ml.shadow``.
                Typed as ``Any`` so the worker's persistence layer does not
                take a hard dependency on ``libs/ml``.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                UPSERT_SHADOW_PREDICTION,
                {
                    "time": prediction.timestamp,
                    "grid_id": prediction.grid_id,
                    "model_name": prediction.model_name,
                    "model_version": prediction.model_version,
                    "stage": prediction.stage,
                    "shadow_value": prediction.shadow_value,
                    "champion_value": prediction.champion_value,
                    "feature_hash": prediction.feature_hash,
                    "feature_completeness": prediction.feature_completeness,
                    "error": prediction.error,
                    "payload": json.dumps(prediction.payload, default=str),
                },
            )
        self.conn.commit()

    def upsert_raster(self, observation: RasterObservation) -> bool:
        """Insert or refresh raster metadata; large arrays stay in object storage."""
        min_lon, min_lat, max_lon, max_lat = observation.bbox
        with self.conn.cursor() as cur:
            cur.execute(
                UPSERT_RASTER,
                {
                    "acquisition_time": observation.acquisition_time,
                    "observation_id": observation.observation_id,
                    "source_id": observation.source_id,
                    "source_record_id": observation.source_record_id,
                    "product_id": observation.product_id,
                    "processing_time": observation.processing_time,
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                    "crs": observation.crs,
                    "resolution": observation.resolution,
                    "object_uri": observation.object_uri,
                    "checksum": observation.checksum,
                    "cloud_fraction": observation.cloud_fraction,
                    "quality_score": observation.quality.quality_score,
                    "sample_aod": observation.sample_aod,
                    "sample_no2": observation.sample_no2,
                    "sample_pm25": observation.sample_pm25,
                    "payload": json.dumps(observation.model_dump(mode="json")),
                },
            )
            inserted = cur.rowcount == 1
        self.conn.commit()
        return inserted

    def record_dlq(self, source_id: str, payload: dict[str, Any], error: str) -> None:
        """Insert a dead-letter row."""
        sql = """
        INSERT INTO connector_dead_letter (source_id, payload, error)
        VALUES (%s, %s::jsonb, %s)
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (source_id, json.dumps(payload), error))
        self.conn.commit()

    def upsert_source_health(
        self,
        source_id: str,
        records: int,
        status: str = "HEALTHY",
        *,
        latency_ms: int | None = None,
        error: str | None = None,
        processing_mode: str | None = None,
    ) -> None:
        """Upsert connector run health. Failures keep the previous success time."""
        success = status in {"HEALTHY", "REPLAY", "REPLAY_EXHAUSTED"}
        stamp = datetime.now(UTC) if success else None
        sql = """
        INSERT INTO source_health (
            source_id, status, last_success_at, last_record_at, records_per_run,
            latency_ms, last_error, processing_mode, updated_at
        )
        VALUES (
            %(source_id)s, %(status)s, %(last_success_at)s, %(last_record_at)s,
            %(records)s, %(latency_ms)s, %(error)s, %(processing_mode)s, now()
        )
        ON CONFLICT (source_id) DO UPDATE SET
            status = EXCLUDED.status,
            last_success_at = COALESCE(EXCLUDED.last_success_at, source_health.last_success_at),
            last_record_at = COALESCE(EXCLUDED.last_record_at, source_health.last_record_at),
            records_per_run = EXCLUDED.records_per_run,
            latency_ms = EXCLUDED.latency_ms,
            last_error = EXCLUDED.last_error,
            processing_mode = EXCLUDED.processing_mode,
            updated_at = EXCLUDED.updated_at
        """
        with self.conn.cursor() as cur:
            try:
                cur.execute(
                    sql,
                    {
                        "source_id": source_id,
                        "status": status,
                        "last_success_at": stamp,
                        "last_record_at": stamp,
                        "records": records,
                        "latency_ms": latency_ms,
                        "error": error,
                        "processing_mode": processing_mode,
                    },
                )
            except Exception:
                self.conn.rollback()
                raise
        self.conn.commit()

    def upsert_checkpoint(self, source_id: str, cursor: str) -> None:
        """Persist the last processed cursor for a source."""
        sql = """
        INSERT INTO connector_checkpoint (source_id, cursor, updated_at)
        VALUES (%(source_id)s, %(cursor)s, now())
        ON CONFLICT (source_id) DO UPDATE SET
            cursor = EXCLUDED.cursor,
            updated_at = now()
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, {"source_id": source_id, "cursor": cursor})
        self.conn.commit()

    def get_checkpoint(self, source_id: str) -> str | None:
        """Return the last saved cursor for a source, if any."""
        sql = "SELECT cursor FROM connector_checkpoint WHERE source_id = %(source_id)s"
        with self.conn.cursor() as cur:
            try:
                cur.execute(sql, {"source_id": source_id})
                row = cur.fetchone()
            except Exception:
                self.conn.rollback()
                raise
        return row[0] if row else None

    def upsert_alert(self, alert: Alert) -> None:
        """Insert or update one alert row.

        Alerts are produced worker-side by the event engine. Without this the
        API process never sees them and GET /api/v1/alerts is empty in every
        deployment.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                UPSERT_ALERT,
                {
                    "alert_id": alert.alert_id,
                    "event_id": alert.event_id,
                    "severity": alert.severity,
                    "recipient_group": alert.recipient_group,
                    "message_template": alert.message_template,
                    "message": alert.message,
                    "evidence": json.dumps(alert.evidence),
                    "channel": alert.channel,
                    "created_at": alert.created_at,
                    "expires_at": alert.expires_at,
                },
            )
        self.conn.commit()

    def upsert_event(self, event: PollutionEvent) -> None:
        """Insert or update a pollution event row."""
        with self.conn.cursor() as cur:
            cur.execute(
                UPSERT_EVENT,
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "status": event.status.value,
                    "severity": event.severity.value,
                    "created_at": event.created_at,
                    "updated_at": event.updated_at,
                    "geometry": event.geometry,
                    "grid_ids": event.grid_ids,
                    "pollutants": event.pollutants,
                    "detection_confidence": event.detection_confidence,
                    "source_confidence": event.source_confidence,
                    "forecast_confidence": event.forecast_confidence,
                    "impact_confidence": event.impact_confidence,
                    "overall_confidence": event.overall_confidence,
                    "evidence_ids": event.evidence_ids,
                    "model_versions": event.model_versions,
                    "feature_version": event.feature_version,
                    "evidence_freshness": event.evidence_freshness,
                    "sensor_coverage": event.sensor_coverage,
                    "payload": json.dumps(event.model_dump(mode="json")),
                },
            )
        self.conn.commit()

    def insert_evidence(self, event_id: str, items: list[EventEvidence]) -> None:
        """Insert evidence rows (ignore duplicates)."""
        sql = """
        INSERT INTO event_evidence (
            evidence_id, event_id, evidence_type, observation_id, grid_id, summary, quality_score
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (evidence_id) DO NOTHING
        """
        with self.conn.cursor() as cur:
            for item in items:
                cur.execute(
                    sql,
                    (
                        item.evidence_id,
                        event_id,
                        item.evidence_type,
                        item.observation_id,
                        item.grid_id,
                        item.summary,
                        item.quality_score,
                    ),
                )
        self.conn.commit()

    def insert_graph(self, graph: EvidenceGraph) -> None:
        """Persist lineage edges."""
        sql = """
        INSERT INTO evidence_edge (
            edge_id, event_id, edge_type, from_id, to_id, confidence, evidence_ids, model_version, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (edge_id) DO NOTHING
        """
        with self.conn.cursor() as cur:
            for edge in graph.edges:
                cur.execute(
                    sql,
                    (
                        edge.edge_id,
                        graph.event_id,
                        edge.edge_type,
                        edge.from_id,
                        edge.to_id,
                        edge.confidence,
                        edge.evidence_ids,
                        edge.model_version,
                        edge.created_at,
                    ),
                )
        self.conn.commit()

    def insert_forecast(self, forecast: ForecastResult) -> None:
        """Persist forecast cells."""
        sql = """
        INSERT INTO forecast_value (
            time, event_id, origin_grid_id, grid_id, horizon_hours, pm25, confidence,
            model_version, cams_applied
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (time, grid_id, horizon_hours, model_version) DO NOTHING
        """
        with self.conn.cursor() as cur:
            for idx, cell in enumerate(forecast.grid_predictions):
                horizon = (
                    0 if idx == 0 else forecast.horizons[min(idx - 1, len(forecast.horizons) - 1)]
                )
                cur.execute(
                    sql,
                    (
                        forecast.generated_at,
                        forecast.event_id,
                        forecast.origin_grid_id,
                        cell.grid_id,
                        horizon,
                        cell.pm25,
                        cell.confidence,
                        forecast.model_version,
                        forecast.cams_applied,
                    ),
                )
        self.conn.commit()
