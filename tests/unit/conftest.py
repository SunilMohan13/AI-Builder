from __future__ import annotations

from pathlib import Path

import pytest
from aeropulse_contracts import RegionSnapshot
from region_cycle import run_cycle


@pytest.fixture(scope="module")
def cycled(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, RegionSnapshot]:
    root = tmp_path_factory.mktemp("cycled")
    return root, run_cycle(root)
