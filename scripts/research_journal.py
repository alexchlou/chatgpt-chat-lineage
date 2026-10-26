#!/usr/bin/env python3
"""Local metadata journal. It never connects to a browser or imports chat bodies."""
import argparse
import csv
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

SCHEMA = "1.0.0"
RECOVERY = "rename-recovery/1"
STATES = {"RENAMED", "ALREADY CORRECT", "BLOCKED", "VERIFICATION FAILED", "INSPECTED"}
SOURCES = {"live_ui", "historical_transcript", "historical_artifact", "synthetic"}
REASONS = {"EXISTING_TITLE_ADEQUATE", "MISSING_OBJECT", "MISSING_TASK", "TOPIC_EVOLVED",
           "OUTDATED_CLAIM", "AMBIGUOUS_TOPIC", "BODY_NOT_READY", "LOGIN_REQUIRED",
           "IDENTITY_AMBIGUOUS", "CONTROL_UNCLEAR", "SAVE_UNCONFIRMED", "OTHER"}
TASKS = {"research", "reading_review", "monitoring", "submission_preparation", "translation",
         "device_instructions", "document_workflow", "other", "undetermined"}
METRICS = {"observations", "additional_observations", "clicks", "additional_clicks", "input_writes",
           "snapshot_chars_read", "context_chars_emitted", "wall_elapsed_ms", "body_expansions", "save_attempts"}
CHECKS = {"address_url_matches", "document_url_matches", "sidebar_title_matches", "editor_closed"}
RUN_KEYS = {"run_id", "event_date", "timezone", "mode", "source_type", "source_ref", "source_sha256",
            "triggered_at", "scheduled_at", "skill_version", "operator_model", "scope_kind",
            "selection_rule", "requested_count", "exclude_pinned", "limitations", "targets", "recovery_protocol", "browser_binding"}
EVENT_KEYS = {"conversation_url", "stage", "status", "decision", "proposed_title", "displayed_title",
              "rationale", "reason_codes", "topic_labels", "task_type", "annotation_basis", "context_level",
              "observed_at", "save_attempted", "verification", "metrics", "supersedes_event_id", "observation"}
OBSERVATION_KEYS = {"protocol", "run_id", "target_url", "session_epoch", "binding_key", "snapshot_id",
                    "observed_at", "fresh", "address_url", "document_url", "document_title",
                    "sidebar_title", "editor_closed", "identity_source"}

DDL = """
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, event_date TEXT NOT NULL, mode TEXT NOT NULL, source_type TEXT NOT NULL,
 state TEXT NOT NULL, metadata_json TEXT NOT NULL, metrics_json TEXT NOT NULL,
 recorded_at TEXT NOT NULL, finalized_at TEXT
);
CREATE TABLE IF NOT EXISTS targets (
 run_id TEXT NOT NULL REFERENCES runs(run_id), conversation_url TEXT NOT NULL,
 position INTEGER NOT NULL, original_title TEXT NOT NULL,
 PRIMARY KEY(run_id, conversation_url), UNIQUE(run_id, position)
);
CREATE TABLE IF NOT EXISTS events (
 event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, conversation_url TEXT NOT NULL,
 sequence INTEGER NOT NULL, stage TEXT NOT NULL, status TEXT, payload_json TEXT NOT NULL,
 recorded_at TEXT NOT NULL,
 FOREIGN KEY(run_id,conversation_url) REFERENCES targets(run_id,conversation_url),
 UNIQUE(run_id,conversation_url,sequence)
);
CREATE TABLE IF NOT EXISTS save_intents (
 run_id TEXT NOT NULL, conversation_url TEXT NOT NULL, intent_id TEXT NOT NULL UNIQUE,
 proposed_title TEXT NOT NULL, receipt_json TEXT NOT NULL, armed_at TEXT NOT NULL,
 PRIMARY KEY(run_id,conversation_url),
 FOREIGN KEY(run_id,conversation_url) REFERENCES targets(run_id,conversation_url)
);
CREATE VIEW IF NOT EXISTS v_outcomes AS
 SELECT r.run_id,r.event_date,r.mode,r.source_type,r.state AS run_state,
 t.position,t.conversation_url,t.original_title,e.event_id,e.stage,
 CASE WHEN e.status IS NULL THEN 'PENDING' ELSE e.status END AS status,e.payload_json
 FROM targets t JOIN runs r USING(run_id)
 LEFT JOIN events e ON e.run_id=t.run_id AND e.conversation_url=t.conversation_url
 AND e.sequence=(SELECT MAX(e2.sequence) FROM events e2
 WHERE e2.run_id=t.run_id AND e2.conversation_url=t.conversation_url);
"""


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def line(value, label, limit=300, nullable=False):
    if value is None and nullable:
        return None
    require(isinstance(value, str) and bool(value.strip()), label + " must be nonempty text")
    require(len(value) <= limit and not any(c in value for c in "\r\n\x00"), label + " must be bounded single-line metadata")
    return value


