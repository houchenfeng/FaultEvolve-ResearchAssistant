"""What a run has to re-establish before a resume spends anything.

A resume opens a database another process wrote, possibly days ago, possibly with
a different task text, a different data snapshot or a different number of islands.
Continuing then keeps the experiment id while quietly changing what the experiment
*is*, so every number in the report after that means something else. This module
makes that identity explicit: it captures what a run was started with, compares it
before the first LLM call, and refuses with the mismatching field named when the
two do not agree.

The same file holds the two mechanics a resume needs next to the check: a way to
take a writable copy of a live SQLite run directory without ignoring its WAL, and a
snapshot of the operator RNG stream so a resumed island continues its exploration
instead of replaying it.
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from faultevolve.common.proc import pid_alive
from faultevolve.cloud.exchange import evaluator_fingerprint, task_fingerprint

#: Bumped when the meaning of a stored field changes, so an old run cannot be
#: read as if it meant the current thing.
IDENTITY_VERSION = 1

#: A data descriptor is a small file that *describes* a dataset. Digesting it is
#: how a resume notices the data moved; digesting the dataset is not something a
#: run may do (the private split must stay unread, and 40 GB cannot be re-read).
DESCRIPTOR_NAMES = ("meta.json", "descriptor.json")

#: Never digest anything under a directory named like this, whatever else is in it.
UNREADABLE_DATA_DIRS = ("holdout",)


class ResumeRefused(RuntimeError):
    """Resuming would continue a different experiment than the one stored."""

    def __init__(
        self,
        experiment_id: str,
        mismatches: dict[str, tuple[str, str]],
        lost: Sequence[str] = (),
    ) -> None:
        self.experiment_id = experiment_id
        #: field -> (what the stored run recorded, what this invocation brings)
        self.mismatches = dict(mismatches)
        #: fields the stored run recorded but this invocation cannot re-derive
        self.lost = list(lost)
        parts = [f"{name}: stored {was!r}, now {now!r}" for name, (was, now) in self.mismatches.items()]
        parts += [f"{name}: stored a value, this run cannot describe it" for name in self.lost]
        super().__init__(
            f"refusing to resume {experiment_id} as the same experiment ({'; '.join(parts)}). "
            "Start a new run, or restore the task, data and island configuration the "
            "stored experiment was created with."
        )


class RunBusy(RuntimeError):
    """Another live process already holds this run."""

    def __init__(self, experiment_id: str, holder_id: str, holder_pid: int | None) -> None:
        self.experiment_id = experiment_id
        self.holder_id = holder_id
        self.holder_pid = holder_pid
        super().__init__(
            f"run {experiment_id} is held by {holder_id} (pid {holder_pid}) which is still "
            "alive; not starting a second process against the same database"
        )


@dataclass
class RunIdentity:
    """The fields that make a resumed run the same experiment.

    An empty value means "this environment could not describe it", which is not the
    same as a match: two unknowns agree only in the weak sense that nothing was
    verified, and the check reports that instead of staying silent.
    """

    identity_version: int = IDENTITY_VERSION
    schema_version: int = 0
    task_fp: str = ""
    evaluator_fp: str = ""
    init_fp: str = ""
    data_fp: str = ""
    seed: int = 0
    island_ids: tuple[str, ...] = ()

    def to_json(self) -> str:
        return json.dumps(
            {
                "identity_version": self.identity_version,
                "schema_version": self.schema_version,
                "task_fp": self.task_fp,
                "evaluator_fp": self.evaluator_fp,
                "init_fp": self.init_fp,
                "data_fp": self.data_fp,
                "seed": self.seed,
                "island_ids": list(self.island_ids),
            },
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, text: str) -> "RunIdentity":
        """Read a stored identity, tolerating a partially written record.

        A run whose record cannot be parsed is not a run whose identity is known,
        so every field comes back empty and the check reports what it could not
        verify rather than pretending the two agree.
        """
        try:
            raw = json.loads(text)
        except (TypeError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        return cls(
            identity_version=int(raw.get("identity_version", 0) or 0),
            schema_version=int(raw.get("schema_version", 0) or 0),
            task_fp=str(raw.get("task_fp", "") or ""),
            evaluator_fp=str(raw.get("evaluator_fp", "") or ""),
            init_fp=str(raw.get("init_fp", "") or ""),
            data_fp=str(raw.get("data_fp", "") or ""),
            seed=int(raw.get("seed", 0) or 0),
            island_ids=tuple(str(i) for i in raw.get("island_ids", ()) or ()),
        )


def _digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def data_fingerprint(task_spec: Any) -> str:
    """Digest of the task's data *descriptors*, or "" when there is none.

    Reads only small descriptor files (``meta.json`` / ``descriptor.json``) beside
    the data, never the dataset: the private split must stay unread and a large
    preparation cannot be re-hashed on every resume. A task with no descriptor
    simply has an unknown fingerprint, which the check reports as unverified.
    """
    task_dir = getattr(task_spec, "task_dir", None)
    if not task_dir:
        return ""
    data_root = Path(task_dir) / "data"
    if not data_root.is_dir():
        return ""
    found: list[tuple[str, str]] = []
    for name in DESCRIPTOR_NAMES:
        for candidate in sorted(data_root.rglob(name)):
            if not candidate.is_file():
                continue
            if any(part in UNREADABLE_DATA_DIRS for part in candidate.parts):
                continue
            try:
                rel = str(candidate.relative_to(data_root)).replace("\\", "/")
                found.append((rel, _digest_text(candidate.read_text(encoding="utf-8"))))
            except (OSError, UnicodeDecodeError):
                continue
    if not found:
        return ""
    return _digest_text(json.dumps(found, sort_keys=True))


def capture_identity(
    task_spec: Any,
    island_ids: Sequence[str],
    *,
    schema_version: int,
    seed: int,
) -> RunIdentity:
    """Describe what this invocation would run, before it runs anything."""
    init_code = str(getattr(task_spec, "init_code", "") or "")
    return RunIdentity(
        identity_version=IDENTITY_VERSION,
        schema_version=int(schema_version),
        task_fp=task_fingerprint(task_spec),
        evaluator_fp=evaluator_fingerprint(task_spec),
        init_fp=_digest_text(init_code) if init_code.strip() else "",
        data_fp=data_fingerprint(task_spec),
        seed=int(seed),
        island_ids=tuple(island_ids),
    )


#: Fields compared for equality. ``seed`` and ``island_ids`` are included because a
#: resumed run that re-rolls the exploration stream or changes the ring is a
#: different experiment even when the task text agrees.
CHECKED_FIELDS = (
    "identity_version",
    "schema_version",
    "task_fp",
    "evaluator_fp",
    "init_fp",
    "data_fp",
    "seed",
    "island_ids",
)

def identity_field_known(name: str, value: Any) -> bool:
    """Whether this field actually describes the run, rather than being absent.

    A value means a claim about the run; the empty string, an empty ring and a zero
    version mean the absence of one, and each field decides for itself what absence
    looks like.
    """
    if name == "seed":
        return True
    if name in ("identity_version", "schema_version"):
        return bool(value)
    if isinstance(value, (tuple, list)):
        return len(value) > 0
    return bool(value)


def known_fields(identity: RunIdentity) -> list[str]:
    """Which of the checked fields this record actually describes."""
    return [
        name for name in CHECKED_FIELDS
        if identity_field_known(name, getattr(identity, name))
    ]


def _render(value: Any) -> str:
    if isinstance(value, (tuple, list)):
        return ",".join(str(v) for v in value) or "(none)"
    return str(value)


def check_identity(stored: RunIdentity, incoming: RunIdentity) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Compare a stored run with the invocation that wants to continue it.

    Returns ``(mismatches, lost)``. A field both sides can describe must agree; a
    field the stored run described and this one cannot is ``lost`` -- the data
    descriptor disappeared, the evaluator file went unreadable -- which is a change
    too, just one this run cannot name. A field the stored run never described is
    simply unverified and gets filled in, because refusing to start would punish an
    old run for the sake of a value it never had.
    """
    mismatches: dict[str, tuple[str, str]] = {}
    lost: list[str] = []
    for name in CHECKED_FIELDS:
        was = getattr(stored, name)
        now = getattr(incoming, name)
        if not identity_field_known(name, was):
            continue
        if not identity_field_known(name, now):
            lost.append(name)
        elif was != now:
            mismatches[name] = (_render(was), _render(now))
    return mismatches, lost


