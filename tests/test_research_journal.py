import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/research_journal.py"
spec = importlib.util.spec_from_file_location("journal", SCRIPT)
j = importlib.util.module_from_spec(spec)
spec.loader.exec_module(j)
URL = "https://chatgpt.com/c/synthetic-a"


def run_spec(run_id="fixture-1", day="2025-01-01", mode="apply", title="Analyze"):
    return {"run_id": run_id, "event_date": day, "mode": mode, "source_type": "synthetic",
            "source_ref": "isolated test fixture, not browser evidence", "skill_version": "1.2.0",
            "scope_kind": "recent_top_n", "selection_rule": "first one, pinned excluded",
            "requested_count": 1, "exclude_pinned": True,
            "targets": [{"conversation_url": URL, "original_title": title}]}


def event(status="RENAMED", **extra):
    value = {"conversation_url": URL, "status": status, "decision": "rename",
             "proposed_title": "Fictional Alpha | Research design", "displayed_title": "Fictional Alpha | Research design",
             "save_attempted": True, "rationale": "Synthetic metadata validation only",
             "reason_codes": ["MISSING_OBJECT"], "topic_labels": ["Fictional Alpha"], "task_type": "research",
             "annotation_basis": "visible_context", "verification": {k: True for k in j.CHECKS}}
    value.update(extra)
    return value


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        j.init(self.root, allow_synthetic=True)

    def tearDown(self):
        self.temp.cleanup()

    def bundle(self, spec=None, events=None, state="COMPLETE"):
        return {"run": spec or run_spec(), "events": events if events is not None else [event()], "final_state": state}

    def test_same_bundle_is_idempotent_but_later_day_is_a_new_observation(self):
        bundle = self.bundle()
        self.assertEqual(j.ingest(self.root, bundle)["events_inserted"], 1)
        self.assertEqual(j.ingest(self.root, bundle)["events_inserted"], 0)
        later = self.bundle(run_spec("fixture-2", "2025-01-02", title="Fictional Alpha | Research design"), [
            event("ALREADY CORRECT", decision="keep", save_attempted=False)])
        j.ingest(self.root, later)
        self.assertEqual(j.stats(self.root)["events"], 2)
        self.assertEqual(j.stats(self.root)["conversations"], 1)

    def test_frozen_scope_cannot_change_under_same_run_id(self):
        spec = run_spec()
        j.start_run(self.root, spec)
        different = copy.deepcopy(spec)
        different["targets"][0]["conversation_url"] = "https://chatgpt.com/c/synthetic-b"
        with self.assertRaisesRegex(ValueError, "different frozen"):
            j.start_run(self.root, different)

    def test_pending_targets_do_not_inflate_observations_or_latest_titles(self):
        j.ingest(self.root, self.bundle())
        pending = run_spec("fixture-pending", "2025-01-02")
        j.start_run(self.root, pending)
        j.record_event(self.root, "fixture-pending", event(
            stage="SAVE_PENDING", status=None, displayed_title="unverified draft"))
        j.finish_run(self.root, "fixture-pending", "INTERRUPTED")
        empty = run_spec("fixture-empty", "2025-01-03")
        empty["targets"][0]["conversation_url"] = "https://chatgpt.com/c/synthetic-only-pending"
        j.start_run(self.root, empty)
        j.finish_run(self.root, "fixture-empty", "INTERRUPTED")
        exported = j.export(self.root)
        self.assertEqual(exported["terminal_outcomes"], 1)
        self.assertEqual(exported["pending_targets"], 2)
        with (self.root / "exports/conversations.csv").open(encoding="utf-8-sig", newline="") as f:
            rows = {r["conversation_url"]: r for r in csv.DictReader(f)}
        row = rows[URL]
        self.assertEqual((row["target_count"], row["pending_target_count"], row["observation_count"]), ("2", "1", "1"))
        self.assertEqual(row["last_observed_date"], "2025-01-01")
        self.assertEqual(json.loads(row["latest_observed_titles"]), [event()["displayed_title"]])
        unobserved = rows[empty["targets"][0]["conversation_url"]]
        self.assertEqual(unobserved["observation_count"], "0")
        self.assertEqual(unobserved["first_observed_date"], "")
        self.assertEqual(unobserved["last_observed_date"], "")
        self.assertEqual(json.loads(unobserved["latest_observed_titles"]), [])

    def test_unapproved_body_field_rolls_back_the_entire_bundle(self):
        bad = event(body="not permitted")
        with self.assertRaisesRegex(ValueError, "unapproved fields"):
            j.ingest(self.root, self.bundle(events=[bad]))
        self.assertEqual(j.stats(self.root)["runs"], 0)
        self.assertEqual(j.stats(self.root)["events"], 0)

    def test_outside_scope_result_cannot_be_inserted(self):
        j.start_run(self.root, run_spec())
        with self.assertRaisesRegex(ValueError, "outside frozen"):
            j.record_event(self.root, "fixture-1", event(conversation_url="https://chatgpt.com/c/synthetic-b"))

    def test_renamed_requires_positive_identity_and_observed_new_title(self):
        for change in [{"save_attempted": None}, {"displayed_title": None},
                       {"verification": {k: False for k in j.CHECKS}}, {"decision": "keep"}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                j.ingest(self.root, self.bundle(events=[event(**change)]))
        self.assertEqual(j.stats(self.root)["events"], 0)

    def test_plan_survives_new_connection_without_assuming_no_save(self):
        j.start_run(self.root, run_spec())
        plan = event(stage="PLANNED", status=None, displayed_title=None, save_attempted=None)
        j.record_event(self.root, "fixture-1", plan)
        self.assertEqual(j.stats(self.root)["statuses"], {"PENDING": 1})
        with self.assertRaisesRegex(ValueError, "COMPLETE requires"):
            j.finish_run(self.root, "fixture-1", "COMPLETE")
        j.record_event(self.root, "fixture-1", event())
        j.finish_run(self.root, "fixture-1", "COMPLETE")
        self.assertEqual(j.stats(self.root)["events"], 2)

    def test_inspect_has_its_own_result_without_claiming_a_rename(self):
        with self.assertRaisesRegex(ValueError, "Inspect cannot"):
            j.ingest(self.root, self.bundle(run_spec(mode="inspect")))
        inspected = event("INSPECTED", save_attempted=False)
        j.ingest(self.root, self.bundle(run_spec(mode="inspect"), [inspected]))
        self.assertEqual(j.stats(self.root)["statuses"], {"INSPECTED": 1})

    def test_pending_save_checkpoint_is_durable_and_never_counted_as_success(self):
        j.start_run(self.root, run_spec())
        j.record_event(self.root, "fixture-1", event(stage="PLANNED", status=None, displayed_title=None, save_attempted=None))
        checkpoint = event(stage="SAVE_PENDING", status=None, displayed_title=None, verification={})
        j.record_event(self.root, "fixture-1", checkpoint)
        self.assertFalse(j.record_event(self.root, "fixture-1", checkpoint)["inserted"])
        with j.connect(self.root, readonly=True) as db:
            row = db.execute("SELECT stage,status,payload_json FROM v_outcomes").fetchone()
        self.assertEqual(row["stage"], "SAVE_PENDING")
        self.assertEqual(row["status"], "PENDING")
        self.assertTrue(json.loads(row["payload_json"])["save_attempted"])
        with self.assertRaises(ValueError):
            j.finish_run(self.root, "fixture-1", "COMPLETE")
        j.record_event(self.root, "fixture-1", event())
        j.finish_run(self.root, "fixture-1", "COMPLETE")
        self.assertEqual(j.stats(self.root)["events"], 3)

    def test_blocked_result_is_retained_and_run_is_partial(self):
        blocked = event("BLOCKED", decision="undetermined", proposed_title=None, displayed_title="Analyze", save_attempted=False,
                        reason_codes=["BODY_NOT_READY"], context_level="not_ready", verification={})
        with self.assertRaisesRegex(ValueError, "COMPLETE requires"):
            j.ingest(self.root, self.bundle(events=[blocked]))
        j.ingest(self.root, self.bundle(events=[blocked], state="PARTIAL"))
        self.assertEqual(j.stats(self.root)["statuses"], {"BLOCKED": 1})

    def test_conflicting_result_requires_explicit_append_only_correction(self):
        j.ingest(self.root, self.bundle())
        changed = event(rationale="Corrected metadata, no new browser action")
        with self.assertRaises(ValueError):
            j.record_event(self.root, "fixture-1", changed)
        with j.connect(self.root, readonly=True) as db:
            previous = db.execute("SELECT event_id FROM events").fetchone()[0]
        changed.update(stage="CORRECTION", supersedes_event_id=previous)
        new = j.record_event(self.root, "fixture-1", changed)
        self.assertTrue(new["inserted"])
        self.assertEqual(j.stats(self.root)["events"], 2)
        j.finish_run(self.root, "fixture-1", "COMPLETE")
        with j.connect(self.root, readonly=True) as db:
            old_payload = json.loads(db.execute("SELECT payload_json FROM events WHERE event_id=?", (previous,)).fetchone()[0])
            latest = json.loads(db.execute("SELECT payload_json FROM v_outcomes").fetchone()[0])
        self.assertNotEqual(old_payload["rationale"], latest["rationale"])

    def test_metric_unknown_stays_null_and_zero_is_not_missing(self):
        j.ingest(self.root, {**self.bundle(), "metrics": {"observations": 0, "coverage": "partial"}})
        j.finish_run(self.root, "fixture-1", "COMPLETE")
        with j.connect(self.root, readonly=True) as db:
            values = json.loads(db.execute("SELECT metrics_json FROM runs").fetchone()[0])
        self.assertEqual(values["observations"], 0)
        self.assertIsNone(values["clicks"])
        with self.assertRaises(ValueError):
            j.metrics({"observations": True})

    def test_export_is_formula_safe_but_canonical_title_is_unchanged(self):
        title = '=HYPERLINK("https://example.invalid")'
        j.ingest(self.root, self.bundle(run_spec(title=title)))
        result = j.export(self.root)
        self.assertEqual(result["outcomes"], 1)
        with (self.root / "exports/outcomes.csv").open(encoding="utf-8-sig", newline="") as f:
            row = next(csv.DictReader(f))
        self.assertTrue(row["original_title"].startswith("'="))
        with j.connect(self.root, readonly=True) as db:
            self.assertEqual(db.execute("SELECT original_title FROM targets").fetchone()[0], title)
        manifest = json.loads((self.root / "exports/manifest.json").read_text())
        for item in manifest["files"]:
            self.assertEqual(hashlib.sha256((self.root / item["path"]).read_bytes()).hexdigest(), item["sha256"])

    def test_historical_backfill_cannot_claim_current_visible_context(self):
        spec = run_spec()
        spec["source_type"] = "historical_transcript"
        with self.assertRaisesRegex(ValueError, "Backfill"):
            j.ingest(self.root, self.bundle(spec))
        j.ingest(self.root, self.bundle(spec, [event(annotation_basis="historical_record")]))
        j.export(self.root)
        text = (self.root / "exports/outcomes.csv").read_text(encoding="utf-8-sig")
        self.assertIn("historical_report", text)

    def test_production_dataset_rejects_synthetic_fixtures(self):
        other = self.root / "production"
        j.init(other)
        with self.assertRaisesRegex(ValueError, "Synthetic fixtures"):
            j.ingest(other, self.bundle())
        self.assertEqual(j.stats(other)["events"], 0)

    def test_legacy_report_retains_unknown_verification_instead_of_fabricating_it(self):
        spec = run_spec()
        spec["source_type"] = "historical_artifact"
        result = event(annotation_basis="historical_record", verification={}, save_attempted=None)
        j.ingest(self.root, self.bundle(spec, [result]))
        j.export(self.root)
        with (self.root / "exports/outcomes.csv").open(encoding="utf-8-sig", newline="") as f:
            row = next(csv.DictReader(f))
        self.assertEqual(row["verification_complete"], "False")
        self.assertIsNone(json.loads(row["verification"])["document_url_matches"])
        self.assertEqual(row["verification_level"], "historical_report")
        wrong = event(annotation_basis="historical_record", verification={"document_url_matches": False})
        with self.assertRaises(ValueError):
            j.ingest(self.root, self.bundle({**run_spec("fixture-wrong"), "source_type": "historical_artifact"}, [wrong]))

    def test_noncanonical_and_credential_urls_are_rejected(self):
        for url in ["http://chatgpt.com/c/a", "https://x:secret" + "@" + "chatgpt.com/c/a", "https://chatgpt.com/c/a?token=secret",
                    "https://chatgpt.com/c/a#fragment", "https://example.invalid/c/a"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                j.canonical_url(url)

    def test_naive_timestamp_is_rejected_instead_of_guessing_timezone(self):
        with self.assertRaisesRegex(ValueError, "explicit offset"):
            j.timestamp("2025-01-01T23:40:00")
        self.assertEqual(j.timestamp("2025-01-01T23:40:00+08:00"), "2025-01-01T15:40:00+00:00")

    def test_same_day_titles_are_not_falsely_ordered_when_observation_time_is_unknown(self):
        j.ingest(self.root, self.bundle())
        other = event(proposed_title="Fictional Beta | Literature review", displayed_title="Fictional Beta | Literature review")
        j.ingest(self.root, self.bundle(run_spec("fixture-2"), [other]))
        j.export(self.root)
        with (self.root / "exports/conversations.csv").open(encoding="utf-8-sig", newline="") as f:
            row = next(csv.DictReader(f))
        self.assertEqual(row["same_day_title_ambiguity"], "True")
        self.assertEqual(len(json.loads(row["latest_observed_titles"])), 2)


if __name__ == "__main__":
    unittest.main()