def only_keys(value, keys, label):
    require(isinstance(value, dict), label + " must be an object")
    require(not (set(value) - keys), label + " contains unapproved fields: " + ", ".join(sorted(set(value) - keys)))


def canonical_url(value):
    line(value, "conversation_url", 500)
    u = urlsplit(value)
    require(u.scheme == "https" and u.netloc == "chatgpt.com" and not u.query and not u.fragment,
            "Exact HTTPS ChatGPT conversation URL required; no credentials, query or fragment")
    require(re.fullmatch(r"/(?:g/[^/]+/)?c/[a-zA-Z0-9-]+/?", u.path), "Unsupported conversation path")
    return "https://chatgpt.com" + u.path.rstrip("/")


def timestamp(value):
    if value is None:
        return None
    require(isinstance(value, str), "Timestamp must be ISO text or null")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(dt.tzinfo is not None and dt.utcoffset() is not None, "Timestamp needs an explicit offset")
    return dt.astimezone(timezone.utc).isoformat()


def text_list(value, label, count=12, limit=100):
    require(isinstance(value, list) and len(value) <= count, label + " must be a bounded list")
    out = [line(x, label, limit) for x in value]
    require(len(out) == len(set(out)), label + " contains duplicates")
    return out


def metrics(value):
    value = value or {}
    only_keys(value, METRICS | {"coverage"}, "metrics")
    result = {k: value.get(k) for k in sorted(METRICS)}
    for k, v in result.items():
        require(v is None or (type(v) is int and v >= 0), k + " must be a nonnegative integer or null")
    result["coverage"] = value.get("coverage", "unknown")
    require(result["coverage"] in {"complete_run", "helper_only", "partial", "unknown"}, "Unknown metric coverage")
    return result


def normalize_run(spec):
    only_keys(spec, RUN_KEYS, "run")
    run_id = line(spec.get("run_id"), "run_id", 120)
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id), "Unsafe run_id")
    event_date = date.fromisoformat(spec["event_date"]).isoformat()
    tz = spec.get("timezone", "UTC")
    ZoneInfo(tz)
    require(spec.get("mode") in {"apply", "inspect"}, "Unknown mode")
    require(spec.get("source_type") in SOURCES, "Unknown provenance source_type")
    require(spec.get("scope_kind") in {"recent_top_n", "exact_urls", "confirmed_single"}, "Unknown scope_kind")
    count = spec.get("requested_count")
    require(type(count) is int and count > 0, "requested_count must be positive")
    require(spec.get("exclude_pinned") is None or type(spec.get("exclude_pinned")) is bool, "exclude_pinned must be bool or null")
    raw_targets = spec.get("targets")
    require(isinstance(raw_targets, list) and len(raw_targets) <= count, "Frozen targets exceed request")
    targets = []
    for position, target in enumerate(raw_targets, 1):
        only_keys(target, {"conversation_url", "original_title", "position"}, "target")
        require(target.get("position", position) == position, "Frozen positions must be consecutive in input order")
        targets.append({"position": position, "conversation_url": canonical_url(target["conversation_url"]),
                        "original_title": line(target["original_title"], "original_title", 250)})
    require(len({x["conversation_url"] for x in targets}) == len(targets), "Duplicate frozen URLs")
    sha = spec.get("source_sha256")
    require(sha is None or (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)), "Invalid source hash")
    result = {"run_id": run_id, "event_date": event_date, "timezone": tz, "mode": spec["mode"],
            "source_type": spec["source_type"], "source_ref": line(spec.get("source_ref"), "source_ref", 1500),
            "source_sha256": sha, "triggered_at": timestamp(spec.get("triggered_at")),
            "scheduled_at": timestamp(spec.get("scheduled_at")),
            "skill_version": line(spec.get("skill_version"), "skill_version", 40),
            "operator_model": line(spec.get("operator_model"), "operator_model", 100, True),
            "scope_kind": spec["scope_kind"], "selection_rule": line(spec.get("selection_rule"), "selection_rule", 500),
            "requested_count": count, "exclude_pinned": spec.get("exclude_pinned"),
            "limitations": text_list(spec.get("limitations", []), "limitations", 20, 500), "targets": targets}
    # Optional extension: do not change historical normalized payloads or their hashes.
    if "recovery_protocol" in spec:
        require(spec["recovery_protocol"] == RECOVERY, "Unknown recovery protocol")
        result["recovery_protocol"] = RECOVERY
        result["browser_binding"] = line(spec.get("browser_binding"), "browser_binding", 250)
    require("browser_binding" not in spec or "recovery_protocol" in spec, "Browser binding requires the recovery protocol")
    if spec["source_type"] == "live_ui" and re.match(r"^1\.(?:[5-9]|[1-9]\d)\.", result["skill_version"]):
        require(result.get("recovery_protocol") == RECOVERY, "New live runs require the durable recovery protocol")
    return result


