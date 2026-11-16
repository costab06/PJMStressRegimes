"""Deterministic directional claim verification for GridRegime investigations.

Free-form LLM prose cannot be exhaustively verified. Only explicitly enumerated,
machine-checked comparisons may appear as verified conclusions.
"""
from __future__ import annotations


def verified_comparisons(result: dict) -> dict:
    """Return authoritative directional claims calculated from investigation values."""
    if result["question"] == "forecast_accuracy":
        overall = result["overall"]
        matched = result["hour_matched"]

        def compare(a, b):
            return "higher" if a > b else "lower" if a < b else "equal"

        claims = {
            "overall_percentage_error": {
                "direction": compare(overall["high_mean_absolute_pct"], overall["other_mean_absolute_pct"]),
                "high": overall["high_mean_absolute_pct"], "other": overall["other_mean_absolute_pct"],
                "units": "percent",
            },
            "overall_absolute_error": {
                "direction": compare(overall["high_mean_absolute_mwh"], overall["other_mean_absolute_mwh"]),
                "high": overall["high_mean_absolute_mwh"], "other": overall["other_mean_absolute_mwh"],
                "units": "MWh",
            },
        }
        diff = matched["mean_difference_pct_points"]
        claims["within_hour_percentage_error"] = {
            "direction": "unavailable" if diff is None else compare(diff, 0),
            "difference": diff, "units": "percentage points",
            "eligible_utc_hours": matched["eligible_hours"],
            "method": "unweighted mean of eligible within-UTC-hour differences",
        }
        return claims
    return {
        "ramp_interchange_change_correlation": {
            "pearson_r": result["pearson_r"],
            "paired_hours": result["paired_hours"],
            "interpretation": "descriptive correlation only; significance not tested",
        }
    }


def verify_model_claims(claims: object, truth: dict) -> dict:
    """Fail closed on unsupported, missing, or contradictory structured assertions."""
    if not isinstance(claims, dict):
        return {"status": "unverified", "errors": ["Model supplied no structured comparison claims"]}
    errors = []
    for key, expected in truth.items():
        if key not in claims:
            errors.append(f"Missing comparison: {key}")
            continue
        proposed = claims[key]
        if not isinstance(proposed, str) or proposed != expected.get("direction", "descriptive"):
            errors.append(f"Contradictory or unsupported comparison: {key}")
    for key in claims:
        if key not in truth:
            errors.append(f"Unknown comparison: {key}")
    return {"status": "verified" if not errors else "rejected", "errors": errors}


def render_verified_comparisons(truth: dict) -> str:
    lines = ["", "### Deterministically verified comparisons", ""]
    for name, value in truth.items():
        if "direction" in value:
            lines.append(f"- **{name}**: {value['direction']} for high-demand versus other hours "
                         f"({value['units']}); values: {value.get('high', 'n/a')} vs "
                         f"{value.get('other', 'n/a')}; within-hour difference: "
                         f"{value.get('difference', 'n/a')}")
        else:
            lines.append(f"- **{name}**: r={value['pearson_r']}, "
                         f"paired hours={value['paired_hours']}; significance not tested")
    return "\n".join(lines) + "\n"
