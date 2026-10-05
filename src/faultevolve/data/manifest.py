"""Run bookkeeping for a large data preparation: opaque identity, config hash, resume.

The rules this module exists to enforce come from the streaming requirement - 40 to 130 GB of event
files that cannot be read twice, and output directories that live next to source data. Two of them
shape every function here:

* a source file name may be a real unit identifier, so a manifest identifies inputs by content
  digest and never by name, and an error message quotes at most a count;
* a checkpoint is only true once the bytes it describes were hashed, so every write goes to
  ``.tmp`` first and is renamed after the digest was taken. A crashed run therefore leaves
  recoverable state instead of a plausible-looking lie.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping, Sequence

MANIFEST_VERSION = "runmanifest-v1"
MANIFEST_NAME = "manifest.json"
LOCK_NAME = "writer.lock"
PARTITIONS_DIR = "partitions"
EXIT_CONFIG_CHANGED = 2

#: A key that smells like a credential must not be hashed into a shared manifest: the hash input
#: would then have been a secret somebody pasted into a config file.
_CREDENTIAL_WORDS = r"secret|token|password|passwd|credential|api[_-]?key|access[_-]?key"
_SENSITIVE_KEY = re.compile(_CREDENTIAL_WORDS, re.I)
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")
_PARTITION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_JSON_SCALARS = (str, int, float, bool, type(None))


class ManifestError(ValueError):
    """Raised when a run directory, a config, or a checkpoint cannot be trusted.

    Messages carry counts and shapes only: an input file name or a config value may be a real
    device identifier or a credential.
    """


class ConfigChangedError(ManifestError):
    """The configuration differs from the one that produced this run directory."""

    exit_code = EXIT_CONFIG_CHANGED


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path, *, buffer_size: int = 1 << 20) -> str:
    """Content digest of one file, streamed so a 30 GB file costs 30 GB of streaming, not of RAM."""
    file_path = Path(path)
    if not file_path.is_file():
        raise ManifestError(
            "an input file does not exist; its name is not printed because a file name may be a "
            "unit identifier"
        )
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for block in iter(lambda: handle.read(int(buffer_size)), b""):
            digest.update(block)
    return digest.hexdigest()


def input_digests(paths: Sequence[Path]) -> list[str]:
    """Sorted content digests, which is the only input identity a public manifest may carry."""
    return sorted(sha256_file(path) for path in paths)


def _check_value(key_path: str, value: object) -> object:
    if isinstance(value, Mapping):
        return {str(k): _check_value(f"{key_path}.{k}", v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_check_value(f"{key_path}[{index}]", item) for index, item in enumerate(value)]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ManifestError(
                f"config key {key_path} is not a finite number; JSON would write it as NaN or "
                "Infinity and no later reader could re-hash that reproducibly"
            )
        return value
    raise ManifestError(
        f"config key {key_path} is a {type(value).__name__}; convert it to a string (for example "
        "'5 days') so the hash means the same thing in two environments"
    )


def _guard_public(value: object, *, key: str = "") -> None:
    if _SENSITIVE_KEY.search(key):
        raise ManifestError(
            f"config key looks like a credential; secrets belong in an environment variable, and "
            "hashing one would copy it into a shared manifest"
        )
    if isinstance(value, Mapping):
        for inner_key, inner in value.items():
            _guard_public(inner, key=str(inner_key))
        return
    if isinstance(value, (list, tuple)):
        for inner in value:
            _guard_public(inner, key=key)
        return
    if isinstance(value, str) and _ABSOLUTE_PATH.match(value):
        raise ManifestError(
            f"config value for {key or 'a key'} looks like a filesystem path; a manifest is shared "
            "and must describe the shape of a run, not where somebody keeps their data"
        )


def config_hash(payload: Mapping[str, object], *, algorithm_version: str) -> str:
    """Digest of the canonical JSON form of a config plus the algorithm version that reads it.

    Key order cannot change the value, so two processes that built the same dict differently still
    agree on whether a run directory is reusable.
    """
    if not isinstance(algorithm_version, str) or not algorithm_version:
        raise ManifestError("algorithm_version must be a non-empty string")
    if not isinstance(payload, Mapping):
        raise ManifestError("config must be a mapping of plain JSON values")
    _guard_public(payload)
    checked = {str(key): _check_value(str(key), value) for key, value in payload.items()}
    canonical = json.dumps(checked, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return _digest(f"{MANIFEST_VERSION}\x1f{algorithm_version}\x1f{canonical}")


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True)
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _require_relative_to(root: Path, path: Path, what: str) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ManifestError(f"{what} must live inside the run directory") from exc
    return relative.as_posix()


def check_partition_name(name: str) -> str:
    """Validate an opaque partition name, refusing one that could leave the run directory.

    A writer must call this before it opens a file, because a name that escapes upward would
    otherwise already have been written by the time the checkpoint is attempted.
    """
    text = str(name)
    if not _PARTITION_NAME.match(text) or ".." in Path(text).parts or text.startswith("/"):
        raise ManifestError(
            f"partition name {text!r} is not usable: it must be a relative path made of letters, "
            "digits, dot, underscore and slash, and may not escape the run directory"
        )
    return text


def read_manifest(out_dir: Path) -> dict:
    """Load and validate the run manifest, refusing anything it cannot fully trust."""
    path = Path(out_dir) / MANIFEST_NAME
    if not path.is_file():
        raise ManifestError(
            "the run directory has no manifest; refusing to guess what produced it or overwrite it"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ManifestError(f"the run manifest is unreadable ({type(exc).__name__})") from exc
    if not isinstance(payload, dict):
        raise ManifestError("the run manifest is not a JSON object")
    if payload.get("manifest_version") != MANIFEST_VERSION:
        raise ManifestError(
            f"the run manifest declares {payload.get('manifest_version')!r}, this build writes "
            f"{MANIFEST_VERSION!r}; refusing to mix two checkpoint formats"
        )
    for key in ("config_hash", "algorithm_version", "inputs", "partitions"):
        if key not in payload:
            raise ManifestError(f"the run manifest is missing its {key} section")
    return payload


def _reject_nested(raw_dir: Path, out_dir: Path) -> None:
    raw, out = raw_dir.resolve(), out_dir.resolve()
    if raw == out:
        raise ManifestError(
            "the output directory is the same directory as the raw input; writing there would "
            "put derived files next to data that must stay read-only"
        )
    if out in raw.parents or raw in out.parents:
        raise ManifestError(
            "the output directory is inside the raw input directory (or the reverse); a run must "
            "not be able to read its own derivatives as source data"
        )


def prepare_run(
    out_dir: Path,
    *,
    raw_dir: Path,
    paths: Sequence[Path],
    config: Mapping[str, object],
    algorithm_version: str,
) -> dict:
    """Open (or resume) a run directory, refusing to overwrite a directory this code did not make.

    Returning the existing manifest when nothing changed is what makes a rerun cheap; a changed
    config is an error rather than a silent rebuild, because a half-new half-old partition set
    is the worst possible outcome of a long job.
    """
    out, raw = Path(out_dir), Path(raw_dir)
    _reject_nested(raw, out)
    digest = config_hash(config, algorithm_version=algorithm_version)
    digests = input_digests(list(paths))
    if not digests:
        raise ManifestError("a run needs at least one input file; refusing to create an empty plan")

    manifest_path = out / MANIFEST_NAME
    if manifest_path.is_file():
        existing = read_manifest(out)
        if existing["config_hash"] != digest:
            raise ConfigChangedError(
                "the config differs from the one that produced this run directory; start a new "
                "runtime directory instead of mixing partitions from two configurations"
            )
        if existing["inputs"]["sha256"] != digests:
            raise ManifestError(
                "the input files differ from the ones this run directory was built from; its "
                "partitions describe a different dataset"
            )
        return existing

    if out.exists() and any(out.iterdir()):
        raise ManifestError(
            "the output directory already has files in it but no manifest; refusing to overwrite a "
            "directory this code did not create"
        )

    created = {
        "manifest_version": MANIFEST_VERSION,
        "algorithm_version": algorithm_version,
        "config_hash": digest,
        "inputs": {
            "count": len(digests),
            "sha256": digests,
        },
        "partitions": {},
        "status": "open",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / PARTITIONS_DIR).mkdir(parents=True, exist_ok=True)
    _atomic_write_json(manifest_path, created)
    return created


def finish_partition(
    out_dir: Path, *, name: str, path: Path, rows: int, extra: Mapping[str, object] | None = None
) -> dict:
    """Record a partition as complete, hashing the bytes that were actually written."""
    out = Path(out_dir)
    partition_name = check_partition_name(name)
    file_path = Path(path)
    if not file_path.is_file():
        raise ManifestError(
            "the partition output file does not exist yet; a checkpoint may only describe bytes "
            "that were written"
        )
    relative = _require_relative_to(out, file_path, "a partition output")
    manifest = read_manifest(out)
    entry = {
        "sha256": sha256_file(file_path),
        "bytes": int(file_path.stat().st_size),
        "rows": int(rows),
        "status": "complete",
        "path": relative,
        "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if extra:
        entry.update({str(k): _check_value(f"{partition_name}.{k}", v) for k, v in extra.items()})
    manifest["partitions"][partition_name] = entry
    _atomic_write_json(out / MANIFEST_NAME, manifest)
    return entry


def verify_partitions(out_dir: Path) -> dict:
    """Re-hash every recorded partition so a resume can rebuild one damaged file, not the run."""
    out = Path(out_dir)
    manifest = read_manifest(out)
    ok: list[str] = []
    corrupt: list[str] = []
    missing: list[str] = []
    for name, entry in sorted(manifest["partitions"].items()):
        candidate = out / str(entry.get("path", ""))
        if not candidate.is_file():
            missing.append(name)
        elif sha256_file(candidate) != entry.get("sha256"):
            corrupt.append(name)
        else:
            ok.append(name)
    return {"ok": ok, "corrupt": corrupt, "missing": missing}


def plan_resume(
    out_dir: Path,
    *,
    paths: Sequence[Path],
    config: Mapping[str, object],
    algorithm_version: str,
) -> dict:
    """Decide what a rerun may reuse, and say why it cannot reuse the rest.

    Order matters: a config change is a different experiment (exit code 2, nothing is reused), an
    input change invalidates every partition, and damaged output invalidates only its own partition.
    """
    manifest = read_manifest(out_dir)
    recorded = sorted(manifest["partitions"])
    if manifest["config_hash"] != config_hash(config, algorithm_version=algorithm_version):
        raise ConfigChangedError(
            "the config differs from the one that produced this run directory; start a new "
            "runtime directory instead of mixing partitions from two configurations"
        )
    if manifest["inputs"]["sha256"] != input_digests(list(paths)):
        return {"reuse": [], "rebuild": recorded, "reason": "inputs"}
    checked = verify_partitions(out_dir)
    rebuild = sorted(checked["corrupt"] + checked["missing"])
    reason = "outputs" if rebuild else None
    reuse = sorted(set(recorded) - set(rebuild))
    return {"reuse": reuse, "rebuild": rebuild, "reason": reason}


@contextmanager
def writer_lock(out_dir: Path, *, owner: str) -> Iterator[None]:
    """One coordinator at a time per run directory; parallel workers write their own temp files.

    A lock is claimed with O_EXCL, so two processes cannot both create it. The lock is removed on a
    clean exit; a killed process leaves it behind on purpose, because guessing that a dead writer
    finished its rename is exactly how a corrupted partition gets marked complete.
    """
    out = Path(out_dir)
    if not str(owner):
        raise ManifestError("a writer lock needs an owner label")
    path = out / LOCK_NAME
    try:
        handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ManifestError(
            "another writer holds this run directory; only one coordinator may finalize it, so "
            "start the second run in its own runtime directory"
        ) from exc
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(str(owner))
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


__all__ = [
    "EXIT_CONFIG_CHANGED",
    "MANIFEST_NAME",
    "MANIFEST_VERSION",
    "PARTITIONS_DIR",
    "ConfigChangedError",
    "ManifestError",
    "check_partition_name",
    "config_hash",
    "finish_partition",
    "input_digests",
    "plan_resume",
    "prepare_run",
    "read_manifest",
    "sha256_file",
    "verify_partitions",
    "writer_lock",
]

