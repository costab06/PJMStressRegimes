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
from gridregime.grid_investigation import QUESTIONS, investigate
from gridregime.grid_semantic_verifier import verified_comparisons, verify_model_claims, render_verified_comparisons

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


HYPOTHESIS_SYSTEM = """You are choosing one useful follow-up investigation of historical grid
measurements. Return JSON with exactly two fields: 'question' and 'reason'.
'question' must be either 'forecast_accuracy' or 'ramp_interchange'.
Choose based only on the evidence. Do not make causal or emergency claims.
The investigation is performed by deterministic code, not by you."""

FOLLOWUP_SYSTEM = """You are an evidence-constrained grid analyst. You have the original
observations, a hypothesis selected earlier, and new deterministic investigation results.
Return JSON with exactly 'assessment', 'supporting_evidence', 'remaining_uncertainty',
and 'next_data_needed' (strings or null; use null when evidence is insufficient). Discuss whether the initial hypothesis
survives the follow-up; distinguish overall from within-hour comparisons and percentage
from absolute MWh error. No causal, emergency, or predictive conclusions. Do not invent
numbers or facts. State if matching is unavailable or inconclusive.\nAlso include 'comparisons' as a JSON object mapping each key from 'comparison_keys'\nin the user input to its correct 'higher', 'lower', 'equal', 'unavailable', or\n'descriptive' direction. Do not invent comparison keys."""


def validate_hypothesis(raw: str) -> dict:
    obj = json.loads(raw)
    if not isinstance(obj, dict) or set(obj) != {"question", "reason"}:
        raise ValueError("Invalid hypothesis selection")
    if obj["question"] not in QUESTIONS or not isinstance(obj["reason"], str) or not obj["reason"].strip():
        raise ValueError("Unsupported or unexplained hypothesis")
    return obj


def validate_followup(raw: str) -> dict:
    """Normalize structured evidence for display without asserting its truth."""
    obj = json.loads(raw)
    fields = {"assessment", "supporting_evidence", "remaining_uncertainty", "next_data_needed"}
    if not isinstance(obj, dict) or not fields.issubset(obj) or set(obj) - fields - {"comparisons"}:
        raise ValueError("Invalid follow-up schema")\n    comparisons = obj.pop("comparisons", None)
    incomplete = False
    structured = []
    for key in fields:
        value = obj[key]
        if value is None or (isinstance(value, str) and not value.strip()):
            obj[key] = "Not provided by local model; requires review."
            incomplete = True
        elif isinstance(value, str):
            continue
        elif key != "assessment" and isinstance(value, list):
            # Common Ollama response shape: a list of evidence statements.
            # Preserve all details as model-generated, not verified evidence.
            if not value:
                obj[key] = "Not provided by local model; requires review."
                incomplete = True
            elif all(isinstance(item, str) and item.strip() for item in value):
                obj[key] = "; ".join(value)
                structured.append(key)
            elif all(isinstance(item, dict) for item in value):
                obj[key] = json.dumps(value, ensure_ascii=False)
                structured.append(key)
            else:
                raise ValueError(f"Invalid follow-up field type: {key}")
        elif key != "assessment" and isinstance(value, dict):
            obj[key] = json.dumps(value, ensure_ascii=False)
            structured.append(key)
        else:
            raise ValueError(f"Invalid follow-up field type: {key}")
    obj["comparisons"] = comparisons\n    obj["incomplete"] = incomplete
    obj["structured_fields"] = sorted(structured)
    return obj

async def investigate_with_model(frame, evidence: dict, model: str, base_url: str) -> tuple[dict, dict, dict]:
    """Model selects a bounded tool; deterministic code investigates; model reassesses."""
    from shared.llm.client import LLMClient, LLMConfig
    client = LLMClient(LLMConfig(model=model, base_url=base_url, temperature=0))
    raw_choice = await client.complete([
        {"role": "system", "content": HYPOTHESIS_SYSTEM},
        {"role": "user", "content": json.dumps({"questions": QUESTIONS, "evidence": evidence}, allow_nan=False)},
    ])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "grid_hypothesis_raw.txt").write_text(raw_choice, encoding="utf-8")
    hypothesis = validate_hypothesis(raw_choice)
    result = investigate(frame, hypothesis["question"])
    truth = verified_comparisons(result)\n    raw_followup = await client.complete([
        {"role": "system", "content": FOLLOWUP_SYSTEM},
        {"role": "user", "content": json.dumps({
            "original_evidence": evidence, "hypothesis": hypothesis, "investigation": result,\n            "comparison_keys": list(truth)
        }, allow_nan=False)},
    ])
    (OUTPUT / "grid_followup_raw.txt").write_text(raw_followup, encoding="utf-8")
    followup = validate_followup(raw_followup)\n    followup["verification"] = verify_model_claims(followup["comparisons"], truth)\n    return hypothesis, result, followup


def render_investigation(hypothesis: dict, result: dict, followup: dict) -> str:
    lines = ["", "## Hypothesis and follow-up investigation", "",
             "**Question selected by local model:** " + QUESTIONS[hypothesis["question"]], "",
             "**Why investigate:** " + hypothesis["reason"], "",
             "**Deterministic method:** " + result["method"], "",
             "**Computed follow-up evidence:**", "", "```json",
             json.dumps(result, indent=2), "```", "",
             "**Reassessment:** " + followup["assessment"], "",
             "**Evidence interpretation:** " + followup["supporting_evidence"], "",
             "**Remaining uncertainty (model-generated):** " + followup["remaining_uncertainty"], "",
             "**Additional data needed:** " + followup["next_data_needed"], "",
             "The follow-up text is model-generated and requires human review; "
             "the numerical investigation is deterministic.", ""])
    if followup.get("structured_fields"):
        lines.extend(["", "**Review required:** Structured model output was formatted for display, not independently verified.", ""])
    if followup.get("incomplete"):
        lines.extend(["", "**Review required:** The local model left one or more follow-up fields unanswered.", ""])
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    args = parser.parse_args()
    frame = load()
    evidence = build_evidence(frame)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "grid_evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    interpretation = await interpret(evidence, args.model, args.base_url)
    (OUTPUT / "grid_interpretation.json").write_text(json.dumps(interpretation, indent=2) + "\n")
    target = OUTPUT / "grid_interpretation.md"
    hypothesis, investigation, followup = await investigate_with_model(frame, evidence, args.model, args.base_url)
    (OUTPUT / "grid_investigation.json").write_text(json.dumps({
        "hypothesis": hypothesis, "investigation": investigation, "followup": followup
    }, indent=2) + "\n", encoding="utf-8")
    target.write_text(render_report(evidence, interpretation, args.model)
                      + render_investigation(hypothesis, investigation, followup), encoding="utf-8")
    print(target.read_text())
    print(f"Saved {target}")


if __name__ == "__main__":
    asyncio.run(main())
