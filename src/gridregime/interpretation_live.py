"""Run a local Ollama interpretation experiment against deterministic PJM evidence.

Usage:
    python -m gridregime.interpretation_live --output-dir results/interpretation-live

The model's claims are audited, never automatically approved for publication.
No network service other than local Ollama is required.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

from gridregime.interpretation_verification import audit_interpretation

DEMO_EVIDENCE = [
    {"id": "E_PCT_HIGH", "metric": "mae_percent", "value": 3.3846,
     "unit": "percent", "population": "high_demand"},
    {"id": "E_PCT_OTHER", "metric": "mae_percent", "value": 4.2445,
     "unit": "percent", "population": "other_hours"},
    {"id": "E_ABS_HIGH", "metric": "mae_absolute", "value": 5091.413,
     "unit": "MWh", "population": "high_demand"},
    {"id": "E_ABS_OTHER", "metric": "mae_absolute", "value": 4485.795,
     "unit": "MWh", "population": "other_hours"},
    {"id": "E_BIAS_HIGH", "metric": "signed_bias_percent", "value": -0.9647,
     "unit": "percent", "population": "high_demand"},
    {"id": "E_BIAS_OTHER", "metric": "signed_bias_percent", "value": 2.1339,
     "unit": "percent", "population": "other_hours"},
    {"id": "E_CORRELATION", "metric": "pearson_r", "value": -0.1338,
     "unit": "ratio", "population": "all_hours"},
]

SYSTEM_PROMPT = """You are interpreting deterministic historical PJM grid measurements.
Return ONLY a JSON object with a 'claims' array. Each claim must have:
id (unique string), type (observed_fact, interpretation, or prediction),
text, evidence_ids (list), evidence_roles (map from evidence ID to
establishes_fact, supports_inference, or context_only), and assertion.
The assertion is either:
{"kind":"comparison","left":"E_ID","right":"E_ID","operator":"gt|lt|eq"}
or {"kind":"value","evidence_id":"E_ID","metric":"metric_name",
"unit":"unit","value":number}.
Use exact evidence metric/unit labels. Do not invent evidence or tests.
Positive signed_bias_percent means actual exceeded forecast; negative means
actual was below forecast. Do not infer statistical significance from r alone.
Only compare matching metrics and units. Include the difference between
absolute and percentage forecast error. Be explicit about uncertainty.
A numeric check cannot validate causal interpretations or significance.
"""


def parse_model_output(raw: str) -> dict:
    """Parse Ollama JSON output without trying to repair invented content."""
    obj = json.loads(raw)
    if not isinstance(obj, dict) or not isinstance(obj.get("claims"), list):
        raise ValueError("model_output_requires_claims_array")
    ids = []
    for claim in obj["claims"]:
        if not isinstance(claim, dict) or not isinstance(claim.get("id"), str):
            raise ValueError("model_claim_requires_string_id")
        ids.append(claim["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_model_claim_id")
    return obj


def query_ollama(evidence: list[dict], *, model: str = "qwen3:8b",
                 url: str = "http://127.0.0.1:11434/api/chat",
                 timeout: float = 180.0) -> str:
    prompt = ("Interpret these evidence records. Produce 5-8 claims, "
              "including percentage and absolute error comparisons, signed "
              "forecast bias, and the correlation's limits.\n"
              + json.dumps(evidence, indent=2))
    payload = json.dumps({
        "model": model, "stream": False, "format": "json",
        "options": {"temperature": 0},
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": prompt}],
    }).encode("utf-8")
    request = Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        envelope = json.load(response)
    return envelope["message"]["content"]


def run_experiment(output_dir: Path, *, model: str = "qwen3:8b",
                   raw_response: str | None = None,
                   evidence: list[dict] | None = None) -> dict:
    """Persist raw response and audit; never publish unreviewed prose."""
    output_dir.mkdir(parents=True, exist_ok=True)
    records = evidence if evidence is not None else DEMO_EVIDENCE
    raw = raw_response if raw_response is not None else query_ollama(records, model=model)
    (output_dir / "llm_raw.txt").write_text(raw, encoding="utf-8")
    parsed = parse_model_output(raw)
    document = {"evidence": records, "claims": parsed["claims"]}
    audit = audit_interpretation(document)
    (output_dir / "claim_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts = {s: sum(a["status"] == s for a in audit["audits"])
              for s in ("rejected", "review_required")}
    report = {
        "model": model, "claims": len(audit["audits"]),
        "counts": counts, "published": len(audit["publication"]),
        "warning": "Numerical consistency does not establish prose entailment. "
                   "All non-rejected claims still require independent review.",
    }
    (output_dir / "summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("results/interpretation-live"))
    parser.add_argument("--model", default="qwen3:8b")
    args = parser.parse_args()
    print(json.dumps(run_experiment(args.output_dir, model=args.model), indent=2))


if __name__ == "__main__":
    main()