def normalize_observation(value, run, target):
    only_keys(value, OBSERVATION_KEYS, "observation")
    require(set(value) == OBSERVATION_KEYS, "Incomplete observation receipt")
    require(value["protocol"] == RECOVERY and value["run_id"] == run["run_id"] and
            value["target_url"] == target["conversation_url"], "Observation target/run mismatch")
    if run.get("browser_binding"):
        require(value["binding_key"] == run["browser_binding"], "Observation browser binding mismatch")
    require(value["fresh"] is True, "Cached observation cannot claim fresh UI evidence")
    result = dict(value)
    for key in ("session_epoch", "binding_key", "snapshot_id"):
        line(value[key], key, 250)
    require(value["snapshot_id"].startswith(value["session_epoch"] + ":"), "Snapshot/session mismatch")
    result["observed_at"] = timestamp(value["observed_at"])
    require(result["observed_at"] is not None, "Observation needs an actual timestamp")
    for key in ("address_url", "document_url"):
        if value[key] is not None:
            result[key] = canonical_url(value[key])
    for key in ("document_title", "sidebar_title"):
        line(value[key], key, 250, True)
    require(type(value["editor_closed"]) is bool, "Editor state must be observed")
    require(value["identity_source"] in {"native-ax", "supported-tab-metadata", "unknown"}, "Invalid observation identity source")
    return result


def normalize_event(value, run, target):
    only_keys(value, EVENT_KEYS, "event")
    url = canonical_url(value["conversation_url"])
    require(url == target["conversation_url"], "Event outside frozen batch")
    stage = value.get("stage", "RESULT")
    require(stage in {"PLANNED", "SAVE_PENDING", "RESULT", "CORRECTION"}, "Unknown stage")
    status = value.get("status")
    pending = stage in {"PLANNED", "SAVE_PENDING"}
    require((pending and status is None) or (not pending and status in STATES), "Invalid stage/status")
    decision = value.get("decision", "undetermined")
    require(decision in {"rename", "keep", "undetermined"}, "Unknown decision")
    proposed = line(value.get("proposed_title"), "proposed_title", 250, True)
    displayed = line(value.get("displayed_title"), "displayed_title", 250, True)
    attempted = value.get("save_attempted")
    require(attempted is None or type(attempted) is bool, "save_attempted must be bool or null")
    verify = value.get("verification", {})
    only_keys(verify, CHECKS | {"identity_source"}, "verification")
    evidence = {k: verify.get(k) for k in sorted(CHECKS)}
    require(all(x is None or type(x) is bool for x in evidence.values()), "Verification flags must be bool or null")
    evidence["identity_source"] = verify.get("identity_source", "unknown")
    require(evidence["identity_source"] in {"native-ax", "supported-tab-metadata", "reported-ui", "unknown"}, "Unknown identity source")
    historical = run["source_type"].startswith("historical")
    verified = all(evidence[k] is not False for k in CHECKS) if historical else all(evidence[k] is True for k in CHECKS)
    if run["mode"] == "inspect" and stage != "PLANNED":
        require(status in {"INSPECTED", "BLOCKED"}, "Inspect cannot assert an applied outcome")
        require(attempted is False, "Inspect cannot attempt saving")
    if status == "RENAMED":
        require(run["mode"] == "apply" and (attempted is True or (historical and attempted is None)) and proposed == displayed and
                proposed != target["original_title"] and decision == "rename", "RENAMED requires one observed changed title and save attempt")
        require(verified, "RENAMED requires positive URL/title/editor verification; historical evidence may be unknown, never contradictory")
    if status == "ALREADY CORRECT":
        require(run["mode"] == "apply" and (attempted is False or (historical and attempted is None)) and
                target["original_title"] == proposed == displayed and decision == "keep", "ALREADY CORRECT requires an unchanged title without save")
        require(verified, "ALREADY CORRECT requires positive target/title verification; historical evidence may be unknown, never contradictory")
    if status == "VERIFICATION FAILED":
        require(attempted is not False, "Save failure cannot assert that no save was attempted")
    if stage == "PLANNED":
        require(attempted is None and displayed is None, "Plan must leave save outcome unknown")
    if stage == "SAVE_PENDING":
        require(run["mode"] == "apply" and attempted is True and decision == "rename" and proposed is not None,
                "SAVE_PENDING requires a reported save attempt without asserting success")
    reason_codes = text_list(value.get("reason_codes", []), "reason_codes")
    require(set(reason_codes) <= REASONS, "Unknown reason code")
    task = value.get("task_type", "undetermined")
    require(task in TASKS, "Unknown task_type")
    basis = value.get("annotation_basis", "not_assessed")
    require(basis in {"visible_context", "historical_record", "title_only", "not_assessed"}, "Unknown annotation basis")
    if run["source_type"].startswith("historical"):
        require(basis != "visible_context", "Backfill must not claim a current visible-context annotation")
    context = value.get("context_level", "unknown")
    require(context in {"outline", "expanded", "partial", "not_ready", "unknown"}, "Unknown context level")
    supersedes = value.get("supersedes_event_id")
    require((stage == "CORRECTION") == (supersedes is not None), "Correction needs an explicit superseded event_id")
    if supersedes is not None:
        require(isinstance(supersedes, str) and re.fullmatch(r"[0-9a-f]{64}", supersedes), "Invalid superseded event id")
    result = {"conversation_url": url, "stage": stage, "status": status, "decision": decision,
            "proposed_title": proposed, "displayed_title": displayed, "save_attempted": attempted,
            "rationale": line(value.get("rationale"), "rationale", 600), "reason_codes": reason_codes,
            "topic_labels": text_list(value.get("topic_labels", []), "topic_labels", 8, 60),
            "task_type": task, "annotation_basis": basis, "context_level": context,
            "observed_at": timestamp(value.get("observed_at")), "verification": evidence,
            "metrics": metrics(value.get("metrics")), "supersedes_event_id": supersedes}
    if "observation" in value:
        obs = normalize_observation(value["observation"], run, target)
        expected = {"address_url_matches": obs["address_url"] == url,
                    "document_url_matches": obs["document_url"] == url,
                    "sidebar_title_matches": obs["sidebar_title"] is not None and obs["sidebar_title"] == proposed,
                    "editor_closed": obs["editor_closed"], "identity_source": obs["identity_source"]}
        require(evidence == expected, "Verification flags conflict with the atomic observation")
        require(result["observed_at"] == obs["observed_at"], "Observation/event timestamp mismatch")
        if displayed is not None:
            require(displayed == obs["sidebar_title"], "Displayed title conflicts with observed sidebar")
        result["observation"] = obs
    if run.get("recovery_protocol") == RECOVERY and status in {"RENAMED", "ALREADY CORRECT"}:
        require("observation" in result, "Fresh atomic observation required for a successful result")
        require(result["observation"]["identity_source"] in {"native-ax", "supported-tab-metadata"},
                "Successful result needs an observed identity source")
    return result


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".journal-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def init(root, allow_synthetic=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    config = root / "dataset.json"
    if config.exists():
        require(json.loads(config.read_text())["schema_version"] == SCHEMA, "Dataset schema mismatch")
    else:
        atomic_write(config, json.dumps({"schema_version": SCHEMA, "created_at": utc_now(),
                     "allow_synthetic": allow_synthetic, "canonical_store": "research.sqlite3",
                     "retention": "title metadata only; no bodies, screenshots, raw AX or credentials"}, ensure_ascii=False, indent=2) + "\n")
    with connect(root) as db:
        db.executescript(DDL)
    return root


