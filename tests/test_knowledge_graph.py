import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import test_research_journal as fixture

j = fixture.j
path = Path(__file__).resolve().parents[1] / "scripts/knowledge_graph.py"
spec = importlib.util.spec_from_file_location("knowledge_graph", path)
kg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kg)


class KnowledgeGraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        j.init(self.root, allow_synthetic=True)

    def tearDown(self):
        self.tmp.cleanup()

    def initial(self, **values):
        j.ingest(self.root, {"run": fixture.run_spec(), "events": [fixture.event(**values)], "final_state": "COMPLETE"})

    def graph(self):
        return kg.derive(kg.snapshot(self.root))[0]

    def test_stable_url_identity_does_not_merge_equal_titles(self):
        self.initial()
        other = fixture.run_spec("second")
        other["targets"][0]["conversation_url"] = "https://chatgpt.com/c/synthetic-b"
        event = fixture.event(conversation_url=other["targets"][0]["conversation_url"])
        j.ingest(self.root, {"run": other, "events": [event], "final_state": "COMPLETE"})
        graph = self.graph()
        self.assertEqual(graph["metadata"]["node_counts"]["Conversation"], 2)
        self.assertEqual(graph["metadata"]["node_counts"]["Observation"], 2)
        self.assertEqual(graph["metadata"]["node_counts"]["Title"], 2)

    def test_pending_annotations_do_not_become_topic_or_observation_assertions(self):
        spec = fixture.run_spec()
        j.start_run(self.root, spec)
        j.record_event(self.root, "fixture-1", fixture.event(stage="PLANNED", status=None,
                       displayed_title=None, save_attempted=None, topic_labels=["unverified-topic"]))
        j.finish_run(self.root, "fixture-1", "INTERRUPTED")
        graph = self.graph()
        self.assertEqual(graph["metadata"]["terminal_observations"], 0)
        self.assertEqual(graph["metadata"]["excluded_pending_targets"], 1)
        self.assertNotIn("Topic", graph["metadata"]["node_counts"])
        self.assertEqual(graph["metadata"]["node_counts"]["Event"], 1)

    def test_source_and_unknown_time_are_not_upgraded(self):
        spec = fixture.run_spec()
        spec["source_type"] = "historical_transcript"
        event = fixture.event(annotation_basis="historical_record", observed_at=None,
                              verification={}, save_attempted=None)
        j.ingest(self.root, {"run": spec, "events": [event], "final_state": "COMPLETE"})
        obs = next(n for n in self.graph()["nodes"] if n["type"] == "Observation")
        self.assertEqual(obs["properties"]["source_type"], "historical_transcript")
        self.assertIsNone(obs["properties"]["observed_at"])
        self.assertIsNone(obs["properties"]["verification"]["document_url_matches"])

    def test_pending_save_events_survive_one_terminal_observation(self):
        j.start_run(self.root, fixture.run_spec())
        j.record_event(self.root, "fixture-1", fixture.event(stage="PLANNED", status=None, displayed_title=None, save_attempted=None))
        j.record_event(self.root, "fixture-1", fixture.event(stage="SAVE_PENDING", status=None, displayed_title=None, verification={}))
        j.record_event(self.root, "fixture-1", fixture.event())
        graph = self.graph()
        self.assertEqual(graph["metadata"]["node_counts"]["Observation"], 1)
        self.assertEqual(graph["metadata"]["node_counts"]["Event"], 3)
        self.assertEqual({n["properties"]["stage"] for n in graph["nodes"] if n["type"] == "Event"}, {"PLANNED", "SAVE_PENDING", "RESULT"})

    def test_determinism_and_incremental_identity(self):
        self.initial()
        source = kg.snapshot(self.root)
        graph1, _ = kg.derive(source)
        shuffled = {k: list(reversed(v)) for k, v in source.items()}
        self.assertEqual(graph1, kg.derive(shuffled)[0])
        later = fixture.run_spec("later", "2025-01-02")
        j.ingest(self.root, {"run": later, "events": [fixture.event()], "final_state": "COMPLETE"})
        graph2 = self.graph()
        self.assertTrue({n["id"] for n in graph1["nodes"]} <= {n["id"] for n in graph2["nodes"]})

    def test_explicit_correction_retains_event_lineage(self):
        self.initial()
        with j.connect(self.root, readonly=True) as db:
            old = db.execute("SELECT event_id FROM events").fetchone()[0]
        j.record_event(self.root, "fixture-1", fixture.event(stage="CORRECTION", supersedes_event_id=old,
            proposed_title="corrected label", displayed_title="corrected label", topic_labels=["corrected-topic"]))
        graph = self.graph()
        self.assertEqual(graph["metadata"]["node_counts"]["Observation"], 1)
        self.assertEqual(graph["metadata"]["node_counts"]["Event"], 2)
        self.assertEqual(sum(e["relation"] == "SUPERSEDES" for e in graph["edges"]), 1)
        event_annotations = [n["properties"]["topic_labels"] for n in graph["nodes"] if n["type"] == "Event"]
        self.assertIn(fixture.event()["topic_labels"], event_annotations)
        self.assertIn(["corrected-topic"], event_annotations)

    def test_build_is_readonly_and_exports_valid_endpoint_graphs(self):
        self.initial()
        database = self.root / "research.sqlite3"
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        kg.build(self.root)
        self.assertEqual(before, hashlib.sha256(database.read_bytes()).hexdigest())
        with (self.root / "knowledge_graph/nodes.csv").open(encoding="utf-8-sig", newline="") as f:
            ids = {r["id"] for r in csv.DictReader(f)}
        with (self.root / "knowledge_graph/edges.csv").open(encoding="utf-8-sig", newline="") as f:
            self.assertTrue(all(r["source"] in ids and r["target"] in ids for r in csv.DictReader(f)))
        doc = ET.parse(self.root / "knowledge_graph/graph.graphml")
        self.assertEqual(len(doc.findall(".//{http://graphml.graphdrawing.org/xmlns}node")), len(ids))

    def test_script_terminator_in_title_stays_inert_data(self):
        title = '</script><img src=x onerror="throw 1">'
        self.initial(proposed_title=title, displayed_title=title)
        kg.build(self.root)
        fragment = (self.root / "knowledge_graph/rename-knowledge-graph.html").read_text()
        self.assertNotIn(title, fragment)
        self.assertIn("\\u003c/script>", fragment)

    def test_daily_export_hook_uses_snapshot_and_refreshes_graph(self):
        self.initial()
        config = self.root / "knowledge_graph/config.json"
        config.parent.mkdir()
        config.write_text('{"enabled":true,"refresh_on_journal_export":false}')
        self.assertNotIn("knowledge_graph", j.export(self.root))
        config.write_text('{"enabled":true}')
        first = j.export(self.root)
        self.assertEqual(first["knowledge_graph"]["terminal_observations"], 1)
        j.ingest(self.root, {"run": fixture.run_spec("later", "2025-01-02"), "events": [fixture.event()], "final_state": "COMPLETE"})
        second = j.export(self.root)
        self.assertEqual(second["knowledge_graph"]["terminal_observations"], second["terminal_outcomes"])
        self.assertEqual(second["knowledge_graph"]["terminal_observations"], 2)

    def test_missing_superseded_endpoint_fails_before_publishing(self):
        self.initial()
        source = kg.snapshot(self.root)
        payload = json.loads(source["events"][0]["payload_json"])
        payload["supersedes_event_id"] = "f" * 64
        source["events"][0]["payload_json"] = json.dumps(payload)
        with self.assertRaisesRegex(ValueError, "Dangling"):
            kg.derive(source)

    def test_standalone_report_has_styles_and_does_not_change_relation_evidence(self):
        self.initial()
        graph, view = kg.derive(kg.snapshot(self.root))
        self.assertEqual(view["report"]["runs"][0]["terminal_count"], 1)
        self.assertEqual(view["report"]["runs"][0]["status_counts"], {"RENAMED": 1})
        self.assertEqual(view["report"]["runs"][0]["pending_count"], 0)
        before = copy.deepcopy(graph)
        kg.build(self.root)
        html = (self.root / "knowledge_graph/rename-knowledge-graph.html").read_text()
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn('name="viewport"', html)
        self.assertIn('--kg-e0:', html)
        self.assertIn('<title>Chat Lineage', html)
        self.assertEqual(before, kg.derive(kg.snapshot(self.root))[0])

    def test_report_keeps_missing_scope_and_pending_targets_in_denominator(self):
        run = fixture.run_spec()
        run["requested_count"] = 10
        j.start_run(self.root, run)
        _, view = kg.derive(kg.snapshot(self.root))
        report = view["report"]["runs"][0]
        self.assertEqual((report["requested_count"], report["frozen_count"], report["pending_count"]), (10, 1, 10))
        self.assertEqual(report["targets"][0]["status"], "PENDING")
        self.assertIsNone(report["targets"][0]["displayed_title"])


if __name__ == "__main__":
    unittest.main()
