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


class AuthError(AeropulseError):
    """Raised when authentication or authorization fails."""

    def __init__(self, message: str, *, status_code: int = 401) -> None:
        super().__init__(message, code="AUTH_ERROR")
        self.status_code = status_code
