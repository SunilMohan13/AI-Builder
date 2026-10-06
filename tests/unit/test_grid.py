"""H3 grid mapping tests."""

from aeropulse_geospatial.grid import DEFAULT_RESOLUTION, in_default_aoi, to_grid_id

# ITO Delhi — documented H3 res-8 cell for contract tests.
ITO_LAT = 28.628
ITO_LON = 77.241


def test_grid_id_stable() -> None:
    first = to_grid_id(ITO_LAT, ITO_LON)
    second = to_grid_id(ITO_LAT, ITO_LON)
    assert first == second
    assert first.startswith("8")


def test_resolution_default_is_8() -> None:
    assert DEFAULT_RESOLUTION == 8
    assert to_grid_id(ITO_LAT, ITO_LON) == to_grid_id(ITO_LAT, ITO_LON, 8)


def test_ncr_in_default_aoi() -> None:
    assert in_default_aoi(ITO_LAT, ITO_LON)
    assert not in_default_aoi(0.0, 0.0)
