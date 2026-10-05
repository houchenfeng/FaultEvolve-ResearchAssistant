"""Code validation utilities for generated candidates.

Reuses rules from the task evaluator's static_check when available.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path
from typing import Callable


FORBIDDEN_PATTERNS = {
    "evaluator-only path": r"eval_only|holdout|val_labels|test_labels",
    "path climbing": r"\.parent\b|\.\./|\.\.\\|os\.pardir|\bparents\[",
    "directory listing": r"\blistdir\b|os\.walk|\bglob\b|\bscandir\b|\biterdir\b|rglob",
    "working-directory access": r"getcwd|Path\.cwd|\bchdir\b",
    "process/network escape": r"\bsubprocess\b|os\.system|\bsocket\b|urllib|requests\b|http\.client",
}


def syntax_check(code: str) -> str:
    """Check if code is valid Python syntax.

    Returns empty string if valid, error message otherwise.
    """
    try:
        ast.parse(code)
        return ""
    except SyntaxError as e:
        return f"syntax error at line {e.lineno}: {e.msg}"


def pattern_check(code: str) -> str:
    """Check code against forbidden patterns.

    Returns empty string if valid, error message otherwise.
    """
    for lineno, line in enumerate(code.splitlines(), 1):
        code_part = line.split("#", 1)[0]
        for reason, pat in FORBIDDEN_PATTERNS.items():
            if re.search(pat, code_part):
                return f"{reason} (line {lineno}): {code_part.strip()[:120]}"
    return ""


def load_evaluator_static_check(evaluator_path: Path) -> Callable[[str], str] | None:
    """Load the static_check function from an evaluator module.

    Returns None if the evaluator doesn't have a static_check function.
    """
    if not evaluator_path.exists():
        return None

    try:
        spec = importlib.util.spec_from_file_location("evaluator", evaluator_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, "static_check"):
            return module.static_check
    except Exception:
        pass
    return None


def full_check(code: str, evaluator_path: Path | None = None) -> str:
    """Run all code checks.

    Args:
        code: Source code to check
        evaluator_path: Path to evaluator.py for additional static checks

    Returns:
        Empty string if all checks pass, error message otherwise.
    """
    err = syntax_check(code)
    if err:
        return err

    err = pattern_check(code)
    if err:
        return err

    if evaluator_path is not None:
        static_check = load_evaluator_static_check(evaluator_path)
        if static_check is not None:
            err = static_check(code)
            if err:
                return err

    return ""


def extract_code_from_response(response: str) -> str | None:
    """Extract Python code block from LLM response.

    Looks for ```python ... ``` blocks.
    Returns None if no code block found.
    """
    import re as regex_module

    pattern = r"```python\s*\n(.*?)```"
    matches = regex_module.findall(pattern, response, regex_module.DOTALL)
    if matches:
        return matches[-1].strip()
    return None


def extract_intent_from_response(response: str) -> str:
    """Extract intent block from LLM response.

    Looks for <intent>...</intent> tags.
    Returns empty string if not found.
    """
    import re as regex_module

    pattern = r"<intent>\s*(.*?)\s*</intent>"
    match = regex_module.search(pattern, response, regex_module.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def extract_hypothesis_from_response(response: str) -> str:
    """Extract hypothesis block from LLM response.

    Looks for <hypothesis>...</hypothesis> tags.
    Returns empty string if not found.
    """
    import re as regex_module

    pattern = r"<hypothesis>\s*(.*?)\s*</hypothesis>"
    match = regex_module.search(pattern, response, regex_module.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def extract_adopted_cards_from_response(response: str) -> list[str]:
    """Extract adopted card IDs from LLM response.

    Looks for <adopted_cards>ID1,ID2,...</adopted_cards> tags.
    Handles various formats robustly:
    - Empty tag means no cards adopted
    - Missing tag means no cards adopted
    - Whitespace and comma-separated IDs

    Returns:
        List of card IDs (empty list if none adopted)
    """
    import re as regex_module

    pattern = r"<adopted_cards>\s*(.*?)\s*</adopted_cards>"
    match = regex_module.search(pattern, response, regex_module.DOTALL | regex_module.IGNORECASE)

    if not match:
        return []

    content = match.group(1).strip()
    if not content:
        return []

    ids = []
    for part in content.split(","):
        card_id = part.strip()
        if card_id:
            ids.append(card_id)

    return ids
