"""Domain error types for AeroPulse service boundaries."""


class AeropulseError(Exception):
    """Base error for all AeroPulse domain failures."""

    def __init__(self, message: str, *, code: str = "AEROPULSE_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class ContractError(AeropulseError):
    """Raised when a payload cannot be mapped to a canonical contract."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="CONTRACT_ERROR")


class ConnectorError(AeropulseError):
    """Raised when a data connector fetch or health check fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="CONNECTOR_ERROR")


class QualityError(AeropulseError):
    """Raised when quality evaluation cannot complete."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="QUALITY_ERROR")


class RegionPackError(AeropulseError):
    """Raised when a Region Pack, hazard profile, or AQI standard is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="REGION_PACK_ERROR")


class RegionNotFoundError(AeropulseError):
    """Raised when a region id has no loaded pack."""

    def __init__(self, region_id: str) -> None:
        super().__init__(f"unknown region: {region_id}", code="REGION_NOT_FOUND")
        self.region_id = region_id


class StorageError(AeropulseError):
    """Raised when an object, analytics, or snapshot store operation fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="STORAGE_ERROR")


class SnapshotNotFoundError(AeropulseError):
    """Raised when no serving snapshot exists for a region."""

    def __init__(self, region_id: str) -> None:
        super().__init__(f"no snapshot for region: {region_id}", code="SNAPSHOT_NOT_FOUND")
        self.region_id = region_id


class ModelServingError(AeropulseError):
    """Raised when ``model_serving.yaml`` or a served artifact is unusable."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="MODEL_SERVING_ERROR")


class DatasetError(AeropulseError):
    """Raised when a training dataset URI cannot be opened or read."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="DATASET_ERROR")


class TrainingError(AeropulseError):
    """Raised when a family cannot be trained or evaluated on the given rows."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="TRAINING_ERROR")


class LeakageError(AeropulseError):
    """Raised when a pipeline would let information from after ``t`` into a feature."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="LEAKAGE_ERROR")


class AuthError(AeropulseError):
    """Raised when authentication or authorization fails."""

    def __init__(self, message: str, *, status_code: int = 401) -> None:
        super().__init__(message, code="AUTH_ERROR")
        self.status_code = status_code
