import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from test_research_journal import j, run_spec, event, URL
from test_knowledge_graph import kg


def receipt(run_id="recovery", editor_closed=True, title="Fictional Alpha | Research design", **changes):
    r = {"protocol": j.RECOVERY, "run_id": run_id, "target_url": URL,
         "session_epoch": "connection-1", "binding_key": "Chrome/TestProfile/synthetic-extension",
         "snapshot_id": "connection-1:1", "observed_at": j.utc_now(), "fresh": True,
         "address_url": URL, "document_url": URL, "document_title": title,
         "sidebar_title": title, "editor_closed": editor_closed, "identity_source": "native-ax"}
    r.update(changes)
    return r


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        j.init(self.root, allow_synthetic=True)
        self.run = dict(run_spec("recovery"), skill_version="1.5.0", recovery_protocol=j.RECOVERY,
                        browser_binding="Chrome/TestProfile/synthetic-extension")

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self):
        j.start_run(self.root, self.run)
        j.record_event(self.root, "recovery", event(stage="PLANNED", status=None, displayed_title=None, save_attempted=None))
        return {"conversation_url": URL, "proposed_title": event()["proposed_title"],
                "observation": receipt(editor_closed=False, title="Analyze", sidebar_title=None)}

    def observed(self, **changes):
        o = receipt()
        return event(observation=o, observed_at=o["observed_at"],
                     verification={**{k: True for k in j.CHECKS}, "identity_source": "native-ax"}, **changes)

    def test_new_live_run_requires_protocol_without_changing_legacy_normalization(self):
        live = dict(run_spec(), source_type="live_ui", skill_version="1.5.0")
        with self.assertRaisesRegex(ValueError, "durable recovery"):
            j.start_run(self.root, live)
        self.assertNotIn("recovery_protocol", j.normalize_run(run_spec()))
        self.assertNotIn("observation", j.normalize_event(event(), j.normalize_run(run_spec()), j.normalize_run(run_spec())["targets"][0]))

    def test_arm_requires_start_and_plan_commit_and_is_idempotent(self):
        value = {"conversation_url": URL, "proposed_title": event()["proposed_title"],
                 "observation": receipt(editor_closed=False, title="Analyze", sidebar_title=None)}
        with self.assertRaisesRegex(ValueError, "Unknown run_id"):
            j.arm_save(self.root, "recovery", value)
        j.start_run(self.root, self.run)
        with self.assertRaisesRegex(ValueError, "PLANNED"):
            j.arm_save(self.root, "recovery", value)
        value = self.plan()
        self.assertTrue(j.arm_save(self.root, "recovery", value)["dispatch_authorized"])
        self.assertFalse(j.arm_save(self.root, "recovery", value)["dispatch_authorized"])
        changed = copy.deepcopy(value); changed["observation"]["session_epoch"] = "connection-2"
        changed["observation"]["snapshot_id"] = "connection-2:1"
        with self.assertRaisesRegex(ValueError, "already armed"):
            j.arm_save(self.root, "recovery", changed)
        with j.connect(self.root, readonly=True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM save_intents").fetchone()[0], 1)
        self.assertEqual(j.stats(self.root)["statuses"], {"PENDING": 1})

    def test_expired_cached_wrong_target_and_conflicting_flags_are_rejected(self):
        value = self.plan()
        for change in ({"observed_at": "2020-01-01T00:00:00Z"}, {"fresh": False},
                       {"target_url": "https://chatgpt.com/c/other"}, {"snapshot_id": "another:1"}):
            bad = copy.deepcopy(value); bad["observation"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                j.arm_save(self.root, "recovery", bad)
        j.arm_save(self.root, "recovery", value)
        bad = self.observed(); bad["verification"]["sidebar_title_matches"] = False
        with self.assertRaises(ValueError):
            j.record_event(self.root, "recovery", bad)
        bad = self.observed(); bad["observation"]["fresh"] = False
        with self.assertRaisesRegex(ValueError, "Cached"):
            j.record_event(self.root, "recovery", bad)

    def test_pre_intent_observation_cannot_confirm_save(self):
        value = self.plan()
        before = self.observed()
        j.arm_save(self.root, "recovery", value)
        with self.assertRaisesRegex(ValueError, "Pre-save evidence"):
            j.record_event(self.root, "recovery", before)

    def test_result_requires_matching_intent_and_positive_atomic_evidence(self):
        self.plan()
        with self.assertRaisesRegex(ValueError, "committed matching intent"):
            j.record_event(self.root, "recovery", self.observed())
        with self.assertRaisesRegex(ValueError, "atomic observation"):
            j.record_event(self.root, "recovery", event())

    def test_resume_never_arms_and_legacy_plan_is_verification_only(self):
        legacy = run_spec("legacy")
        j.start_run(self.root, legacy)
        j.record_event(self.root, "legacy", event(stage="PLANNED", status=None, displayed_title=None, save_attempted=None))
        self.assertEqual(j.resume_run(self.root, "legacy")["targets"][0]["action"], "VERIFY_ONLY")
        value = self.plan(); j.arm_save(self.root, "recovery", value)
        j.finish_run(self.root, "recovery", "INTERRUPTED")
        restored = j.reopen_run(self.root, "recovery")
        self.assertEqual(restored["targets"][0]["action"], "VERIFY_ONLY")
        self.assertFalse(restored["targets"][0]["save_intent"]["dispatch_authorized"])

    def test_complete_replay_does_not_change_db_bytes_or_regenerate_evidence(self):
        value = self.plan(); j.arm_save(self.root, "recovery", value)
        e = self.observed(); j.record_event(self.root, "recovery", e)
        j.finish_run(self.root, "recovery", "COMPLETE")
        before = hashlib.sha256((self.root / "research.sqlite3").read_bytes()).hexdigest()
        self.assertEqual(j.resume_run(self.root, "recovery")["targets"][0]["action"], "SKIP_VERIFIED")
        self.assertFalse(j.record_event(self.root, "recovery", e)["inserted"])
        j.start_run(self.root, self.run)
        self.assertEqual(before, hashlib.sha256((self.root / "research.sqlite3").read_bytes()).hexdigest())
        with self.assertRaisesRegex(ValueError, "Cannot reopen"):
            j.reopen_run(self.root, "recovery")

    def test_noop_evidence_survives_graph_projection_and_arm_stays_out_of_observations(self):
        self.run["targets"][0]["original_title"] = event()["proposed_title"]
        j.start_run(self.root, self.run)
        e = self.observed(status="ALREADY CORRECT", decision="keep", save_attempted=False)
        j.record_event(self.root, "recovery", e)
        graph, _ = kg.derive(kg.snapshot(self.root))
        obs, = [n for n in graph["nodes"] if n["type"] == "Observation"]
        self.assertEqual(obs["properties"]["observation"]["snapshot_id"], "connection-1:1")
        self.assertNotIn("E2", graph["metadata"]["research_relation_counts"])


if __name__ == "__main__":
    unittest.main()