def connect(root, readonly=False):
    path = Path(root) / "research.sqlite3"
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) if readonly else sqlite3.connect(str(path), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    if not readonly:
        db.execute("PRAGMA synchronous=FULL")
    return db


def start_in(db, spec, allow_synthetic):
    run = normalize_run(spec)
    require(run["source_type"] != "synthetic" or allow_synthetic, "Synthetic fixtures are not permitted in this dataset")
    existing = db.execute("SELECT metadata_json FROM runs WHERE run_id=?", (run["run_id"],)).fetchone()
    serialized = canonical_json(run)
    if existing:
        require(existing[0] == serialized, "run_id already has a different frozen scope or metadata")
        return run, False
    db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)", (run["run_id"], run["event_date"], run["mode"],
               run["source_type"], "OPEN", serialized, canonical_json(metrics({})), utc_now(), None))
    db.executemany("INSERT INTO targets VALUES (?,?,?,?)", [(run["run_id"], t["conversation_url"], t["position"], t["original_title"]) for t in run["targets"]])
    return run, True


def record_in(db, run_id, value):
    row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    require(row is not None, "Unknown run_id")
    run = json.loads(row["metadata_json"])
    url = canonical_url(value["conversation_url"])
    target = next((t for t in run["targets"] if t["conversation_url"] == url), None)
    require(target is not None, "Event outside frozen batch")
    event = normalize_event(value, run, target)
    payload = canonical_json(event)
    event_id = hashlib.sha256((run_id + "\n" + payload).encode()).hexdigest()
    if db.execute("SELECT 1 FROM events WHERE event_id=?", (event_id,)).fetchone():
        return {"event_id": event_id, "inserted": False}
    if run.get("recovery_protocol") == RECOVERY:
        intent = db.execute("SELECT * FROM save_intents WHERE run_id=? AND conversation_url=?", (run_id, url)).fetchone()
        if event["status"] == "RENAMED" or event["stage"] == "SAVE_PENDING":
            require(intent is not None and intent["proposed_title"] == event["proposed_title"],
                    "Save result requires a committed matching intent")
        if intent:
            require(event["save_attempted"] is not False, "Armed save cannot be asserted unattempted after recovery")
            if event["status"] == "RENAMED":
                require(datetime.fromisoformat(event["observation"]["observed_at"]) >= datetime.fromisoformat(intent["armed_at"]),
                        "Pre-save evidence cannot confirm a saved title")
    previous = db.execute("SELECT * FROM events WHERE run_id=? AND conversation_url=? ORDER BY sequence DESC LIMIT 1", (run_id, url)).fetchone()
    if event["stage"] == "CORRECTION":
        require(previous is not None and event["supersedes_event_id"] == previous["event_id"], "Correction must supersede latest event of this exact target")
    else:
        require(row["state"] == "OPEN", "Finalized run accepts explicit corrections only")
        require(previous is None or previous["stage"] in {"PLANNED", "SAVE_PENDING"}, "Conflicting result; append an explicit correction instead")
        if previous and event["stage"] == "PLANNED":
            raise ValueError("Conflicting plan; use an explicit correction")
    seq = previous["sequence"] + 1 if previous else 1
    db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", (event_id, run_id, url, seq, event["stage"], event["status"], payload, utc_now()))
    if event["stage"] == "CORRECTION" and row["state"] != "OPEN":
        # Preserve the event history and reopen the run for a fresh completeness check.
        db.execute("UPDATE runs SET state='OPEN',finalized_at=NULL WHERE run_id=?", (run_id,))
    return {"event_id": event_id, "inserted": True}


