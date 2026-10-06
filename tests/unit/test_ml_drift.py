"""Distribution-drift metric tests (LLD §46)."""

from aeropulse_ml.drift import distribution_drift


def test_identical_distributions_are_stable() -> None:
    values = [float(value) for value in range(100)]

    result = distribution_drift(values, values)

    assert result["status"] == "STABLE"
    assert result["psi"] == 0.0
    assert result["ks_statistic"] == 0.0


def test_shifted_distributions_trigger_drift() -> None:
    reference = [float(value) for value in range(100)]
    current = [float(value + 100) for value in range(100)]

    result = distribution_drift(reference, current)

    assert result["status"] == "DRIFT"
    assert result["psi"] >= 0.25
    assert result["ks_statistic"] > result["ks_critical_value"]


def test_small_windows_report_insufficient_data() -> None:
    result = distribution_drift([1.0, 2.0], [2.0, 3.0], min_samples=3)

    assert result == {
        "reference_n": 2,
        "current_n": 2,
        "minimum_samples": 3,
        "status": "INSUFFICIENT_DATA",
        "psi": None,
        "ks_statistic": None,
        "ks_critical_value": None,
    }


def test_constant_reference_is_supported() -> None:
    result = distribution_drift([5.0] * 40, [5.0] * 40)

    assert result["status"] == "STABLE"
    assert result["psi"] == 0.0
