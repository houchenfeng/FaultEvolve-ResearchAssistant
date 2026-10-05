"""Redaction of host paths, keys and serials (TODO §2.3 / §17.3).

Applied to everything that is echoed back from disk: log excerpts, event
payloads, error details. Two rules shape the patterns:

* **Prefer over-redaction.** A false positive costs a bland string; a false
  negative publishes a customer path or a live credential.
* **Never redact something the UI needs.** Numbers are only treated as serials
  from 16 digits up, so epoch milliseconds (13) and float fractions survive.

``sanitize`` is pure and returns a report of what it replaced, so tests can
assert on classifications rather than on brittle exact strings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

REDACTED_PATH = "<REDACTED_PATH>"
REDACTED_SECRET = "<REDACTED_SECRET>"
REDACTED_SERIAL = "<REDACTED_SERIAL>"

#: ``C:\Users\...``, ``C:/Users/...`` and UNC ``\\host\share\...``.
_WINDOWS_PATH = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:[A-Za-z]:[\\/][^\s\"'<>|]*"
    r"|\\\\[^\s\"'<>|]+)"
)

#: POSIX absolute paths under directories that actually hold home/data trees.
#: A bare ``/api/runs`` route is *not* matched, so contract text survives.
_POSIX_PATH = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"/(?:home|root|mnt|media|Users|var|opt|srv|etc|tmp)"
    r"(?:/[^\s\"'<>|,;]*)*"
)

#: ``sk-...`` style API keys, plus long base64-ish blobs after a key-ish name.
_API_KEY = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}")
_KEY_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|secret|password)"
    r"(\s*[=:]\s*)([^\s,;\"'}]{4,})"
)

#: Serial numbers: 16+ digits. Epoch millis (13) and fractions stay intact.
_SERIAL = re.compile(r"(?<![0-9A-Za-z])\d{16,}(?![0-9A-Za-z])")


@dataclass
class SanitizationReport:
    """What a :func:`sanitize` call replaced, by category."""

    paths: int = 0
    secrets: int = 0
    serials: int = 0
    #: Human-readable reasons, for the "已脱敏" banner in the UI.
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.paths + self.secrets + self.serials

    def as_dict(self) -> dict[str, Any]:
        return {
            "paths": self.paths,
            "secrets": self.secrets,
            "serials": self.serials,
            "total": self.total,
        }


def sanitize(text: str) -> tuple[str, SanitizationReport]:
    """Redact ``text``; return the cleaned string and a report."""
    report = SanitizationReport()
    if not text:
        return text, report

    out, n = _WINDOWS_PATH.subn(REDACTED_PATH, text)
    report.paths += n
    out, n = _POSIX_PATH.subn(REDACTED_PATH, out)
    report.paths += n

    out, n = _API_KEY.subn(REDACTED_SECRET, out)
    report.secrets += n
    out, n = _KEY_ASSIGNMENT.subn(
        lambda m: f"{m.group(1)}{m.group(2)}{REDACTED_SECRET}", out
    )
    report.secrets += n

    out, n = _SERIAL.subn(REDACTED_SERIAL, out)
    report.serials += n

    if report.paths:
        report.notes.append(f"隐藏了 {report.paths} 处本机路径")
    if report.secrets:
        report.notes.append(f"隐藏了 {report.secrets} 处疑似密钥")
    if report.serials:
        report.notes.append(f"隐藏了 {report.serials} 处疑似序列号")
    return out, report


def sanitize_value(value: Any) -> tuple[Any, SanitizationReport]:
    """Recursively sanitize every string inside a JSON-like structure.

    Keys are sanitized too: a payload key can itself be a path in the engine's
    smoke-data events.
    """
    report = SanitizationReport()

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            cleaned, sub = sanitize(node)
            report.paths += sub.paths
            report.secrets += sub.secrets
            report.serials += sub.serials
            return cleaned
        if isinstance(node, dict):
            return {walk(k): walk(v) for k, v in node.items()}
        if isinstance(node, (list, tuple)):
            return [walk(item) for item in node]
        return node

    cleaned = walk(value)
    report.notes = _merge_notes(report)
    return cleaned, report


def _merge_notes(report: SanitizationReport) -> list[str]:
    notes: list[str] = []
    if report.paths:
        notes.append(f"隐藏了 {report.paths} 处本机路径")
    if report.secrets:
        notes.append(f"隐藏了 {report.secrets} 处疑似密钥")
    if report.serials:
        notes.append(f"隐藏了 {report.serials} 处疑似序列号")
    return notes


def truncate_log(text: str, *, max_chars: int = 4000) -> tuple[str, bool]:
    """Keep only the tail of a log, which is where failures are written.

    Returns ``(text, truncated)``. Truncation happens from the *head* so the
    most recent lines survive.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return f"…（前 {len(text) - max_chars} 字符已省略）\n" + text[-max_chars:], True
