"""Text processing utilities for FaultEvolve."""

from __future__ import annotations

import difflib
import hashlib
import re


def truncate_text(text: str, max_chars: int = 4000, suffix: str = "\n... [truncated]") -> str:
    """Truncate text to max_chars, adding suffix if truncated."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - len(suffix)] + suffix


def tail_text(text: str, max_chars: int = 800, prefix: str = "... [truncated]\n") -> str:
    """Keep the last max_chars of text (traceback tails)."""
    if len(text) <= max_chars:
        return text
    keep = max(1, max_chars - len(prefix))
    return prefix + text[-keep:]


def compute_code_hash(code: str) -> str:
    """Compute a hash of normalized code for deduplication."""
    normalized = re.sub(r"\s+", " ", code.strip())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def unified_diff(old_code: str, new_code: str, max_chars: int = 6000) -> str:
    """Generate a unified diff between two code strings.

    Returns truncated diff if it exceeds max_chars.
    """
    old_lines = old_code.splitlines(keepends=True)
    new_lines = new_code.splitlines(keepends=True)

    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
    diff_text = "".join(diff)

    return truncate_text(diff_text, max_chars)


def sanitize_error_info(
    error_info: str,
    max_chars: int = 500,
    *,
    keep_tail: bool = False,
) -> str:
    """Sanitize error info by removing sensitive data.

    - Truncates to max_chars (head by default; tail when keep_tail=True)
    - Replaces absolute paths with <path>
    - Replaces serial-number-like strings with <id>
    """
    if keep_tail:
        text = tail_text(error_info, max_chars=max_chars)
    elif len(error_info) > max_chars:
        text = error_info[:max_chars]
    else:
        text = error_info

    text = re.sub(r"(/[^\s:]+)+", "<path>", text)

    text = re.sub(r"\b[A-Z0-9]{8,}\b", "<id>", text)

    return text


def format_metric_summary(metric: dict) -> str:
    """Format metrics into a readable summary string."""
    if not metric:
        return ""

    parts = []
    key_order = ["f1", "f1_p10", "auprc", "recall_at_far", "false_alarm_rate", "run_time_s"]

    for key in key_order:
        if key in metric:
            val = metric[key]
            if isinstance(val, float):
                if key == "false_alarm_rate":
                    parts.append(f"{key}={val:.4f}")
                else:
                    parts.append(f"{key}={val:.3f}")
            else:
                parts.append(f"{key}={val}")

    return " ".join(parts)


def extract_json_from_response(response: str) -> str | None:
    """Extract JSON block from LLM response.

    Looks for ```json ... ``` blocks or raw JSON objects/arrays.
    Returns None if no valid JSON found.
    """
    json_pattern = r"```json\s*\n(.*?)```"
    match = re.search(json_pattern, response, re.DOTALL)
    if match:
        return match.group(1).strip()

    obj_pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
    match = re.search(obj_pattern, response, re.DOTALL)
    if match:
        return match.group(0)

    return None


def vendor_from_model(model_name: str) -> str:
    """Extract vendor prefix from disk model name."""
    prefixes = ["ST", "TOSHIBA", "HGST", "WDC"]
    for prefix in prefixes:
        if model_name.upper().startswith(prefix):
            return prefix
    return "OTHER"
