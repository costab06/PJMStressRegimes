"""Deterministic semantic claim verification tests."""
from gridregime.grid_semantic_verifier import verified_comparisons, verify_model_claims


def forecast_result():
    return {
        "question": "forecast_accuracy",
        "overall": {
            "high_mean_absolute_pct": 3.3846, "other_mean_absolute_pct": 4.2445,
            "high_mean_absolute_mwh": 5091.413, "other_mean_absolute_mwh": 4485.795,
        },
        "hour_matched": {"eligible_hours": 12, "mean_difference_pct_points": 0.6035},
    }


def test_direction_reversal_is_deterministically_recorded():
    truth = verified_comparisons(forecast_result())
    assert truth["overall_percentage_error"]["direction"] == "lower"
    assert truth["overall_absolute_error"]["direction"] == "higher"
    assert truth["within_hour_percentage_error"]["direction"] == "higher"


def test_wrong_mwh_direction_rejected():
    truth = verified_comparisons(forecast_result())
    claims = {"overall_percentage_error": "lower",
              "overall_absolute_error": "lower",
              "within_hour_percentage_error": "higher"}
    check = verify_model_claims(claims, truth)
    assert check["status"] == "rejected"
    assert "overall_absolute_error" in check["errors"][0]


def test_correct_claims_verified():
    truth = verified_comparisons(forecast_result())
    claims = {key: value["direction"] for key, value in truth.items()}
    assert verify_model_claims(claims, truth)["status"] == "verified"


def test_missing_claims_fail_closed():
    truth = verified_comparisons(forecast_result())
    assert verify_model_claims(None, truth)["status"] == "unverified"
    assert verify_model_claims({}, truth)["status"] == "rejected"


def test_unavailable_matched_comparison():
    result = forecast_result()
    result["hour_matched"] = {"eligible_hours": 0, "mean_difference_pct_points": None}
    assert verified_comparisons(result)["within_hour_percentage_error"]["direction"] == "unavailable"
