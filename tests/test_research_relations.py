import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from test_knowledge_graph import kg, j
import test_research_journal as fixture

spec = importlib.util.spec_from_file_location("register_relation", Path(kg.__file__).with_name("register_research_relation.py"))
registrar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registrar)


class ResearchRelationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        j.init(self.root, allow_synthetic=True)

    def tearDown(self):
        self.tmp.cleanup()

    def ingest(self, rid, suffix, tag):
        run = fixture.run_spec(rid)
        url = "https://chatgpt.com/c/" + suffix
        run["targets"][0]["conversation_url"] = url
        j.ingest(self.root, {"run": run, "events": [fixture.event(conversation_url=url, topic_labels=[tag])], "final_state": "COMPLETE"})
        return url

    def pair(self, same_tag=True):
        a = self.ingest("a", "synthetic-a", "Shared tag")
        b = self.ingest("b", "synthetic-b", "Shared tag" if same_tag else "Other tag")
        return a, b

    def registry(self):
        a, b = self.pair(False)
        graph, _ = kg.derive(kg.snapshot(self.root))
        runs = {n["label"]: n["properties"] for n in graph["nodes"] if n["type"] == "Run"}
        support = [kg.relation_engine().support_record(n, runs) for n in graph["nodes"] if n["type"] == "Observation"]
        return {"schema_version": "1.0.0", "assertions": [{"id": "H-test", "source_url": a, "target_url": b,
                "tier": "H", "relation": "CANDIDATE_COMPARISON", "label": "Pending comparison", "evidence": "Synthetic metadata",
                "validation_needed": "Full text and counterexamples", "validation_status": "PENDING_VALIDATION", "support": support,
                "source_documents": [{"path": "synthetic-only", "sha256": "a" * 64}]}]}

    def test_shared_task_and_equal_titles_do_not_create_content_links(self):
        self.pair(False)
        _, view = kg.derive(kg.snapshot(self.root))
        self.assertEqual(view["research"]["edges"], [])

    def test_exact_tag_link_has_evidence_for_both_distinct_urls(self):
        self.pair()
        graph, view = kg.derive(kg.snapshot(self.root))
        e, = view["research"]["edges"]
        self.assertEqual(e["properties"]["tier"], "E0")
        self.assertEqual(len({s["conversation_url"] for s in e["properties"]["support"]}), 2)
        self.assertTrue(all(s["signature"] and s["result_event_id"] for s in e["properties"]["support"]))
        self.assertIn(e, graph["edges"])

    def test_hypothesis_keeps_its_tier_when_more_observations_arrive(self):
        registry = self.registry()
        before = kg.derive(kg.snapshot(self.root), registry)[1]["research"]["edges"]
        self.ingest("later", "synthetic-a", "New tag")
        after = kg.derive(kg.snapshot(self.root), registry)[1]["research"]["edges"]
        self.assertEqual(before, after)
        self.assertEqual(after[0]["properties"]["validation_status"], "PENDING_VALIDATION")

    def test_source_correction_quarantines_old_hypothesis_without_erasing_it(self):
        registry = self.registry()
        with j.connect(self.root, readonly=True) as db:
            old = db.execute("SELECT event_id FROM events WHERE run_id='a'").fetchone()[0]
        j.record_event(self.root, "a", fixture.event(stage="CORRECTION", supersedes_event_id=old,
                       topic_labels=["Corrected"], proposed_title="Corrected title", displayed_title="Corrected title"))
        graph, view = kg.derive(kg.snapshot(self.root), registry)
        self.assertEqual(view["research"]["edges"], [])
        e, = view["research"]["stale_relations"]
        self.assertIn("SOURCE_CORRECTED", e["properties"]["stale_reasons"])
        self.assertEqual(e["properties"]["tier"], "H")
        self.assertNotIn(e, graph["edges"])
        self.assertEqual(view["relationship_records"], [e])

    def test_tier_promotion_and_one_sided_support_are_rejected(self):
        registry = self.registry()
        registry["assertions"][0]["validation_status"] = "VERIFIED"
        with self.assertRaisesRegex(ValueError, "cannot upgrade"):
            kg.derive(kg.snapshot(self.root), registry)
        registry["assertions"][0]["validation_status"] = "PENDING_VALIDATION"
        registry["assertions"][0]["support"] = registry["assertions"][0]["support"][:1]
        with self.assertRaisesRegex(ValueError, "Both endpoints"):
            kg.derive(kg.snapshot(self.root), registry)

    def test_daily_delta_is_idempotent_and_new_url_adds_real_edges(self):
        self.pair()
        (self.root / "knowledge_graph").mkdir()
        (self.root / "knowledge_graph/config.json").write_text('{"enabled":true}')
        first = j.export(self.root)["knowledge_graph"]
        path = self.root / "knowledge_graph/updates.jsonl"
        original = path.read_bytes()
        self.assertEqual(first, j.export(self.root)["knowledge_graph"])
        self.assertEqual(original, path.read_bytes())
        edges = json.loads((self.root / "knowledge_graph/research_relationships.json").read_text())
        self.ingest("c", "synthetic-c", "Shared tag")
        second = j.export(self.root)["knowledge_graph"]
        delta = json.loads(path.read_text().splitlines()[-1])
        self.assertEqual(len(path.read_text().splitlines()), 2)
        self.assertEqual(len(delta["added"]), 2)
        self.assertEqual(second["research_relation_counts"], {"E0": 3})
        after = json.loads((self.root / "knowledge_graph/research_relationships.json").read_text())
        self.assertTrue({e["id"] for e in edges} <= {e["id"] for e in after})

    def test_invalid_registry_does_not_replace_published_graph(self):
        registry = self.registry()
        kg.build(self.root)
        path = self.root / "knowledge_graph/graph.json"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        registry["assertions"][0]["support"] = []
        (path.parent / "relationship_registry.json").write_text(json.dumps(registry))
        with self.assertRaises(ValueError):
            kg.build(self.root)
        self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())

    def registration_input(self):
        registry = self.registry()
        a = registry["assertions"][0]
        spec = {k: a[k] for k in ("id", "source_url", "target_url", "tier", "relation", "label", "evidence", "validation_needed")}
        spec.update(source_ref="synthetic test only", support_observation_ids=[s["observation_id"] for s in a["support"]])
        return spec

    def test_registration_is_immutable_and_retry_is_semantically_idempotent(self):
        value = self.registration_input()
        path = self.root / "input.json"
        path.write_text(json.dumps(value))
        self.assertEqual(registrar.register(self.root, path)["status"], "REGISTERED")
        path.write_text(json.dumps(value, indent=2))
        self.assertEqual(registrar.register(self.root, path)["status"], "ALREADY_REGISTERED")
        value["evidence"] = "different evidence"
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "immutable"):
            registrar.register(self.root, path)
        self.assertEqual(len(list((self.root / "knowledge_graph/relationship_inputs").glob("*.json"))), 1)

    def test_explicit_supersession_preserves_old_assertion_and_cannot_promote_h(self):
        value = self.registration_input()
        path = self.root / "input.json"
        path.write_text(json.dumps(value))
        registrar.register(self.root, path)
        value.update(id="H-new", supersedes=value["id"], evidence="revised synthetic hypothesis")
        path.write_text(json.dumps(value))
        registrar.register(self.root, path)
        kg.build(self.root)
        rows = json.loads((self.root / "knowledge_graph/research_relationships.json").read_text())
        self.assertEqual(sum(e["properties"]["active"] for e in rows), 1)
        old, = [e for e in rows if not e["properties"]["active"]]
        self.assertIn("SUPERSEDED_ASSERTION", old["properties"]["stale_reasons"])
        value.update(id="E-new", tier="E1", relation="METADATA_SUBJECT_OVERLAP", supersedes="H-new")
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "superseded"):
            registrar.register(self.root, path)

    def test_body_fields_and_unsupported_relation_types_are_rejected(self):
        value = self.registration_input()
        path = self.root / "input.json"
        value["body"] = "not allowed"
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "metadata fields"):
            registrar.register(self.root, path)
        del value["body"]
        value.update(tier="E1", relation="CAUSES")
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "metadata overlap"):
            registrar.register(self.root, path)

    def test_recovered_noop_and_duplicate_results_cannot_promote_h_or_rewrite_support(self):
        from test_recovery_protocol import receipt
        value = self.registration_input()
        path = self.root / "input.json"; path.write_text(json.dumps(value))
        registrar.register(self.root, path)
        (self.root / "knowledge_graph/config.json").write_text('{"enabled":true}')
        j.export(self.root)
        original = json.loads((self.root / "knowledge_graph/research_relationships.json").read_text())
        url = value["source_url"]; title = fixture.event()["displayed_title"]
        run = fixture.run_spec("recovered-noop", title=title)
        run["targets"][0]["conversation_url"] = url
        run.update(skill_version="1.5.0", recovery_protocol=j.RECOVERY, browser_binding="Chrome/TestProfile/synthetic-extension")
        j.start_run(self.root, run)
        o = receipt(run_id=run["run_id"], title=title, target_url=url, address_url=url, document_url=url)
        e = fixture.event("ALREADY CORRECT", conversation_url=url, decision="keep", save_attempted=False,
                          observed_at=o["observed_at"], observation=o,
                          verification={**{k:True for k in j.CHECKS}, "identity_source":"native-ax"})
        j.record_event(self.root, run["run_id"], e); j.finish_run(self.root, run["run_id"], "COMPLETE")
        self.assertEqual(j.resume_run(self.root, run["run_id"])["targets"][0]["action"], "SKIP_VERIFIED")
        self.assertFalse(j.record_event(self.root, run["run_id"], e)["inserted"])
        first = j.export(self.root)["knowledge_graph"]
        updates = (self.root / "knowledge_graph/updates.jsonl").read_bytes()
        self.assertEqual(first, j.export(self.root)["knowledge_graph"])
        self.assertEqual(updates, (self.root / "knowledge_graph/updates.jsonl").read_bytes())
        after = json.loads((self.root / "knowledge_graph/research_relationships.json").read_text())
        self.assertEqual(original, after)
        self.assertEqual(after[0]["properties"]["tier"], "H")
        self.assertEqual(after[0]["properties"]["validation_status"], "PENDING_VALIDATION")


if __name__ == "__main__":
    unittest.main()
