"""Proposed service-alive scheduler: production activation remains policy-blocked.

Only an explicitly generated, persistently marked engineering root can exercise
the engine. This is not an owner-approved backup frequency or recovery policy.
Append-only records are process-restart evidence, not power-loss proof.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import threading
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backup_manager import BackupManager
from runtime_config import is_reparse, startup_lock

SCHEMA = "kinelab.backup-schedule-event.v1"
TEST_DECLARATION = {"schema": "kinelab.backup-scheduler-test.v1", "purpose": "TEST_ONLY"}
LIMIT = 4096
RECORD_BYTES = 64 * 1024
TERMINAL = {"SUCCEEDED", "FAILED", "MISSED", "INTERRUPTED", "CLOCK_UNCERTAIN"}


class BackupScheduleError(ValueError):
    """Fail-closed scheduler state or policy refusal."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _integer(value: object, lower: int = 0, upper: int = 253402300799) -> int:
    if type(value) is not int or not lower <= value <= upper:
        raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: bounded integer required")
    return value


def _ordinary(path: Path) -> None:
    for entry in (path, *path.parents):
        if is_reparse(entry):
            raise BackupScheduleError("BACKUP_SCHEDULE_PATH_INVALID: linked control path")


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _read(path: Path) -> bytes:
    _ordinary(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > RECORD_BYTES:
        raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: bounded ordinary file required")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(RECORD_BYTES + 1)
        after_fd = os.fstat(stream.fileno())
    after = path.stat()
    if (len(data) > RECORD_BYTES or _identity(before) != _identity(opened)
            or _identity(opened) != _identity(after_fd) or _identity(before) != _identity(after)):
        raise BackupScheduleError("BACKUP_SCHEDULE_STATE_CHANGED: control input changed")
    return data


def _json(data: bytes) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: duplicate key")
            result[key] = value
        return result
    try:
        value = json.loads(data, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    except (UnicodeError, ValueError) as error:
        raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: invalid JSON") from error
    if type(value) is not dict:
        raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: object required")
    return value


class BackupSchedule:
    """One OS-held writer; exact immutable journal; no pruning or archive adoption."""

    def __init__(self, manager: BackupManager, *, test_only: bool = False):
        self.manager = manager
        self.root = manager.projects_root
        self.control = self.root / ".backup-scheduler"
        self.events = self.control / "events"
        self.test_only = test_only is True
        if self.test_only:
            self._test_root()

    def _test_root(self) -> None:
        if _json(_read(self.root / "TEST_ONLY_SCHEDULER.json")) != TEST_DECLARATION:
            raise BackupScheduleError("BACKUP_SCHEDULE_TEST_ROOT_REQUIRED")

    def _inspect(self) -> tuple[list[dict[str, Any]], str | None]:
        """Keep a validated historical prefix; never repair ambiguous evidence."""
        result: list[dict[str, Any]] = []
        try:
            _ordinary(self.control)
            if not self.control.exists():
                return result, None
            if not self.control.is_dir():
                raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: control directory")
            for child in self.control.iterdir():
                if child.name not in {"events", "prepared", "t6-startup.lock"}:
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: unknown control file")
                _ordinary(child)
            paths: list[Path] = []
            if self.events.exists():
                if not self.events.is_dir():
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: events directory")
                for path in self.events.iterdir():
                    paths.append(path)
                    if len(paths) > LIMIT:
                        raise BackupScheduleError("BACKUP_SCHEDULE_CAPACITY: journal requires review")
            previous = None
            for number, path in enumerate(sorted(paths), 1):
                if path.name != f"{number:08d}.json":
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: noncontiguous journal")
                raw = _read(path)
                event = _json(raw)
                if (set(event) != {"schema", "sequence", "previous_sha256", "type", "at", "data"}
                        or event["schema"] != SCHEMA or event["sequence"] != number
                        or type(event["sequence"]) is not int or event["previous_sha256"] != previous
                        or type(event["data"]) is not dict or type(event["type"]) is not str
                        or canonical(event) != raw):
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: canonical chain required")
                _integer(event["at"])
                self._state([*result, event])
                result.append(event)
                previous = hashlib.sha256(raw).hexdigest()
            prepared = self.control / "prepared"
            if prepared.exists():
                if not prepared.is_dir():
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: prepared directory")
                for count, witness in enumerate(prepared.iterdir(), 1):
                    if count > LIMIT or re.fullmatch(r"[0-9]{8}\.json", witness.name) is None:
                        raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: prepared inventory")
                    published = self.events / witness.name
                    raw = _read(witness)
                    if not published.exists() or _read(published) != raw:
                        raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: unpublished preparation retained")
                    if _identity(witness.stat()) != _identity(published.stat()):
                        raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: prepared identity changed")
            return result, None
        except (OSError, ValueError, KeyError, TypeError):
            return result, "JOURNAL_RECOVERY_REQUIRED"

    def _load(self) -> list[dict[str, Any]]:
        events, issue = self._inspect()
        if issue is not None:
            raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: journal recovery required")
        return events


    @staticmethod
    def _state(events: list[dict[str, Any]]) -> dict[str, Any]:
        plan = None
        jobs: dict[str, dict[str, Any]] = {}
        active = None
        last_verified = None
        last_at = 0
        clock_health = None
        pump_health = None
        for event in events:
            data, kind = event["data"], event["type"]
            if event["at"] < last_at:
                raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: nonmonotonic history")
            last_at = event["at"]
            if kind == "CLOCK_OBSERVATION":
                if data or clock_health is not None or pump_health is not None or active is not None:
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: clock observation")
            elif kind == "CLOCK_ANOMALY":
                if (set(data) != {"observed_utc", "reference_utc"}
                        or _integer(data["reference_utc"]) != last_at
                        or _integer(data["observed_utc"]) >= last_at or clock_health is not None):
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: clock health")
                clock_health = data
            elif kind == "PUMP_FAILURE":
                if (set(data) != {"reason", "observed_utc"} or data["reason"] != "TICK_FAILED"
                        or _integer(data["observed_utc"]) > last_at or pump_health is not None):
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: pump health")
                pump_health = data
            elif kind == "PLAN":
                if plan is not None or set(data) != {"mode", "schedule_id", "first_due", "interval", "grace"}:
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: plan")
                if (data["mode"] != "TEST_ONLY" or type(data["schedule_id"]) is not str or re.fullmatch(r"[a-f0-9]{32}", data["schedule_id"]) is None):
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: generated plan required")
                _integer(data["first_due"])
                _integer(data["interval"], 1, 365 * 86400)
                _integer(data["grace"], 0, data["interval"] - 1)
                plan = data
            elif kind == "QUEUED":
                if plan is None or active is not None or set(data) != {"operation_id", "due", "archive"}:
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: pending overlap")
                due = _integer(data["due"])
                operation = hashlib.sha256(canonical({"schedule_id": plan["schedule_id"], "due": due})).hexdigest()[:32]
                if (due < plan["first_due"] or (due - plan["first_due"]) % plan["interval"]
                        or due != max((job["due"] for job in jobs.values()), default=plan["first_due"] - plan["interval"]) + plan["interval"]
                        or data["operation_id"] != operation or operation in jobs
                        or data["archive"] != f"scheduled-{operation}.zip"):
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: operation identity")
                active = operation
                jobs[operation] = {**data, "status": kind, "at": event["at"]}
            elif kind == "RUNNING":
                if set(data) != {"operation_id"} or active is None or data["operation_id"] != active or jobs[active]["status"] != "QUEUED":
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: running transition")
                jobs[active] = {**jobs[active], "status": kind, "at": event["at"]}
            elif kind in TERMINAL:
                keys = {"operation_id", "reason", "verification"}
                if set(data) != keys or active is None or data["operation_id"] != active:
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: terminal transition")
                verification = data["verification"]
                if kind == "SUCCEEDED":
                    if (jobs[active]["status"] != "RUNNING" or data["reason"] != "MEMBERS_VERIFIED"
                            or type(verification) is not dict or set(verification) != {"generation_id", "sha256", "bytes"}
                            or type(verification["generation_id"]) is not str or re.fullmatch(r"[a-f0-9]{32}", verification["generation_id"]) is None
                            or type(verification["sha256"]) is not str or re.fullmatch(r"[a-f0-9]{64}", verification["sha256"]) is None):
                        raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: verified archive receipt")
                    _integer(verification["bytes"], 1, 1 << 40)
                    last_verified = {"archive": jobs[active]["archive"], **verification, "verified_at": event["at"],
                                     "verification_kind": "CREATED_AND_MEMBER_HASH_VERIFIED"}
                elif (verification is not None or type(data["reason"]) is not str
                      or data["reason"] not in {"BUSY", "BACKUP_FAILED", "INTERRUPTED", "LATE", "CLOCK_UNCERTAIN"}):
                    raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: failure receipt")
                jobs[active] = {**jobs[active], "status": kind, "at": event["at"], "reason": data["reason"]}
                active = None
            else:
                raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: unknown event")
        return {"plan": plan, "jobs": jobs, "active": active, "last_verified_archive": last_verified, "last_at": last_at, "clock_health": clock_health, "pump_health": pump_health}

    def _append(self, events: list[dict[str, Any]], kind: str, at: int, data: dict[str, Any]) -> None:
        if len(events) >= LIMIT:
            raise BackupScheduleError("BACKUP_SCHEDULE_CAPACITY: history requires review")
        event = {"schema": SCHEMA, "sequence": len(events) + 1,
                 "previous_sha256": hashlib.sha256(canonical(events[-1])).hexdigest() if events else None,
                 "type": kind, "at": at, "data": data}
        self._state([*events, event])
        raw = canonical(event)
        if len(raw) > RECORD_BYTES:
            raise BackupScheduleError("BACKUP_SCHEDULE_CAPACITY: event too large")
        self.events.mkdir(exist_ok=True)
        _ordinary(self.events)
        prepared = self.control / "prepared"
        prepared.mkdir(exist_ok=True)
        _ordinary(prepared)
        path = self.events / f"{len(events) + 1:08d}.json"
        witness = prepared / path.name
        # Retained immutable preparation: no truncated final filename or cleanup window.
        with witness.open("xb") as stream:
            if stream.write(raw) != len(raw):
                raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: short journal write")
            stream.flush()
            os.fsync(stream.fileno())
        if _read(witness) != raw:
            raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: preparation changed")
        os.link(witness, path)  # Same-filesystem no-overwrite publication; unsupported FS fails closed.
        if _read(path) != raw or _identity(witness.stat()) != _identity(path.stat()):
            raise BackupScheduleError("BACKUP_SCHEDULE_STATE_INVALID: publication changed")
        events.append(event)

    def install_test_plan(self, *, schedule_id: str, first_due: int, interval: int, grace: int, now: int) -> None:
        if not self.test_only:
            raise BackupScheduleError("BACKUP_SCHEDULE_POLICY_REQUIRED: D05/D08 OPEN")
        self._test_root()
        _integer(now)
        plan = {"mode": "TEST_ONLY", "schedule_id": schedule_id, "first_due": first_due, "interval": interval, "grace": grace}
        prospective = [{"type": "PLAN", "at": now, "data": plan}]
        self._state(prospective)
        _ordinary(self.control)
        with startup_lock(self.control, timeout=0.0):
            events = self._load()
            if events:
                if len(events) == 1 and events[0]["data"] == plan:
                    return
                raise BackupScheduleError("BACKUP_SCHEDULE_CONFLICT: immutable plan already exists")
            self._append(events, "PLAN", now, plan)

    def status(self) -> dict[str, Any]:
        events, issue = self._inspect()
        state = self._state(events)
        jobs = list(state["jobs"].values())
        # No production activation route or synthetic recovery-drill success.
        return {"schema": "kinelab.backup-schedule-status.v1", "enabled": False,
                "state": "DISABLED", "policy_status": "OPEN", "next_due_at_utc": None,
                "engine_mode": "TEST_ONLY" if state["plan"] else "UNCONFIGURED",
                "last_job": jobs[-1] if jobs else None, "history": jobs[-50:],
                "missed_count": sum(job["status"] == "MISSED" for job in jobs),
                "last_verified_archive": state["last_verified_archive"],
                "last_verified_recovery_point": None,
                "pruning": {"enabled": False, "reason": "POLICY_NOT_APPROVED"},
                "service_alive_only": True, "journal_capacity": LIMIT, "journal_health": "RECOVERY_REQUIRED" if issue else "VALIDATED", "historical_prefix_only": issue is not None, "engine_health": "REVIEW_REQUIRED" if issue or state["clock_health"] or state["pump_health"] else "IDLE", "clock_health": state["clock_health"], "pump_health": state["pump_health"]}

    def recover(self, *, now: int, strict: bool = True) -> None:
        if not self.control.exists():
            return
        _integer(now)
        if strict is False and self._inspect()[1] is not None:
            return  # Refuse before even creating a previously absent lock anchor.
        _ordinary(self.control)
        with startup_lock(self.control, timeout=0.0):
            inspected, issue = self._inspect()
            if issue is not None and strict is False:
                return  # Expose disabled read-only status; no work or repair authority.
            events = self._load() if issue is not None else inspected
            state = self._state(events)
            if state["active"] is not None:
                # This cannot acknowledge an archive that was not durably acknowledged.
                self._append(events, "INTERRUPTED", max(now, state["last_at"]),
                             {"operation_id": state["active"], "reason": "INTERRUPTED", "verification": None})

    def record_pump_failure(self, *, now: int) -> None:
        if not self.test_only:
            raise BackupScheduleError("BACKUP_SCHEDULE_POLICY_REQUIRED: D05/D08 OPEN")
        self._test_root()
        _integer(now)
        with startup_lock(self.control, timeout=0.0):
            events = self._load()
            state = self._state(events)
            if state["pump_health"] is None:
                self._append(events, "PUMP_FAILURE", max(now, state["last_at"]),
                             {"reason": "TICK_FAILED", "observed_utc": now})


    def tick(self, *, now: int, busy: bool = False, checkpoint: Callable[[str], None] | None = None) -> dict[str, Any]:
        _integer(now)
        if not self.test_only:
            return self.status()
        self._test_root()
        with startup_lock(self.control, timeout=0.0):
            events = self._load()
            state = self._state(events)
            if state["active"] is not None:
                raise BackupScheduleError("BACKUP_SCHEDULE_RECOVERY_REQUIRED")
            if state["clock_health"] is not None or state["pump_health"] is not None:
                raise BackupScheduleError("BACKUP_SCHEDULE_RECOVERY_REQUIRED: retained health review")
            if now < state["last_at"]:
                self._append(events, "CLOCK_ANOMALY", state["last_at"],
                             {"observed_utc": now, "reference_utc": state["last_at"]})
                raise BackupScheduleError("BACKUP_SCHEDULE_CLOCK_UNCERTAIN")
            # Persist idle highwater through the existing fsynced witness protocol.
            # Due-work events already retain now; reserve before any journal write.
            plan = state["plan"]
            if plan is None or now < plan["first_due"]:
                if now > state["last_at"]:
                    self._append(events, "CLOCK_OBSERVATION", now, {})
                return self.status()
            due = plan["first_due"] + ((now - plan["first_due"]) // plan["interval"]) * plan["interval"]
            handled = {job["due"] for job in state["jobs"].values()}
            first_unhandled = max(handled, default=plan["first_due"] - plan["interval"]) + plan["interval"]
            count = (due - first_unhandled) // plan["interval"] + 1
            # Reserve all possible records before any archive publication.
            if count <= 0:
                if now > state["last_at"]:
                    self._append(events, "CLOCK_OBSERVATION", now, {})
                return self.status()
            if len(events) + 4 * count > LIMIT:
                raise BackupScheduleError("BACKUP_SCHEDULE_CAPACITY: complete transition reservation required")
            for slot in range(first_unhandled, due + 1, plan["interval"]):
                operation = hashlib.sha256(canonical({"schedule_id": plan["schedule_id"], "due": slot})).hexdigest()[:32]
                self._append(events, "QUEUED", now, {"operation_id": operation, "due": slot, "archive": f"scheduled-{operation}.zip"})
                if slot != due or now > slot + plan["grace"]:
                    self._append(events, "MISSED", now, {"operation_id": operation, "reason": "LATE", "verification": None})
                    continue
                if busy:
                    self._append(events, "FAILED", now, {"operation_id": operation, "reason": "BUSY", "verification": None})
                    continue
                self._append(events, "RUNNING", now, {"operation_id": operation})
                if checkpoint is not None:
                    checkpoint("after_running")
                archive = self.root / "backups" / f"scheduled-{operation}.zip"
                try:
                    manifest = self.manager.create_backup(archive)
                    if checkpoint is not None:
                        checkpoint("after_archive")
                    # Reuse the exact manager preflight/member verification before acknowledgment.
                    _ordinary(archive)
                    before = archive.stat()
                    with archive.open("rb") as stream:
                        opened = os.fstat(stream.fileno())
                        if (before.st_dev, before.st_ino, before.st_size) != (opened.st_dev, opened.st_ino, opened.st_size):
                            raise BackupScheduleError("BACKUP_SCHEDULE_ARCHIVE_CHANGED")
                        with zipfile.ZipFile(stream) as zipped:
                            checked, members = self.manager._preflight(zipped)
                            self.manager._verify_members(zipped, checked, members)
                        if checked != manifest:
                            raise BackupScheduleError("BACKUP_SCHEDULE_ARCHIVE_CHANGED")
                        stream.seek(0)
                        digest = hashlib.file_digest(stream, "sha256").hexdigest()
                        after_fd = os.fstat(stream.fileno())
                    after = archive.stat()
                    if _identity(before) != _identity(after) or _identity(opened) != _identity(after_fd):
                        raise BackupScheduleError("BACKUP_SCHEDULE_ARCHIVE_CHANGED")
                    verification = {"generation_id": checked["generation"]["id"], "sha256": digest, "bytes": after.st_size}
                except (OSError, ValueError, zipfile.BadZipFile):
                    self._append(events, "FAILED", now, {"operation_id": operation, "reason": "BACKUP_FAILED", "verification": None})
                    continue
                self._append(events, "SUCCEEDED", now, {"operation_id": operation, "reason": "MEMBERS_VERIFIED", "verification": verification})
            return self.status()

    @staticmethod
    def configure(request: object) -> None:
        if (type(request) is not dict or set(request) != {"enabled", "confirm"}
                or type(request["enabled"]) is not bool or request["confirm"] is not True):
            raise BackupScheduleError("BACKUP_SCHEDULE_REQUEST_INVALID")
        if request["enabled"]:
            raise BackupScheduleError("BACKUP_SCHEDULE_POLICY_REQUIRED: D05/D08 OPEN")

    @staticmethod
    def prune() -> None:
        raise BackupScheduleError("BACKUP_PRUNING_UNAVAILABLE: all copies protected; D08 OPEN")


class BackupSchedulePump:
    """Owned local worker; only explicit generated-engine tests may start it today."""

    def __init__(self, tick: Callable[[], object], *, interval: float = 1.0):
        if type(interval) not in {float, int} or not math.isfinite(interval) or not 0 < interval <= 60:
            raise BackupScheduleError("BACKUP_SCHEDULE_PUMP_INVALID: bounded positive interval required")
        self.tick = tick
        self.interval = interval
        self.stop_event = threading.Event()
        self.failure: BaseException | None = None
        self.health_failure: BaseException | None = None
        self.engine: BackupSchedule | None = None
        self.thread = threading.Thread(target=self._run, name="kinelab-backup-schedule", daemon=True)

    def _run(self) -> None:
        try:
            while not self.stop_event.wait(self.interval):
                self.tick()
        except BaseException as error:  # noqa: BLE001 - Preserve cancellation failures for the owner through close().
            self.failure = error
            self.stop_event.set()
            try:
                if self.engine is not None:
                    self.engine.record_pump_failure(now=int(time.time()))
            except BaseException as persistence_error:  # noqa: BLE001 - Retain secondary cancellation without replacing the primary.
                self.health_failure = persistence_error  # Original failure remains primary.

    def start(self, *, test_engine: BackupSchedule) -> None:
        if not test_engine.test_only:
            raise BackupScheduleError("BACKUP_SCHEDULE_POLICY_REQUIRED: D05/D08 OPEN")
        test_engine._test_root()
        self.engine = test_engine
        self.thread.start()

    def close(self, *, timeout: float = 5.0) -> None:
        self.stop_event.set()
        if self.thread.ident is not None:
            self.thread.join(timeout)
            if self.thread.is_alive():
                raise BackupScheduleError("BACKUP_SCHEDULE_SHUTDOWN_BUSY: preserve index until worker exits")
        if self.failure is not None:
            code = "BACKUP_SCHEDULE_PUMP_FAILED_HEALTH_UNRECORDED" if self.health_failure else "BACKUP_SCHEDULE_PUMP_FAILED"
            raise BackupScheduleError(code + ": inspect retained history") from self.failure
