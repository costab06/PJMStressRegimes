"""Local-LLM interpretation of deterministic grid evidence using OAF's LLM client.

Run: python -m gridregime.grid_interpretation_agent --model qwen3:8b
Requires a running OpenAI-compatible local endpoint (Ollama default: localhost:11434).
No live EIA fetch, Redis worker, or operational risk prediction is involved.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

from gridregime.demo import OUTPUT, load
from gridregime.grid_intelligence import build_evidence

SYSTEM = """You are a cautious electrical-grid research analyst. Interpret ONLY the supplied
deterministic observations. Return a JSON object with exactly a 'findings' array and
a 'summary' string. Each finding must have: 'title', 'interpretation',
'evidence_ids' (array of E1..E5), 'alternative_explanations' (array of strings),
'additional_evidence_needed' (array of strings). Provide 2-3 useful findings.
Interpretations are hypotheses, not established causes. Never claim an outage,
emergency, prediction, reliability risk, or causal mechanism was demonstrated.
Do not invent measurements, percentages, dates, weather, generation, or citations.
Avoid quoting numerical values unless necessary; the report displays verified evidence separately.
Every finding must cite relevant evidence IDs. State uncertainty explicitly."""


def validate_interpretation(response: str, evidence: dict) -> dict:
    """Reject malformed and uncited narratives; numeric claims require human review."""
    obj = json.loads(response)
    if not isinstance(obj, dict) or set(obj) != {"findings", "summary"}:
        raise ValueError("Unexpected model response schema")
    findings = obj["findings"]
    if not isinstance(findings, list) or not 1 <= len(findings) <= 3:
        raise ValueError("Expected 1-3 findings")
    allowed = {o["id"] for o in evidence["observations"]}
    forbidden = ("proved", "proves", "caused", "causes", "predicts", "predicted",
                 "confirmed outage", "confirmed emergency", "guarantees")
    def check_text(s: object) -> str:
        if not isinstance(s, str) or not s.strip() or len(s) > 1500:
            raise ValueError("Invalid interpretation text")
        if any(term in s.lower() for term in forbidden):
            raise ValueError("Unsupported certainty or causal claim")
        return s.strip()
    check_text(obj["summary"])
    for f in findings:
        if not isinstance(f, dict) or set(f) != {
            "title", "interpretation", "evidence_ids",
            "alternative_explanations", "additional_evidence_needed"
        }:
            raise ValueError("Invalid finding schema")
        check_text(f["title"])
        check_text(f["interpretation"])
        ids = f["evidence_ids"]
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in allowed for i in ids):
            raise ValueError("Finding contains missing or unknown evidence IDs")
        for key in ("alternative_explanations", "additional_evidence_needed"):
            if not isinstance(f[key], list) or not f[key]:
                raise ValueError(f"Missing {key}")
            for item in f[key]:
                check_text(item)
    return obj


def render_report(evidence: dict, interpretation: dict, model: str) -> str:
    lookup = {o["id"]: o for o in evidence["observations"]}
    lines = ["# PJM historical grid interpretation", "",
             f"Local model: `{model}`", "",
             "**Scope:** Historical descriptive interpretation, not emergency prediction or causal proof.", "",
             "## Evidence-backed findings", ""]
    for f in interpretation["findings"]:
        lines.extend([f"### {f['title']}", "", f["interpretation"], "",
                      "**Verified supporting observations:**", ""])
        for eid in f["evidence_ids"]:
            o = lookup[eid]
            details = ", ".join(f"{k}={v}" for k, v in o.items() if k not in ("id", "finding", "definition"))
            lines.append(f"- **{eid} — {o['finding']}**: {details}. {o['definition']}")
        lines.extend(["", "**Possible alternative explanations:** " + "; ".join(f["alternative_explanations"]),
                      "", "**Evidence needed:** " + "; ".join(f["additional_evidence_needed"]), ""])
    lines.extend(["## Interpretation summary", "", interpretation["summary"], "",
                  "## Method and limitations", "",
                  "Deterministic calculations are stored in `grid_evidence.json`. "
                  "Model-generated explanations are hypotheses, not independently verified findings.", ""])
    lines.extend(f"- {item}" for item in evidence["limitations"])
    return "\n".join(lines) + "\n"


async def interpret(evidence: dict, model: str, base_url: str) -> dict:
    from shared.llm.client import LLMClient, LLMConfig
    client = LLMClient(LLMConfig(model=model, base_url=base_url, temperature=0))
    raw = await client.complete([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(evidence, allow_nan=False)},
    ])
    # Retain the raw model response for inspection even when validation fails.
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "grid_interpretation_raw.txt").write_text(raw, encoding="utf-8")
    return validate_interpretation(raw, evidence)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    args = parser.parse_args()
    evidence = build_evidence(load())
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "grid_evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    interpretation = await interpret(evidence, args.model, args.base_url)
    (OUTPUT / "grid_interpretation.json").write_text(json.dumps(interpretation, indent=2) + "\n")
    target = OUTPUT / "grid_interpretation.md"
    target.write_text(render_report(evidence, interpretation, args.model), encoding="utf-8")
    print(target.read_text())
    print(f"Saved {target}")


if __name__ == "__main__":
    asyncio.run(main())
