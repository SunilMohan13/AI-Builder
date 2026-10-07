"""Versioned canonical contracts independent of source-specific payloads."""

from aeropulse_contracts.alert import Alert
from aeropulse_contracts.citizen import (
    CitizenAnalysis,
    CitizenReport,
    CitizenReportDocument,
    Corroboration,
    CorroborationSignal,
    GeoTrust,
    VisualObservation,
)
from aeropulse_contracts.copilot import CopilotResponse
from aeropulse_contracts.envelope import KafkaEnvelope, ProcessingMode
from aeropulse_contracts.event import (
    EventConfidence,
    EventEvidence,
    EventSeverity,
    EventStatus,
    PollutionEvent,
)
from aeropulse_contracts.feature import GridFeature, SourceLikelihood
from aeropulse_contracts.fire import FireObservation, FireProperties
from aeropulse_contracts.forecast import ForecastResult, GridCellForecast
from aeropulse_contracts.gate_report import (
    GATE_REPORT_SCHEMA,
    MODEL_FAMILIES,
    DatasetLineage,
    EvalMetricRow,
    GateReport,
    ModelFamily,
    RegionGate,
    StrategyResult,
)
from aeropulse_contracts.graph import GraphEdge, GraphNode, GroundedValue, IncidentSummary
from aeropulse_contracts.likelihood import EvidenceItem, SourceLikelihoodV2, SourceScore
from aeropulse_contracts.lineage import EvidenceGraph, LineageEdge, LineageVertex
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.meteo_forecast import MeteoForecast
from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    PointObservationBase,
    Provenance,
    Quality,
)
from aeropulse_contracts.plume import (
    HorizonExposure,
    PlaceArrival,
    Plume,
    PlumeHorizon,
    PlumeOrigin,
    PlumeSummary,
    SourceCandidate,
)
from aeropulse_contracts.prediction import AnomalyResult, GridPrediction
from aeropulse_contracts.provenance import FieldStatus, ProvenanceClass
from aeropulse_contracts.raster import RasterObservation
from aeropulse_contracts.snapshot import (
    AnomalyFlag,
    AqiBandRef,
    CellForecast,
    CellState,
    CitizenWatchSummary,
    FireCluster,
    HazardState,
    RegionSnapshot,
    ServedModel,
    WindVector,
)
from aeropulse_contracts.source_health import SourceHealth, SourceState

#: Every contract a connector's ``normalize`` may return.
CanonicalRecord = (
    Observation | FireObservation | MeteorologicalObservation | RasterObservation | MeteoForecast
)

__all__ = [
    "GATE_REPORT_SCHEMA",
    "MODEL_FAMILIES",
    "Alert",
    "AnomalyFlag",
    "AnomalyResult",
    "AqiBandRef",
    "CanonicalRecord",
    "CellForecast",
    "CellState",
    "CitizenAnalysis",
    "CitizenReport",
    "CitizenReportDocument",
    "CitizenWatchSummary",
    "CopilotResponse",
    "Corroboration",
    "CorroborationSignal",
    "DatasetLineage",
    "EvalMetricRow",
    "EventConfidence",
    "EventEvidence",
    "EventSeverity",
    "EventStatus",
    "EvidenceGraph",
    "EvidenceItem",
    "FieldStatus",
    "FireCluster",
    "FireObservation",
    "FireProperties",
    "ForecastResult",
    "GateReport",
    "GeoTrust",
    "GraphEdge",
    "GraphNode",
    "GridCellForecast",
    "GridFeature",
    "GridPrediction",
    "GroundedValue",
    "HazardState",
    "HorizonExposure",
    "IncidentSummary",
    "KafkaEnvelope",
    "LineageEdge",
    "LineageVertex",
    "Location",
    "Measurement",
    "MeteoForecast",
    "MeteorologicalObservation",
    "ModelFamily",
    "Observation",
    "PlaceArrival",
    "Plume",
    "PlumeHorizon",
    "PlumeOrigin",
    "PlumeSummary",
    "PointObservationBase",
    "PollutionEvent",
    "ProcessingMode",
    "Provenance",
    "ProvenanceClass",
    "Quality",
    "RasterObservation",
    "RegionGate",
    "RegionSnapshot",
    "ServedModel",
    "SourceCandidate",
    "SourceHealth",
    "SourceLikelihood",
    "SourceLikelihoodV2",
    "SourceScore",
    "SourceState",
    "StrategyResult",
    "VisualObservation",
    "WindVector",
]
