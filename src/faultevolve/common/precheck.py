"""Pre-evaluation static checks and auto-rewrites.

Catches common API compatibility issues before evaluation and fixes them
where safe, avoiding wasted eval time on trivially fixable errors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PrecheckResult:
    """Result of pre-evaluation check."""
    original_code: str
    fixed_code: str
    fixes_applied: list[str] = field(default_factory=list)
    unfixable_issues: list[str] = field(default_factory=list)

    @property
    def was_fixed(self) -> bool:
        return len(self.fixes_applied) > 0

    @property
    def has_unfixable(self) -> bool:
        return len(self.unfixable_issues) > 0


PANDAS_FILLNA_METHOD = re.compile(
    r"\.fillna\s*\(\s*method\s*=\s*['\"]?(ffill|bfill|pad|backfill)['\"]?\s*\)",
    re.IGNORECASE
)

PANDAS_FILLNA_METHOD_POSITIONAL = re.compile(
    r"\.fillna\s*\(\s*['\"]?(ffill|bfill|pad|backfill)['\"]?\s*\)",
    re.IGNORECASE
)

SERIAL_LOOP = re.compile(
    r"for\s+\w+\s+in\s+\w+\[?['\"]?serial_number['\"]?\]?\.unique\(\)",
    re.IGNORECASE
)

GROUPBY_APPLY_LAMBDA = re.compile(
    r"\.groupby\s*\([^)]*\)\s*\.apply\s*\(\s*lambda",
    re.IGNORECASE
)

DATA_DIR_UNDERSCORE = re.compile(
    r"add_argument\s*\(\s*['\"]--data_dir['\"]",
)


def fix_fillna_method(code: str) -> tuple[str, list[str]]:
    """Fix pandas fillna(method=...) to .ffill()/.bfill().

    Args:
        code: Source code

    Returns:
        Tuple of (fixed_code, list of fix descriptions)
    """
    fixes = []

    def replace_fillna(match: re.Match) -> str:
        method = match.group(1).lower()
        if method in ("ffill", "pad"):
            fixes.append(f"fillna(method='{method}') -> ffill()")
            return ".ffill()"
        elif method in ("bfill", "backfill"):
            fixes.append(f"fillna(method='{method}') -> bfill()")
            return ".bfill()"
        return match.group(0)

    code = PANDAS_FILLNA_METHOD.sub(replace_fillna, code)
    code = PANDAS_FILLNA_METHOD_POSITIONAL.sub(replace_fillna, code)

    return code, fixes


def fix_lgb_kwargs(code: str) -> tuple[str, list[str]]:
    """Remove verbose_eval and early_stopping_rounds from LightGBM calls.

    Handles comma placement correctly to avoid syntax errors like f(, x=1).

    Args:
        code: Source code

    Returns:
        Tuple of (fixed_code, list of fix descriptions)
    """
    fixes = []

    verbose_pattern = re.compile(
        r",\s*verbose_eval\s*=\s*[^,\)]+|verbose_eval\s*=\s*[^,\)]+\s*,?",
        re.IGNORECASE
    )
    early_stop_pattern = re.compile(
        r",\s*early_stopping_rounds\s*=\s*\d+|early_stopping_rounds\s*=\s*\d+\s*,?",
        re.IGNORECASE
    )

    if verbose_pattern.search(code):
        code = verbose_pattern.sub("", code)
        fixes.append("removed verbose_eval (use callbacks=[lgb.log_evaluation()])")

    if early_stop_pattern.search(code):
        code = early_stop_pattern.sub("", code)
        fixes.append("removed early_stopping_rounds (use callbacks=[lgb.early_stopping()])")

    opening_comma = re.compile(r"\(\s*,")
    code = opening_comma.sub("(", code)

    return code, fixes


def fix_data_dir_arg(code: str) -> tuple[str, list[str]]:
    """Fix --data_dir to --data-dir in argparse.

    The harness requires --data-dir (with hyphen), not --data_dir.

    Args:
        code: Source code

    Returns:
        Tuple of (fixed_code, list of fix descriptions)
    """
    fixes = []

    if DATA_DIR_UNDERSCORE.search(code):
        code = re.sub(
            r"(add_argument\s*\(\s*['\"])--data_dir(['\"])",
            r"\1--data-dir\2",
            code
        )
        fixes.append("fixed --data_dir to --data-dir (harness requirement)")

    return code, fixes


EARLY_STOPPING_CALLBACK = re.compile(
    r"lgb\.early_stopping\s*\(|early_stopping\s*\(",
    re.IGNORECASE
)

EVAL_SET_PATTERN = re.compile(
    r"eval_set\s*=|valid_sets\s*=",
    re.IGNORECASE
)


def check_performance_issues(code: str) -> list[str]:
    """Check for patterns that cause timeout (>900s).

    These are not auto-fixed but flagged as warnings.

    Args:
        code: Source code

    Returns:
        List of issues found
    """
    issues = []

    if SERIAL_LOOP.search(code):
        issues.append(
            "for-loop over serial_number.unique() detected - will timeout on 12M rows. "
            "Use vectorized groupby().agg()/transform() instead."
        )

    if GROUPBY_APPLY_LAMBDA.search(code):
        issues.append(
            "groupby().apply(lambda) detected - very slow on large data. "
            "Use groupby().agg()/transform()/rolling() for vectorized operations."
        )

    return issues


def fix_early_stopping_without_eval_set(code: str) -> tuple[str, list[str]]:
    """Remove early_stopping callback when no eval_set/valid_sets is provided.

    LightGBM requires at least one evaluation dataset for early stopping.
    Without it, the error 'For early stopping, at least one dataset...' occurs.

    Args:
        code: Source code

    Returns:
        Tuple of (fixed_code, list of fix descriptions)
    """
    fixes = []

    if EARLY_STOPPING_CALLBACK.search(code) and not EVAL_SET_PATTERN.search(code):
        callback_pattern = re.compile(
            r"lgb\.early_stopping\s*\([^)]*\)\s*,?\s*|"
            r"early_stopping\s*\([^)]*\)\s*,?\s*",
            re.IGNORECASE
        )
        code = callback_pattern.sub("", code)

        callbacks_pattern = re.compile(r"callbacks\s*=\s*\[\s*\]")
        code = callbacks_pattern.sub("", code)

        opening_comma = re.compile(r"\(\s*,")
        code = opening_comma.sub("(", code)
        trailing_comma = re.compile(r",\s*\)")
        code = trailing_comma.sub(")", code)

        fixes.append(
            "removed early_stopping callback (requires eval_set/valid_sets; "
            "add validation data or remove the callback)"
        )

    return code, fixes


def precheck_and_fix(code: str) -> PrecheckResult:
    """Run all prechecks and apply safe fixes.

    Args:
        code: Source code to check

    Returns:
        PrecheckResult with fixed code and details
    """
    original = code
    all_fixes: list[str] = []
    all_issues: list[str] = []

    code, fixes = fix_fillna_method(code)
    all_fixes.extend(fixes)

    code, fixes = fix_lgb_kwargs(code)
    all_fixes.extend(fixes)

    code, fixes = fix_data_dir_arg(code)
    all_fixes.extend(fixes)

    code, fixes = fix_early_stopping_without_eval_set(code)
    all_fixes.extend(fixes)

    issues = check_performance_issues(code)
    all_issues.extend(issues)

    return PrecheckResult(
        original_code=original,
        fixed_code=code,
        fixes_applied=all_fixes,
        unfixable_issues=all_issues,
    )


def is_api_compat_error(error_info: str) -> bool:
    """Check if an error is an API compatibility error.

    These errors should not penalize knowledge cards since they're
    not caused by the card's advice but by outdated API usage.

    Args:
        error_info: Error traceback/message

    Returns:
        True if this is an API compat error
    """
    if not error_info:
        return False

    error_lower = error_info.lower()

    api_patterns = [
        "unexpected keyword argument",
        "got an unexpected keyword argument",
        "fillna() got an unexpected keyword argument 'method'",
        "verbose_eval",
        "early_stopping_rounds",
    ]

    for pattern in api_patterns:
        if pattern in error_lower:
            return True

    if "typeerror" in error_lower and "keyword argument" in error_lower:
        return True

    return False


def is_timeout_error(error_info: str) -> bool:
    """Check if an error is a timeout.

    Args:
        error_info: Error traceback/message

    Returns:
        True if this is a timeout error
    """
    if not error_info:
        return False

    error_lower = error_info.lower()
    return "timeout" in error_lower or "timed out" in error_lower


ERROR_FIX_MAPPING = {
    "fillna": {
        "pattern": r"fillna\(\).*unexpected keyword argument.*method",
        "description": "pandas>=2 不支持 fillna(method=...)",
        "fix": "使用 df.ffill() 或 df.bfill() 代替 df.fillna(method='ffill'/'bfill')",
    },
    "verbose_eval": {
        "pattern": r"(train|fit)\(\).*unexpected keyword argument.*verbose_eval",
        "description": "LightGBM>=4 不支持 verbose_eval 参数",
        "fix": "删除 verbose_eval 参数，改用 callbacks=[lgb.log_evaluation(period=0)]",
    },
    "early_stopping_rounds": {
        "pattern": r"(train|fit)\(\).*unexpected keyword argument.*early_stopping_rounds",
        "description": "LightGBM>=4 不支持 early_stopping_rounds 参数",
        "fix": "删除 early_stopping_rounds 参数，改用 callbacks=[lgb.early_stopping(stopping_rounds=N)]",
    },
    "keyerror_serial": {
        "pattern": r"KeyError.*serial_number|serial_number.*KeyError",
        "description": "聚合后丢失了 serial_number 列",
        "fix": "聚合前保留 key 列：groupby(..., as_index=False) 或聚合后 .reset_index()",
    },
    "columns_overlap": {
        "pattern": r"columns overlap|duplicate column",
        "description": "DataFrame 合并时列名重复",
        "fix": "使用 join(..., rsuffix='_y') 或合并前 drop 重复列",
    },
    "length_mismatch": {
        "pattern": r"length.*mismatch|cannot reindex|length of values.*does not match",
        "description": "数组长度不匹配",
        "fix": "使用 merge(on='serial_number') 代替直接赋值数组",
    },
    "object_dtype": {
        "pattern": r"could not convert.*to.*numeric|invalid literal for|cannot convert",
        "description": "object 类型无法转换为数值",
        "fix": "使用 pd.to_numeric(df[col], errors='coerce') 处理非数值",
    },
    "np_series": {
        "pattern": r"numpy.*has no attribute.*Series|module.*numpy.*Series",
        "description": "np.Series 不存在",
        "fix": "使用 pd.Series 而非 np.Series",
    },
    "ambiguous_truth": {
        "pattern": r"truth value of a Series is ambiguous|ambiguous.*array.*truth",
        "description": "Series 的布尔值判断是歧义的",
        "fix": "使用 .any() 或 .all() 代替直接 if series",
    },
    "timeout": {
        "pattern": r"timeout|timed out|exceeded.*time",
        "description": "评估超时（可能是 for-loop 或 groupby().apply()）",
        "fix": "使用向量化操作：groupby().agg()/transform()/rolling()，禁止 for-loop over serial_number.unique()",
    },
    "early_stopping_no_eval": {
        "pattern": r"For early stopping.*at least one dataset|early stopping.*eval.*required",
        "description": "early_stopping callback 需要验证集",
        "fix": "添加 eval_set=[(X_val, y_val)] 或 valid_sets=[valid_set]，或删除 early_stopping callback",
    },
    "multiindex_keyerror": {
        "pattern": r"KeyError.*MultiIndex|MultiIndex.*KeyError",
        "description": "MultiIndex 导致的 KeyError",
        "fix": "使用 .reset_index() 将 MultiIndex 转为普通列，或使用 .loc[(level1, level2)]",
    },
    "grouper_length": {
        "pattern": r"Grouper and axis must be same length",
        "description": "groupby 的 key 长度与数据不匹配",
        "fix": "确保 groupby 的 key 来自同一个 DataFrame，使用 df.groupby(df['col']) 而非外部变量",
    },
    "column_not_found": {
        "pattern": r"Column.*not found|KeyError.*(?!serial_number)",
        "description": "列名不存在",
        "fix": "使用 df.columns 检查可用列，不要发明不存在的列名",
    },
    "ndarray_values": {
        "pattern": r"ndarray.*has no attribute.*values|'numpy.ndarray'.*'values'",
        "description": "ndarray 没有 .values 属性",
        "fix": "ndarray 本身就是数组，不需要 .values；DataFrame/Series 才有 .values",
    },
    "set_indexer": {
        "pattern": r"unhashable type.*set|set.*as.*indexer",
        "description": "set 不能用作索引",
        "fix": "使用 list(your_set) 或 df[[col1, col2]] 代替 df[{col1, col2}]",
    },
    "syntax_paren": {
        "pattern": r"SyntaxError.*\(|unexpected EOF|unmatched.*paren",
        "description": "括号不匹配的语法错误",
        "fix": "检查所有括号是否匹配，特别是多行表达式",
    },
}


def get_error_fix_hint(error_info: str) -> str:
    """Get specific fix hint for a known error pattern.

    Args:
        error_info: Error traceback/message

    Returns:
        Fix hint string, or empty string if no known fix
    """
    if not error_info:
        return ""

    hints = []
    for name, mapping in ERROR_FIX_MAPPING.items():
        if re.search(mapping["pattern"], error_info, re.IGNORECASE):
            hints.append(f"**{mapping['description']}**\n修复方法：{mapping['fix']}")

    return "\n\n".join(hints)
