"""Held-out PJM research-spec interpretation benchmark.

Source: research_spec.yaml (2026-10-01 frozen specification), and
paper/manuscript.md section 2. This is a NEW domain relative to the
MAE/correlation development benchmark, but labels are author-constructed
from the same repository sources; it is not independent external validation.
No unseen event measurements or model results are invented.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gridregime.interpretation_benchmark import evaluate

SOURCE = "research_spec.yaml"
EVIDENCE = [
    {"id":"H_S3","metric":"catalog_episode_count","population":"S3_emergency",
     "unit":"episodes","value":2,"source":SOURCE,
     "description":"As of 2026-10-01, current_S3=2; catalog not at modeling gate."},
    {"id":"H_S2","metric":"catalog_episode_count","population":"S2_stressed_managed",
     "unit":"episodes","value":8,"source":SOURCE,
     "description":"As of 2026-10-01, current_S2=8."},
    {"id":"H_S1","metric":"catalog_episode_count","population":"S1_quantitative_extreme",
     "unit":"episodes","value":1,"source":SOURCE,
     "description":"As of 2026-10-01, current_S1=1."},
    {"id":"H_TOTAL","metric":"catalog_episode_count","population":"all_cataloged",
     "unit":"episodes","value":11,"source":SOURCE,
     "description":"As of 2026-10-01, 11 cataloged episodes."},
    {"id":"H_PENDING","metric":"pending_catalog_review","population":"archive_items",
     "unit":"items","value":2,"source":SOURCE,
     "description":"Two candidate items await direct archive review; may add 0–2 episodes."},
    {"id":"H_GATE","metric":"minimum_total_model_gate","population":"all_cataloged",
     "unit":"episodes","value":20,"source":SOURCE,
     "description":"Total-min modeling gate 20, S3-min 6, S2-min 10; gate is a design choice, not a success criterion."},
    {"id":"H_FEATURES","metric":"frozen_feature_count","population":"v1_state_vector",
     "unit":"features","value":4,"source":SOURCE,
     "description":"Frozen v1 features: LoadZ, ForecastErrorZ, RampZ, InterchangeZ; baseline 2021 PJM hourly conditioned on hour and month."},
    {"id":"H_DERIVED","metric":"derived_velocity_lags_count","population":"v1_derivatives",
     "unit":"lags","value":5,"source":SOURCE,
     "description":"Velocity X_t - X_(t-k), k in {1,3,6,12,24}; derivatives are not new frozen features."},
    {"id":"H_PRIMARY","metric":"primary_target_defined","population":"S2_vs_S3",
     "unit":"boolean_indicator","value":1,"source":SOURCE,
     "description":"Primary discrimination target is S2 stressed-managed versus S3 emergency; not an achieved classifier result."},
    {"id":"H_DEFERRED","metric":"model_evaluation_deferred","population":"research_plan",
     "unit":"boolean_indicator","value":1,"source":SOURCE,
     "description":"HMM evaluation deferred pending sufficient independent episodes; leave-one-episode-out planned; no reported model accuracy."},
    {"id":"H_EXPLORATORY","metric":"exploratory_hypothesis_only","population":"five_episode_exploration",
     "unit":"boolean_indicator","value":1,"source":SOURCE,
     "description":"Exploratory five-episode observation motivates joint-configuration and trajectory hypothesis; explicitly not a result."},
    {"id":"H_WEATHER","metric":"weather_extension_pending","population":"predefined_extension",
     "unit":"boolean_indicator","value":1,"source":SOURCE,
     "description":"WeatherZ predefined extension pending NOAA data; not a frozen v1 state-vector member."},
    {"id":"H_NEIGHBOR","metric":"neighbor_extension_pending","population":"predefined_extension",
     "unit":"boolean_indicator","value":1,"source":SOURCE,
     "description":"NeighborStressZ predefined extension pending data; not a frozen v1 state-vector member."},
    {"id":"H_EPISODE","metric":"episode_independence_rule","population":"unit_of_observation",
     "unit":"boolean_indicator","value":1,"source":SOURCE,
     "description":"Episode is the independent observation; multiple Elliott actions in same weather episode cannot be treated as independent train/test samples."},
    {"id":"H_MANUSCRIPT","metric":"manuscript_exploration","population":"section_2",
     "unit":"boolean_indicator","value":1,"source":"paper/manuscript.md",
     "description":"Section 2 describes exploratory heterogeneous forecast-error precursors in Elliott 2022 versus July 2026; motivates multivariate hypothesis, not predictive proof."},
]

# Source-level provenance is attached to each cited fact, not to the prompt.
# The research specification is dated 2026-10-01; the manuscript section
# has no asserted publication date in this fixture.
for _fact in EVIDENCE:
    if _fact["source"] == SOURCE:
        _fact["provenance"] = {
            "document": SOURCE,
            "section": ("model_plan.modeling_gate" if _fact["id"] in
                        {"H_S3", "H_S2", "H_S1", "H_TOTAL", "H_PENDING", "H_GATE"}
                        else "feature_freeze" if _fact["id"] in
                        {"H_FEATURES", "H_DERIVED", "H_WEATHER", "H_NEIGHBOR"}
                        else "unit_of_observation" if _fact["id"] == "H_EPISODE"
                        else "discrimination_targets" if _fact["id"] == "H_PRIMARY"
                        else "model_plan" if _fact["id"] == "H_DEFERRED"
                        else "hypothesis"),
            "source_date": "2026-10-01",
            "evidence_status": ("exploratory_finding" if _fact["id"] == "H_EXPLORATORY"
                                else "planned" if _fact["id"] in
                                {"H_DEFERRED", "H_WEATHER", "H_NEIGHBOR"}
                                else "methodological_definition" if _fact["id"] in
                                {"H_FEATURES", "H_DERIVED", "H_PRIMARY", "H_EPISODE", "H_GATE"}
                                else "observation"),
        }
    else:
        _fact["provenance"] = {
            "document": "paper/manuscript.md",
            "section": "2. Exploratory Observations",
            "evidence_status": "exploratory_finding",
        }



def _claim(cid, expected, category, text, eid):
    e = next(x for x in EVIDENCE if x["id"] == eid)
    return {"id":cid,"expected":expected,"category":category,
            "claim":{"id":cid,"type":"interpretation","text":text,
                     "evidence_ids":[eid],
                     "evidence_roles":{eid:"establishes_fact"},
                     "assertion":{"kind":"value","evidence_id":eid,
                                  "metric":e["metric"],"unit":e["unit"],
                                  "value":e["value"]}}}


def holdout_cases():
    rows = [
        ("supported","catalog","The research specification records two S3 emergency episodes as of October 1, 2026.","H_S3"),
        ("supported","catalog","The research specification records eight S2 stressed-managed episodes as of October 1, 2026.","H_S2"),
        ("supported","catalog","The research specification records eleven cataloged episodes as of October 1, 2026.","H_TOTAL"),
        ("supported","catalog","Two candidate archive items remained pending direct review in the October 1 specification.","H_PENDING"),
        ("supported","model_gate","The specified total minimum modeling gate is twenty episodes; it is not a demonstrated model result.","H_GATE"),
        ("supported","feature_freeze","The frozen v1 state vector has four variables: LoadZ, ForecastErrorZ, RampZ and InterchangeZ.","H_FEATURES"),
        ("supported","feature_freeze","The specified velocity derivative uses five lag lengths, and these derivatives are not new frozen features.","H_DERIVED"),
        ("supported","target","The study defines S2 versus S3 as the primary discrimination target, not as an achieved classification result.","H_PRIMARY"),
        ("supported","model_status","The HMM evaluation is deferred; leave-one-episode-out evaluation is planned rather than completed.","H_DEFERRED"),
        ("supported","scope","The manuscript describes heterogeneous forecast-error precursors as exploratory motivation, not proof of predictive performance.","H_MANUSCRIPT"),
        ("unsupported","catalog","The research specification establishes that at least six S3 emergency episodes had already been cataloged.","H_S3"),
        ("unsupported","catalog","The two pending archive items are confirmed S3 emergency episodes.","H_PENDING"),
        ("unsupported","model_gate","The twenty-episode modeling gate proves the HMM achieved statistically reliable predictive performance.","H_GATE"),
        ("unsupported","feature_freeze","The frozen v1 state vector includes WeatherZ as a fifth feature.","H_FEATURES"),
        ("unsupported","feature_freeze","NeighborStressZ was included in the frozen v1 state vector and evaluated in the primary model.","H_NEIGHBOR"),
        ("unsupported","target","The study's primary discrimination target is normal grid operation versus S3 emergencies.","H_PRIMARY"),
        ("unsupported","model_status","The completed HMM evaluation demonstrated reliable S2-to-S3 transition predictions.","H_DEFERRED"),
        ("unsupported","causal_overreach","The five-episode exploratory observations prove that joint trajectories cause grid emergencies.","H_EXPLORATORY"),
        ("unsupported","independence","The Elliott December 23 and December 24 actions are independent episodes and valid separate train/test observations.","H_EPISODE"),
        ("unsupported","generalization","The manuscript establishes that ForecastErrorZ is a universally reliable precursor to all PJM emergencies.","H_MANUSCRIPT"),
    ]
    cases = [_claim(f"P{i:02}", *row) for i,row in enumerate(rows,1)]
    assert len(cases)==20
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semantic-review",action="store_true")
    parser.add_argument("--model",default="qwen3:8b")
    parser.add_argument("--output",type=Path,default=Path("results/pjm-holdout.json"))
    args=parser.parse_args()
    result=evaluate(holdout_cases(),evidence=EVIDENCE,
                    semantic_review=args.semantic_review,model=args.model)
    result["provenance"]={"sources":[SOURCE,"paper/manuscript.md"],
                          "source_spec_date":"2026-10-01",
                          "label_policy":"Author-labeled against repository text; not independent field validation",
                          "measurement_policy":"No unreported time-series measurements or trained-model results"}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result["metrics"],indent=2))


if __name__=="__main__":
    main()