def new_holder_id() -> str:
    """One process's identity for a run claim; two launches never share it."""
    return uuid.uuid4().hex[:12]


def claim_is_live(claim: dict[str, Any] | None, *, current_pid: int | None = None) -> bool:
    """Whether a stored claim names a process that is still running.

    ``current_pid`` makes the question precise: a claim left by this very process
    is not somebody else holding the run -- it is this process starting its second
    engine object, which is how a restart is driven in tests and in a worker that
    rebuilds an engine. Only another *live* process is a competing execution.
    """
    if not claim:
        return False
    pid = claim.get("holder_pid")
    if current_pid is not None and pid == current_pid:
        return False
    alive = pid_alive(pid)
    if alive is None:
        # Unknowable is not "alive": a stale claim must not block a run forever.
        return False
    return bool(alive)


def claim_is_foreign_death(claim: dict[str, Any] | None, *, current_pid: int | None = None) -> bool:
    """Whether the claim was left by a *different* process that is no longer running.

    That and only that is an interrupted run: an attempt that stopped without
    finishing, which the next attempt should say out loud instead of silently
    inheriting.
    """
    if not claim:
        return False
    if current_pid is not None and claim.get("holder_pid") == current_pid:
        return False
    return not claim_is_live(claim, current_pid=current_pid)


