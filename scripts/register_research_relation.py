#!/usr/bin/env python3
"""Append a sourced E1/H metadata assertion; no browser actions or body collection."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


def builder():
    spec = importlib.util.spec_from_file_location("rename_graph_builder", Path(__file__).with_name("knowledge_graph.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def register(root, input_path):
    root, input_path = Path(root).resolve(), Path(input_path).resolve()
    kg = builder()
    engine = kg.relation_engine()
    raw = input_path.read_bytes()
    spec = json.loads(raw)
    required = {"id", "source_url", "target_url", "tier", "relation", "label", "evidence", "validation_needed", "support_observation_ids", "source_ref"}
    if not required <= spec.keys() or spec.keys() - required - {"supersedes"}:
        raise ValueError("Input must contain approved metadata fields only")
    if spec["tier"] not in {"E1", "H"}:
        raise ValueError("Only E1/H can be registered; E0 is computed from recorded tags")
    if any(not isinstance(spec[k], str) or not spec[k].strip() or len(spec[k]) > 600
           for k in required - {"support_observation_ids"}):
        raise ValueError("Empty or oversized metadata field")
    allowed_e1 = {"EXPLICIT_METADATA_OVERLAP", "METADATA_SUBJECT_OVERLAP"}
    if spec["tier"] == "E1" and spec["relation"] not in allowed_e1:
        raise ValueError("E1 only records metadata overlap, never a causal or theoretical claim")
    if spec["tier"] == "H" and not spec["relation"].startswith("CANDIDATE_"):
        raise ValueError("H requires a candidate relationship type")
    graph, _ = kg.derive(kg.snapshot(root))
    obs = {n["id"]: n for n in graph["nodes"] if n["type"] == "Observation"}
    runs = {n["label"]: n["properties"] for n in graph["nodes"] if n["type"] == "Run"}
    ids = spec["support_observation_ids"]
    if not isinstance(ids, list) or not ids or any(i not in obs for i in ids):
        raise ValueError("Support must name existing terminal observations")
    support = [engine.support_record(obs[i], runs) for i in sorted(set(ids))]
    if {s["conversation_url"] for s in support} != {spec["source_url"], spec["target_url"]}:
        raise ValueError("Support must cover exactly the two target URLs")
    output = root / "knowledge_graph"
    path = output / "relationship_registry.json"
    registry = json.loads(path.read_text()) if path.exists() else {"schema_version": "1.0.0", "assertions": [], "domains": [], "conversation_annotations": []}
    spec_hash = hashlib.sha256(raw).hexdigest()
    source_path = output / "relationship_inputs" / (spec_hash + ".json")
    assertion = {k: spec[k] for k in required - {"support_observation_ids", "source_ref"}}
    assertion.update(support=support, source_ref=spec["source_ref"],
                     source_documents=[{"path": str(source_path), "sha256": spec_hash}],
                     validation_status="METADATA_COMPATIBILITY_ONLY" if spec["tier"] == "E1" else "PENDING_VALIDATION")
    if spec.get("supersedes"):
        assertion["supersedes"] = spec["supersedes"]
    old = next((a for a in registry["assertions"] if a["id"] == spec["id"]), None)
    if old:
        if {k: v for k, v in old.items() if k != "source_documents"} == {k: v for k, v in assertion.items() if k != "source_documents"}:
            return {"status": "ALREADY_REGISTERED", "id": spec["id"]}
        raise ValueError("Existing assertion is immutable; use a new id and supersedes")
    prior = None
    if spec.get("supersedes"):
        prior = next((a for a in registry["assertions"] if a["id"] == spec["supersedes"]), None)
        if not prior or prior.get("superseded_by") or prior["tier"] != spec["tier"] or {prior["source_url"], prior["target_url"]} != {spec["source_url"], spec["target_url"]}:
            raise ValueError("Invalid superseded assertion")
    for a in registry["assertions"]:
        if not a.get("superseded_by") and a is not prior and a["tier"] == spec["tier"] and a["relation"] == spec["relation"] and a["label"] == spec["label"] and {a["source_url"], a["target_url"]} == {spec["source_url"], spec["target_url"]}:
            raise ValueError("Duplicate active relationship; reuse or explicitly supersede it")
    original = json.dumps(registry, ensure_ascii=False, indent=2) + "\n"
    if prior:
        prior["superseded_by"] = spec["id"]
    registry["assertions"].append(assertion)
    engine.validate_registry(registry)
    kg.derive(kg.snapshot(root), registry)  # Validate all source signatures and graph endpoints before writes.
    kg.atomic(output / "registry_history" / (engine.sha(json.loads(original)) + ".json"), original)
    kg.atomic(source_path, raw.decode("utf-8"))
    kg.atomic(path, json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
    return {"status": "REGISTERED", "id": spec["id"], "tier": spec["tier"], "export_required": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    print(json.dumps(register(args.root, args.input), ensure_ascii=False))
