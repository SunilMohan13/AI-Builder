"""Storage failures. Writes raise; nothing returns a URI that points at nothing."""

from __future__ import annotations

from aeropulse_common.errors import AeropulseError


class StorageError(AeropulseError):
    def __init__(self, message: str, *, code: str = "STORAGE_ERROR") -> None:
        super().__init__(message, code=code)


class ObjectNotFoundError(StorageError):
    def __init__(self, key: str) -> None:
        super().__init__(f"object not found: {key}", code="OBJECT_NOT_FOUND")
        self.key = key


class PreconditionFailedError(StorageError):
    """The object's generation did not match ``if_generation_match``."""

    def __init__(self, key: str, expected: int, actual: int | None) -> None:
        super().__init__(
            f"generation precondition failed for {key}: expected {expected}, found {actual}",
            code="PRECONDITION_FAILED",
        )
        self.key = key
        self.expected = expected
        self.actual = actual