def finish_in(db, run_id, state, counters=None):
    require(state in {"COMPLETE", "PARTIAL", "INTERRUPTED"}, "Unknown run completion state")
    run = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    require(run is not None, "Unknown run_id")
    outcomes = db.execute("SELECT status FROM v_outcomes WHERE run_id=?", (run_id,)).fetchall()
    spec = json.loads(run["metadata_json"])
    if state == "COMPLETE":
        require(len(outcomes) == spec["requested_count"] and all(x[0] in {"RENAMED", "ALREADY CORRECT", "INSPECTED"} for x in outcomes),
                "COMPLETE requires the full requested scope and successful outcomes")
    normalized = run["metrics_json"] if counters is None else canonical_json(metrics(counters))
    if run["state"] != "OPEN":
        require(run["state"] == state and run["metrics_json"] == normalized, "Completion differs from previously finalized run")
        return False
    db.execute("UPDATE runs SET state=?,metrics_json=?,finalized_at=? WHERE run_id=?", (state, normalized, utc_now(), run_id))
    return True


def operate(root, callback):
    root = Path(root).resolve()
    init(root)
    allow = json.loads((root / "dataset.json").read_text())["allow_synthetic"]
    with connect(root) as db:
        db.execute("BEGIN IMMEDIATE")
        result = callback(db, allow)
    return result


def start_run(root, spec):
    # operate returns only after its transaction committed. Never race this with record/arm.
    def work(db, allow):
        run, created = start_in(db, spec, allow)
        return {"run_id": run["run_id"], "run_created": created}
    result = operate(root, work)
    return dict(result, recovery=resume_run(root, result["run_id"]))


def resume_in(db, run_id):
    row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    require(row is not None, "Unknown run_id; freeze and start a new logical run first")
    run = json.loads(row["metadata_json"])
    has_intents = db.execute("SELECT 1 FROM sqlite_master WHERE name='save_intents'").fetchone() is not None
    targets = []
    for t in run["targets"]:
        e = db.execute("SELECT event_id,payload_json FROM events WHERE run_id=? AND conversation_url=? ORDER BY sequence DESC LIMIT 1",
                       (run_id, t["conversation_url"])).fetchone()
        payload = json.loads(e["payload_json"]) if e else None
        i = db.execute("SELECT * FROM save_intents WHERE run_id=? AND conversation_url=?", (run_id, t["conversation_url"])).fetchone() if has_intents else None
        intent = json.loads(i["receipt_json"]) if i else None
        if intent:
            intent["dispatch_authorized"] = False  # readback never grants another click
        if payload and payload["status"] in {"RENAMED", "ALREADY CORRECT", "INSPECTED"}:
            action = "SKIP_VERIFIED"
        elif i or (payload and (payload["stage"] == "SAVE_PENDING" or payload["save_attempted"] is not False and
                               run.get("recovery_protocol") != RECOVERY)):
            action = "VERIFY_ONLY"
        elif payload and payload["status"] == "BLOCKED":
            action = "REVIEW_BLOCKED"
        elif run.get("recovery_protocol") != RECOVERY and payload:
            action = "VERIFY_ONLY"  # legacy PLANNED cannot establish that no save happened
        else:
            action = "READ_CONTEXT"
        targets.append(dict(t, action=action, latest_event=payload,
                            latest_event_id=e["event_id"] if e else None, save_intent=intent))
    return {"protocol": RECOVERY, "run_id": run_id, "committed": True, "state": row["state"],
            "recovery_protocol": run.get("recovery_protocol"), "binding_key": run.get("browser_binding"), "targets": targets}