def snapshot_rng(rng: random.Random) -> str:
    """Serialise an RNG stream so a resume continues it instead of re-deriving it."""
    version, internal, gauss = rng.getstate()
    return json.dumps([version, list(internal), gauss])


def rng_from_snapshot(payload: str) -> random.Random | None:
    """Rebuild a saved stream, or None when the payload is not one."""
    if not payload:
        return None
    try:
        raw = json.loads(payload)
        version, internal, gauss = raw
        rng = random.Random()
        rng.setstate((int(version), tuple(int(i) for i in internal), gauss))
    except (ValueError, TypeError, AttributeError):
        return None
    return rng


def clone_run_database(src_db: Path, dst_db: Path) -> Path:
    """Copy a run database the way a live SQLite file must be copied.

    A run directory is written in WAL mode, so ``fe.db`` alone is not the run: the
    recent commits sit in ``fe.db-wal``. The backup API reads through the source
    connection, which is what makes the copy one consistent snapshot instead of a
    half-applied file pair, and it leaves the source opened read-only so a resume
    cannot mutate the run it was copied from.
    """
    src_db, dst_db = Path(src_db), Path(dst_db)
    if not src_db.is_file():
        raise FileNotFoundError(f"no run database at {src_db}")
    if dst_db.exists() and dst_db.stat().st_size:
        raise FileExistsError(
            f"{dst_db} already holds a database; refusing to overwrite a run with a copy"
        )
    dst_db.parent.mkdir(parents=True, exist_ok=True)
    uri = src_db.resolve().as_uri() + "?mode=ro"
    source = sqlite3.connect(uri, uri=True, timeout=30.0)
    try:
        target = sqlite3.connect(dst_db)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
    finally:
        source.close()
    return dst_db


#: A file whose name ends like this is a SQLite file, not an artifact: a main
#: database copied by hand is a snapshot of whatever happened to be checkpointed,
#: and its sidecars arriving without their database are just a discrepancy.
_DATABASE_SUFFIXES = (".db", "-wal", "-shm", "-journal")


def copy_run_artifacts(
    src_dir: Path, dst_dir: Path, *, skip_names: Sequence[str] = ()
) -> list[str]:
    """Copy one run's artifacts into a new home and return what moved.

    Only the ordinary files -- ``tree.json``, ``events.jsonl``, ``run_summary.json``,
    the programs and the logs. A database never travels this way: it goes through
    :func:`clone_run_database`, whose backup copy is one consistent snapshot of the
    WAL-including state. A name that already exists in the destination is left
    alone, because the copy is what a resume starts from, not what it overwrites.
    """
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    if not src_dir.is_dir():
        raise FileNotFoundError(f"no run directory at {src_dir}")
    copied: list[str] = []
    for item in sorted(src_dir.iterdir()):
        if item.name.endswith(_DATABASE_SUFFIXES) or item.name in skip_names:
            continue
        target = dst_dir / item.name
        if target.exists():
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
        copied.append(item.name)
    return copied


def clone_run_directory(src_dir: Path, dst_dir: Path, *, db_name: str = "fe.db") -> Path:
    """Copy one run's whole directory into a new home and return the new database.

    Used when a resume must not write on the original: the SQLite file goes through
    :func:`clone_run_database` (WAL-correct), and the artifacts that sit beside it
    are copied as ordinary files because nothing reads them while a run writes them.
    """
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    dst_db = clone_run_database(src_dir / db_name, dst_dir / db_name)
    copy_run_artifacts(src_dir, dst_dir, skip_names=(db_name,))
    return dst_db
def run_claim_summary(claim: dict[str, Any] | None) -> dict[str, Any]:
    """Describe a claim for an event payload without inventing a state."""
    if not claim:
        return {"holder_id": "", "holder_pid": None, "alive": False}
    alive = pid_alive(claim.get("holder_pid"))
    return {
        "holder_id": str(claim.get("holder_id", "")),
        "holder_pid": claim.get("holder_pid"),
        "alive": bool(alive) if alive is not None else False,
        "unknowable": alive is None,
        "claimed_at": str(claim.get("claimed_at", "")),
    }
