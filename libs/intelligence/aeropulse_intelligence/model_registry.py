"""Deprecated shim for the former in-process model registry (LLD §19).

This module used to hold a hardcoded list of three baselines, every one of
them labelled ``PRODUCTION`` unconditionally, and ``GET /api/v1/models`` served
it. That made the endpoint structurally incapable of reporting a real trained
champion, and it was a second registry competing with the filesystem one that
training actually writes to.

The filesystem registry won. The baselines now live in
``aeropulse_ml.baselines`` as genuine :class:`~aeropulse_ml.registry.ModelRecord`
entries, which is why this module cannot simply re-export them: ``libs/ml``
imports ``libs/intelligence`` for the version constants, so importing back the
other way would be circular.

Nothing in the runtime uses this module. It is kept only so that an external
caller pinned to the old import fails with an explanation rather than an
``ImportError``, and it should be deleted once that grace period has passed.
"""

from __future__ import annotations

from typing import NoReturn

_REPLACEMENT = (
    "aeropulse_ml.baselines.baseline_records() for the deterministic baselines, "
    "or aeropulse_ml.registry.ModelRegistry().list_models() for everything"
)


def list_production_models() -> NoReturn:
    """Raise, pointing the caller at the registry that replaced this one.

    Raises:
        NotImplementedError: Always. The hardcoded list it used to return
            reported baselines as PRODUCTION regardless of what was trained,
            so returning anything here would reintroduce that untruth.
    """
    raise NotImplementedError(
        f"aeropulse_intelligence.model_registry was removed; use {_REPLACEMENT}"
    )