def resume_run(root, run_id):
    with connect(Path(root).resolve(), readonly=True) as db:
        db.execute("BEGIN")
        return resume_in(db, run_id)


def reopen_run(root, run_id):
    def work(db, _):
        row = db.execute("SELECT state FROM runs WHERE run_id=?", (run_id,)).fetchone()
        require(row is not None and row[0] in {"PARTIAL", "INTERRUPTED", "OPEN"}, "Cannot reopen a complete or unknown run")
        db.execute("UPDATE runs SET state='OPEN',finalized_at=NULL WHERE run_id=?", (run_id,))
    operate(root, work)
    return resume_run(root, run_id)


def arm_save(root, run_id, value):
    """Commit one conservative save intent. Lost acknowledgements never grant a second dispatch."""
    only_keys(value, {"conversation_url", "proposed_title", "observation"}, "save preparation")
    def work(db, _):
        row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        require(row is not None, "Unknown run_id; await start commit before arming")
        run = json.loads(row["metadata_json"])
        require(run.get("recovery_protocol") == RECOVERY and run["mode"] == "apply", "Durable apply protocol required")
        url = canonical_url(value["conversation_url"])
        target = next((t for t in run["targets"] if t["conversation_url"] == url), None)
        require(target is not None, "Save intent outside frozen batch")
        obs = normalize_observation(value["observation"], run, target)
        proposed = line(value["proposed_title"], "proposed_title", 250)
        intent_id = hashlib.sha256((run_id + "\n" + canonical_json(value)).encode()).hexdigest()
        old = db.execute("SELECT * FROM save_intents WHERE run_id=? AND conversation_url=?", (run_id, url)).fetchone()
        if old:
            require(old["intent_id"] == intent_id, "Save already armed; restore journal and verify only")
            return dict(json.loads(old["receipt_json"]), dispatch_authorized=False)
        require(row["state"] == "OPEN", "Finalized run cannot arm a save")
        latest = db.execute("SELECT stage,payload_json FROM events WHERE run_id=? AND conversation_url=? ORDER BY sequence DESC LIMIT 1", (run_id, url)).fetchone()
        require(latest is not None and latest["stage"] == "PLANNED", "Await matching PLANNED commit before arming")
        require(json.loads(latest["payload_json"])["proposed_title"] == proposed, "Prepared title differs from committed plan")
        require(obs["address_url"] == url == obs["document_url"] and obs["document_title"] == target["original_title"] and
                obs["editor_closed"] is False and proposed != target["original_title"], "Preparation must observe target and open title editor")
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(obs["observed_at"])).total_seconds()
        require(-5 <= elapsed <= 120, "Save preparation expired; observe again, never reuse stale controls")
        # Any unresolved target blocks new save authorization, including failure terminals.
        for t in resume_in(db, run_id)["targets"]:
            require(t["conversation_url"] == url or t["action"] != "VERIFY_ONLY", "Another save remains unresolved")
        receipt = {"protocol": RECOVERY, "run_id": run_id, "conversation_url": url,
                   "proposed_title": proposed, "intent_id": intent_id,
                   "session_epoch": obs["session_epoch"], "binding_key": obs["binding_key"],
                   "snapshot_id": obs["snapshot_id"], "armed_at": utc_now(), "dispatch_authorized": True}
        db.execute("INSERT INTO save_intents VALUES (?,?,?,?,?,?)", (run_id, url, intent_id, proposed,
                   canonical_json(receipt), receipt["armed_at"]))
        return receipt
    return operate(root, work)


def record_event(root, run_id, event):
    return operate(root, lambda db, _: record_in(db, run_id, event))


def finish_run(root, run_id, state, counters=None):
    return operate(root, lambda db, _: {"finalized": finish_in(db, run_id, state, counters)})


def ingest(root, bundle):
    only_keys(bundle, {"run", "events", "final_state", "metrics"}, "bundle")
    def work(db, allow):
        run, created = start_in(db, bundle["run"], allow)
        require(isinstance(bundle.get("events"), list), "events must be a list")
        results = [record_in(db, run["run_id"], e) for e in bundle["events"]]
        if bundle.get("final_state"):
            finish_in(db, run["run_id"], bundle["final_state"], bundle.get("metrics"))
        return {"run_id": run["run_id"], "run_created": created, "events_inserted": sum(x["inserted"] for x in results)}
    return operate(root, work)


def safe_cell(value):
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        value = canonical_json(value)
    if isinstance(value, str) and (value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))):
        return "'" + value
    return value


def csv_text(rows, columns):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=columns)
    writer.writeheader()
    writer.writerows({k: safe_cell(row.get(k)) for k in columns} for row in rows)
    return "\ufeff" + out.getvalue()


def export(root):
    root = Path(root).resolve()
    with connect(root, readonly=True) as db:
        db.execute("BEGIN")  # One consistent read snapshot for all derived files.
        runs = [dict(r) for r in db.execute("SELECT * FROM runs ORDER BY event_date,run_id")]
        event_rows = [dict(r) for r in db.execute("SELECT e.* FROM events e JOIN runs r USING(run_id) JOIN targets t USING(run_id,conversation_url) ORDER BY r.event_date,r.run_id,t.position,e.sequence")]
        outcomes = [dict(r) for r in db.execute("SELECT * FROM v_outcomes ORDER BY event_date,run_id,position")]
        has_intents = db.execute("SELECT 1 FROM sqlite_master WHERE name='save_intents'").fetchone() is not None
        intents = [dict(r) for r in db.execute("SELECT * FROM save_intents ORDER BY run_id,conversation_url")] if has_intents else []
    graph_source = {"runs": [dict(r) for r in runs], "events": [dict(r) for r in event_rows],
                    "outcomes": [dict(r) for r in outcomes]}
    run_meta = {r["run_id"]: json.loads(r["metadata_json"]) for r in runs}
    exported_events = [{"event_id": e["event_id"], "run_id": e["run_id"], "sequence": e["sequence"],
                        "recorded_at": e["recorded_at"], "payload": json.loads(e["payload_json"])} for e in event_rows]
    for r in runs:
        snapshot = {"schema_version": SCHEMA, "run": run_meta[r["run_id"]], "state": r["state"],
                    "metrics": json.loads(r["metrics_json"]), "recorded_at": r["recorded_at"],
                    "finalized_at": r["finalized_at"], "events": [e for e in exported_events if e["run_id"] == r["run_id"]]}
        if run_meta[r["run_id"]].get("recovery_protocol") == RECOVERY:
            snapshot["save_intents"] = [dict(json.loads(i["receipt_json"]), dispatch_authorized=False)
                                        for i in intents if i["run_id"] == r["run_id"]]
        atomic_write(root / "runs" / (r["run_id"] + ".json"), json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    flat = []
    for row in outcomes:
        payload = json.loads(row.pop("payload_json")) if row["payload_json"] else {}
        meta = run_meta[row["run_id"]]
        row.update({k: meta[k] for k in ("source_ref", "scope_kind", "selection_rule", "requested_count", "exclude_pinned", "skill_version", "operator_model")})
        row.update({k: payload.get(k) for k in ("proposed_title", "displayed_title", "decision", "rationale", "reason_codes", "topic_labels", "task_type", "annotation_basis", "context_level", "observed_at", "save_attempted", "verification", "metrics")})
        row["observation"] = payload.get("observation")
        row["verification_level"] = "historical_report" if row["source_type"].startswith("historical") else row["source_type"]
        row["verification_complete"] = all((payload.get("verification") or {}).get(k) is True for k in CHECKS)
        flat.append(row)
    columns = ["run_id", "event_date", "mode", "source_type", "verification_level", "verification_complete", "run_state", "position", "conversation_url", "original_title", "proposed_title", "displayed_title", "stage", "status", "decision", "rationale", "reason_codes", "topic_labels", "task_type", "annotation_basis", "context_level", "observed_at", "save_attempted", "verification", "observation", "metrics", "scope_kind", "selection_rule", "requested_count", "exclude_pinned", "skill_version", "operator_model", "source_ref", "event_id"]
    atomic_write(root / "exports" / "outcomes.csv", csv_text(flat, columns))
    atomic_write(root / "exports" / "events.jsonl", "".join(canonical_json(e) + "\n" for e in exported_events))
    run_rows = [{"run_id": r["run_id"], "event_date": r["event_date"], "mode": r["mode"], "source_type": r["source_type"], "state": r["state"], "metadata": run_meta[r["run_id"]], "metrics": json.loads(r["metrics_json"])} for r in runs]
    atomic_write(root / "exports" / "runs.csv", csv_text(run_rows, ["run_id", "event_date", "mode", "source_type", "state", "metadata", "metrics"]))
    changes = [r for r in flat if r["status"] == "RENAMED"]
    atomic_write(root / "exports" / "title_changes.csv", csv_text(changes, columns))
    conversations = []
    for url in sorted({r["conversation_url"] for r in flat}):
        history = [r for r in flat if r["conversation_url"] == url]
        observed = [r for r in history if r["status"] in STATES]
        with_title = [r for r in observed if r.get("displayed_title")]
        latest_date = max((r["event_date"] for r in with_title), default=None)
        latest_titles = sorted({r["displayed_title"] for r in with_title if r["event_date"] == latest_date})
        conversations.append({"conversation_url": url, "first_observed_date": min((r["event_date"] for r in observed), default=None),
                              "last_observed_date": max((r["event_date"] for r in observed), default=None), "observation_count": len(observed),
                              "target_count": len(history), "pending_target_count": len(history) - len(observed),
                              "rename_count": sum(r["status"] == "RENAMED" for r in observed),
                              "latest_observed_titles": latest_titles, "same_day_title_ambiguity": len(latest_titles) > 1})
    atomic_write(root / "exports" / "conversations.csv", csv_text(conversations, ["conversation_url", "first_observed_date", "last_observed_date", "observation_count", "target_count", "pending_target_count", "rename_count", "latest_observed_titles", "same_day_title_ambiguity"]))
    manifest = {"schema_version": SCHEMA, "exported_at": utc_now(), "runs": len(runs), "events": len(event_rows),
                "outcomes": len(flat), "terminal_outcomes": sum(r["status"] in STATES for r in flat),
                "pending_targets": sum(r["status"] == "PENDING" for r in flat),
                "conversations": len(conversations), "renamed": len(changes), "files": []}
    for base in (root / "runs", root / "exports"):
        for p in sorted(base.glob("*")):
            if p.is_file() and p.name != "manifest.json":
                manifest["files"].append({"path": str(p.relative_to(root)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    graph_config = root / "knowledge_graph" / "config.json"
    graph_settings = json.loads(graph_config.read_text()) if graph_config.exists() else {}
    if graph_settings.get("enabled") is True and graph_settings.get("refresh_on_journal_export", True) is True:
        script = Path(__file__).with_name("knowledge_graph.py")
        spec = importlib.util.spec_from_file_location("rename_knowledge_graph", script)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        manifest["knowledge_graph"] = builder.build(root, source=graph_source)
    atomic_write(root / "exports" / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    result = {k: v for k, v in manifest.items() if k != "files"}
    obsidian = graph_settings.get("obsidian", {})
    if obsidian.get("enabled") is True:
        require("knowledge_graph" in result, "Obsidian export requires a freshly committed graph export")
        script = Path(__file__).with_name("obsidian_export.py")
        spec = importlib.util.spec_from_file_location("rename_obsidian_export", script)
        exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(exporter)
        try:
            result["obsidian"] = exporter.sync(root, obsidian["vault_root"])
        except (ValueError, OSError, KeyError) as error:
            raise ValueError("Obsidian sync failed after CSV/graph export; retry export only: " + str(error)) from error
    return result


def stats(root):
    with connect(Path(root).resolve(), readonly=True) as db:
        return {"runs": db.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
                "events": db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                "conversations": db.execute("SELECT COUNT(DISTINCT conversation_url) FROM targets").fetchone()[0],
                "statuses": dict(db.execute("SELECT status,COUNT(*) FROM v_outcomes GROUP BY status")),
                "sources": dict(db.execute("SELECT source_type,COUNT(*) FROM runs GROUP BY source_type")),
                "integrity": db.execute("PRAGMA integrity_check").fetchone()[0]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["init", "start", "resume", "reopen", "arm", "record", "finish", "ingest", "export", "stats"])
    p.add_argument("--root", required=True)
    p.add_argument("--input")
    p.add_argument("--run-id")
    p.add_argument("--state", choices=["COMPLETE", "PARTIAL", "INTERRUPTED"])
    p.add_argument("--metrics")
    a = p.parse_args()
    value = json.loads(Path(a.input).read_text()) if a.input else None
    try:
        if a.command == "init": result = {"root": str(init(Path(a.root).resolve())), "schema_version": SCHEMA}
        elif a.command == "start": result = start_run(a.root, value)
        elif a.command == "resume": result = resume_run(a.root, a.run_id)
        elif a.command == "reopen": result = reopen_run(a.root, a.run_id)
        elif a.command == "arm": result = arm_save(a.root, a.run_id, value)
        elif a.command == "record": result = record_event(a.root, a.run_id, value)
        elif a.command == "finish": result = finish_run(a.root, a.run_id, a.state, json.loads(Path(a.metrics).read_text()) if a.metrics else None)
        elif a.command == "ingest": result = ingest(a.root, value)
        elif a.command == "export": result = export(a.root)
        else: result = stats(a.root)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, sqlite3.Error) as e:
        p.exit(1, "Metadata journal failed: " + str(e) + "\n")


if __name__ == "__main__":
    main()
