"""HDD-specific task adapter.

This adapter extends the generic Famou adapter with HDD-specific
noise delta calculation using f1_boot_std and task constraints.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

from faultevolve.tasks.famou_adapter import FamouAdapter
from faultevolve.tasks.protocol import DataStatus, DiscoveryFrames, EvalResult, TaskSpec


HDD_FORBIDDEN_TOKENS = [
    "eval_only", "holdout", "val_labels", "test_labels",
    "'../'", "'..\\\\'" , ".parent", "parents[", "os.pardir",
    "listdir", "glob", "os.walk", "iterdir", "scandir", "rglob",
    "getcwd", "Path.cwd", "chdir",
    "subprocess", "os.system", "socket", "urllib", "requests", "http.client",
]

HDD_CONSTRAINTS_TEMPLATE = """以下是硬盘故障预测任务的硬约束，违反任何一条都会导致分数为 0：

1. **静态检查禁止的关键词**：以下词汇不能出现在代码中（注释 # 后除外，但 docstring 和字符串中也不行）：
   {forbidden_tokens}

2. **路径约束**：只能使用 os.path.join(args.data_dir, filename) 来构建数据路径，不能使用相对路径或目录遍历。

3. **运行时间**：总运行时间应控制在 300 秒以内（超过 600 秒会导致 time_factor 惩罚，超过 900 秒会超时失败）。
   - 使用 groupby().agg() 代替 groupby().apply()
   - 避免逐盘的 Python 循环，使用向量化操作

4. **允许的依赖**：只能使用 pandas、numpy、sklearn、lightgbm、scipy。"""

HDD_API_NOTES = """## 禁止的 API 用法（违反会导致运行时错误）

### Pandas >= 2.0 禁止用法
❌ **禁止**: `df.fillna(method='ffill')` 或 `df.fillna(method='bfill')`
✅ **改用**: `df.ffill()` 或 `df.bfill()`

❌ **禁止**: `df[{col1, col2}]`（set 索引）
✅ **改用**: `df[[col1, col2]]` 或 `df[list(cols)]`

### LightGBM >= 4.0 禁止用法
❌ **禁止**: `lgb.train(..., verbose_eval=...)` 或 `model.fit(..., verbose_eval=...)`
❌ **禁止**: `lgb.train(..., early_stopping_rounds=...)` 或 `model.fit(..., early_stopping_rounds=...)`
⚠️ **重要**: `lgb.early_stopping()` callback **必须**配合 `eval_set` 或 `valid_sets` 使用！
   - 没有验证集时会报错："For early stopping, at least one dataset and eval metric is required"
✅ **正确用法**:
```python
# 方法 1：使用验证集
callbacks = [lgb.early_stopping(stopping_rounds=50), lgb.log_evaluation(period=0)]
model.fit(X, y, eval_set=[(X_val, y_val)], callbacks=callbacks)

# 方法 2：不用 early_stopping（无验证集时）
model.fit(X, y)  # 不要传 early_stopping callback
```

### 程序入口（CLI 不可修改）
⚠️ **重要**: 保持 init.py 的 CLI 接口不变，必须使用 `--data-dir`、`--split`、`--out`
❌ **禁止**: 修改或删除 argparse 定义
❌ **禁止**: 使用 `--data_dir`（下划线），必须是 `--data-dir`（连字符）
✅ **正确**: 通过 `args.data_dir` 获取路径（argparse 自动转换连字符为下划线）

### 超时风险（会导致 900s 超时）
❌ **禁止**: `for sn in df['serial_number'].unique():` — 12M 行会超时
❌ **禁止**: `df.groupby(...).apply(lambda ...)` — 非常慢
✅ **改用**: 向量化操作 `groupby().agg()`、`groupby().transform()`、`rolling()`

### 类型转换
- object 列传入 LightGBM 前需转为 int 或 category：`df[cols].astype('category')`

### 运行时间
- 使用 3-fold CV，LightGBM 树数量 ≤300
- 目标运行时间：< 300 秒（超过会被惩罚）"""


HDD_DATA_SCHEMA = """## 数据 Schema（不要发明不存在的列！）

### train_history.csv / val_history.csv 列
**关键列**：`serial_number`（硬盘序列号）、`date`（日期）
**特征列**：
- 基本信息：`model`、`capacity_bytes`
- SMART raw 值：`smart_1_raw`, `smart_3_raw`, `smart_4_raw`, `smart_5_raw`, `smart_7_raw`, 
  `smart_9_raw`, `smart_10_raw`, `smart_12_raw`, `smart_187_raw`, `smart_188_raw`, 
  `smart_190_raw`, `smart_191_raw`, `smart_192_raw`, `smart_193_raw`, `smart_194_raw`, 
  `smart_196_raw`, `smart_197_raw`, `smart_198_raw`, `smart_199_raw`, `smart_240_raw`, 
  `smart_241_raw`, `smart_242_raw`
- SMART normalized 值：`smart_1_normalized`, `smart_3_normalized`, `smart_5_normalized`, 
  `smart_7_normalized`, `smart_9_normalized`, `smart_187_normalized`, `smart_194_normalized`, 
  `smart_197_normalized`, `smart_198_normalized`

### train_labels.csv 列
`serial_number`, `model`, `cutoff_date`, `label`, `weight`

### val_index.csv 列
`serial_number`, `model`, `cutoff_date`

### 严禁
❌ **不要发明不存在的列名**（如 smart_195_raw、model_te 等不存在）
❌ **不要假设有其他列**（只使用上述列名）"""


def build_history_contract(
    history: "pd.DataFrame",
    unit_col: str,
    time_col: str,
) -> tuple[str, dict]:
    """Describe the *actual* ``history`` frame handed to ``feature(history)``.

    ``HDD_DATA_SCHEMA`` documents the raw CSV files, which is not the same
    thing: the discovery frame is built by ``discovery_frames()`` from a fixed
    column subset, so ``model`` / ``capacity_bytes`` are absent and ``date`` is
    still a string.  Handing the LLM only the raw-CSV description let it write
    code against a frame that does not exist (Run B: KeyError on a column that
    is not there, and ``median`` over a string column).

    Returns ``(prompt_text, json_dict)``.
    """
    cols = [str(c) for c in history.columns]
    dtypes = {str(c): str(history[c].dtype) for c in history.columns}
    numeric = [c for c in cols if pd.api.types.is_numeric_dtype(history[c])]
    non_numeric = [c for c in cols if c not in numeric]
    try:
        per_unit_max = int(history.groupby(unit_col).size().max()) if len(history) else 0
    except (KeyError, ValueError, TypeError):
        per_unit_max = 0
    labels_only = [
        c for c in ("model", "capacity_bytes", "cutoff_date", "label", "weight")
        if c not in cols
    ]

    def _fmt(names: list[str]) -> str:
        return ", ".join(f"`{n}`" for n in names) if names else "（无）"

    example_col = numeric[0] if numeric else "smart_5_raw"
    text = f"""

## history 帧契约（**权威定义，请严格按此写 feature_code**）

**上面那段描述的是原始 CSV；`feature(history)` 拿到的是下面这个加工过的帧，以本段为准。**

- `history` 是**长面板**：每一行是一次 **(硬盘, 日期) 采样**，不是"每块硬盘一行"。
  每块硬盘最多 {per_unit_max} 行。
- `history.columns` 只有这些，**不要使用表里没有的列**：
  - 列：{_fmt(cols)}
  - dtype：{", ".join(f"`{c}`={dtypes[c]}" for c in cols)}
- **数值列**（可参与 `max/min/mean/median/sum`）：{_fmt(numeric)}
- **非数值列**（**绝不能**参与数值约简）：{_fmt(non_numeric)}
- **不在 `history` 里的列**（只存在于 labels / 原始 CSV）：{_fmt(labels_only)}
- 返回契约：`feature` 必须返回 `pandas.Series`，**index 是字符串形式的 `{unit_col}`**，
  覆盖率 ≥ 80%，且不能是常量序列。
- 禁止：对整帧调用 `.median()/.mean()/.sum()`（会撞上非数值列）；
  使用上表以外的列名；读写文件。

正确写法（先选列/先按单元聚合，再返回以 `{unit_col}` 为索引的 Series）：

```python
def feature(history):
    return history.groupby("{unit_col}")["{example_col}"].max()
```
"""
    contract = {
        "frame": "history",
        "rows": int(len(history)),
        "columns": cols,
        "dtypes": dtypes,
        "numeric_columns": numeric,
        "non_numeric_columns": non_numeric,
        "absent_columns": labels_only,
        "rows_per_unit_max": per_unit_max,
        "unit_col": unit_col,
        "time_col": time_col,
        "contract": {
            "signature": "def feature(history) -> pandas.Series",
            "index": f"string {unit_col}",
            "min_coverage": 0.8,
            "constant_series_rejected": True,
        },
    }
    return text, contract


HDD_K0_COLUMNS = (
    "smart_5_raw",
    "smart_9_raw",
    "smart_12_raw",
    "smart_187_raw",
    "smart_188_raw",
    "smart_194_raw",
    "smart_197_raw",
    "smart_198_raw",
    "smart_199_raw",
)

# History feature columns declared in HDD_DATA_SCHEMA (excluding serial_number/date).
HDD_DISCOVERY_EXTRA_COLUMNS = (
    "model",
    "capacity_bytes",
    "smart_1_raw",
    "smart_3_raw",
    "smart_4_raw",
    "smart_5_raw",
    "smart_7_raw",
    "smart_9_raw",
    "smart_10_raw",
    "smart_12_raw",
    "smart_187_raw",
    "smart_188_raw",
    "smart_190_raw",
    "smart_191_raw",
    "smart_192_raw",
    "smart_193_raw",
    "smart_194_raw",
    "smart_196_raw",
    "smart_197_raw",
    "smart_198_raw",
    "smart_199_raw",
    "smart_240_raw",
    "smart_241_raw",
    "smart_242_raw",
    "smart_1_normalized",
    "smart_3_normalized",
    "smart_5_normalized",
    "smart_7_normalized",
    "smart_9_normalized",
    "smart_187_normalized",
    "smart_194_normalized",
    "smart_197_normalized",
    "smart_198_normalized",
)


def _dedupe_columns(*groups: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for col in group:
            if col not in seen:
                seen.add(col)
                out.append(col)
    return tuple(out)


HDD_DISCOVERY_COLUMNS = _dedupe_columns(
    ("serial_number", "date"),
    HDD_K0_COLUMNS,
    HDD_DISCOVERY_EXTRA_COLUMNS,
)

#: Columns a factor's ``inputs`` may name.  The disk identifier is excluded on
#: purpose -- it identifies a unit, it is not a signal a factor may read.
#: ``faultevolve.discovery`` must stay task-agnostic, so the loader takes this
#: list as an argument (``allowed_columns=``) instead of importing it.
HDD_DISCOVERY_INPUT_COLUMNS = tuple(col for col in HDD_DISCOVERY_COLUMNS if col != "serial_number")


def _discovery_schema_note(history_columns: list[str], tail_rows: int) -> str:
    cols = list(history_columns)
    id_cols = [c for c in ("serial_number", "date") if c in cols]
    basic = [c for c in ("model", "capacity_bytes") if c in cols]
    raw_cols = [c for c in cols if c.endswith("_raw")]
    norm_cols = [c for c in cols if c.endswith("_normalized")]
    listed = set(id_cols + basic + raw_cols + norm_cols)
    other = [c for c in cols if c not in listed]
    lines = [
        f"history 每序列多行（最近约 {tail_rows} 行，date <= cutoff），只含以下列，不要使用其他列：",
    ]
    if id_cols:
        lines.append(f"标识/时间: {', '.join(id_cols)}")
    if basic:
        lines.append(f"基本信息: {', '.join(basic)}")
    if raw_cols:
        lines.append(f"SMART raw: {', '.join(raw_cols)}")
    if norm_cols:
        lines.append(f"SMART normalized: {', '.join(norm_cols)}")
    if other:
        lines.append(f"其他: {', '.join(other)}")
    lines.append("labels 仅 serial_number, label（不在 history 中）。")
    note = "\n".join(lines)
    if len(note) > 1500:
        return note[:1497] + "..."
    return note


SILENT_SMART_COLS = ("smart_5_raw", "smart_187_raw", "smart_197_raw", "smart_198_raw")
TB = 1024**4

HDD_OBJECTIVE_BRIEF = """ROS = 100 × (0.5×F1_p10 + 0.3×AUPRC + 0.2×R@FAR) × time_factor。
三项质量分量在 ROS 上的近似边际收益约为：F1_p10 +0.01 → +0.5 分，AUPRC +0.01 → +0.3 分，R@FAR +0.01 → +0.2 分。
R@FAR 仅在 0.2% 误报率预算内优化召回；负样本权重约 10，机队正例率约 0.25%（推算）。
若做概率校准，F1 最优阈值常落在 F1*/2 附近。
下方聚合错例画像仅作 dev 集改进线索，勿针对单一分组过拟合。"""

HDD_EDIT_GUIDANCE = """## 代码修改指南

### 最小编辑原则
- **优先做最小必要修改**，每次修改控制在 ~60 行以内
- **不要重写整个文件**，只修改需要改的部分
- 保持原有的代码结构和辅助函数

### 辅助函数
- **保持现有辅助函数的签名不变**，除非同时更新所有调用者
- 如果需要修改函数签名，确保所有调用点都更新

### 常见错误
- 不要删除必要的 import 语句
- 不要删除 argparse 定义
- 确保所有括号匹配
- 检查 groupby 后是否需要 reset_index()"""


class HDDAdapter(FamouAdapter):
    """Adapter for HDD failure prediction tasks.

    Extends FamouAdapter with HDD-specific noise delta calculation
    based on the bootstrap standard deviation of F1 score.
    """

    F1_TO_ROS_FACTOR = 50.0
    DEFAULT_KAPPA = 1.0

    def __init__(
        self,
        min_noise_delta: float = 0.5,
        kappa: float = DEFAULT_KAPPA,
        dev_late_fraction: float = 0.4,
        analysis_min_group_count: int = 10,
    ) -> None:
        """Initialize the HDD adapter.

        Args:
            min_noise_delta: Minimum noise delta threshold
            kappa: Multiplier for bootstrap std in delta calculation
            dev_late_fraction: Fraction of latest cutoff dates used as dev queries
            analysis_min_group_count: Minimum count to emit an error group
        """
        super().__init__(min_noise_delta=min_noise_delta)
        self.kappa = kappa
        self.dev_late_fraction = dev_late_fraction
        self.analysis_min_group_count = analysis_min_group_count
        self._cached_constraints: str | None = None
        self._analysis_data_dir: Path | None = None
        self._analysis_labels: pd.DataFrame | None = None
        self._analysis_features: pd.DataFrame | None = None
        self._discovery_cache: Any | None = None

    def cleanup_discovery_data(self) -> None:
        self._discovery_cache = None

    def get_noise_delta(self, eval_result: EvalResult) -> float:
        """Calculate noise delta from f1_boot_std.

        delta = kappa * f1_boot_std * 50 (converting F1 scale to ROS scale)
        The factor 50 comes from 0.5 * 100 in the ROS formula.

        Falls back to min_noise_delta if f1_boot_std is not available
        or is too small.
        """
        f1_boot_std = eval_result.metric.get("f1_boot_std", 0.0)

        if f1_boot_std <= 0:
            return self.min_noise_delta

        delta = self.kappa * f1_boot_std * self.F1_TO_ROS_FACTOR
        return max(delta, self.min_noise_delta)

    def objectives(self) -> list[str]:
        return ["auprc", "recall_at_far"]

    def threshold_objectives(self) -> list[str]:
        return ["f1_p10"]

    def noise_metric(self) -> str:
        return "f1_boot_std"

    def _extract_forbidden_tokens_from_evaluator(self, evaluator_path: Path) -> list[str]:
        """Try to extract forbidden tokens from evaluator.py at runtime.

        Returns the default list if extraction fails.
        """
        if not evaluator_path.exists():
            return HDD_FORBIDDEN_TOKENS

        try:
            content = evaluator_path.read_text(encoding="utf-8")
            pattern = r'FORBIDDEN_PATTERNS\s*=\s*\{([^}]+)\}'
            match = re.search(pattern, content, re.DOTALL)
            if match:
                patterns_text = match.group(1)
                token_pattern = r'r["\']([^"\']+)["\']'
                tokens = []
                for m in re.finditer(token_pattern, patterns_text):
                    regex_str = m.group(1)
                    readable_tokens = self._regex_to_readable_tokens(regex_str)
                    tokens.extend(readable_tokens)
                if tokens:
                    return list(set(tokens))
        except Exception:
            pass

        return HDD_FORBIDDEN_TOKENS

    def _regex_to_readable_tokens(self, regex_str: str) -> list[str]:
        """Convert regex pattern to human-readable tokens."""
        tokens = []
        simple_tokens = regex_str.replace(r"\b", "").replace(r"\.", ".").split("|")
        for t in simple_tokens:
            t = t.strip()
            if t and not t.startswith("(") and not t.endswith("?"):
                t = t.replace("\\", "")
                if t:
                    tokens.append(t)
        return tokens

    def constraints(self, task_spec: TaskSpec) -> str:
        """Get HDD-specific constraints to inject into prompts.

        Extracts forbidden tokens from evaluator.py if possible,
        otherwise uses the hardcoded list.
        """
        if self._cached_constraints is not None:
            return self._cached_constraints

        forbidden = self._extract_forbidden_tokens_from_evaluator(task_spec.evaluator_path)
        token_list = ", ".join(f"`{t}`" for t in sorted(set(forbidden)))

        self._cached_constraints = HDD_CONSTRAINTS_TEMPLATE.format(
            forbidden_tokens=token_list
        )
        return self._cached_constraints

    def context_keywords(self, code: str) -> list[str]:
        """Extract HDD-specific keywords from code for knowledge retrieval.

        Extracts SMART attribute names (smart_5, smart_187, etc.) and
        other domain-specific patterns for matching knowledge cards.

        Args:
            code: Current solution code

        Returns:
            List of keywords for knowledge card matching
        """
        keywords = []

        smart_pattern = r"smart_(\d+)"
        for match in re.finditer(smart_pattern, code, re.IGNORECASE):
            keywords.append(f"smart_{match.group(1)}")

        model_patterns = [
            (r"LightGBM|lightgbm|lgb\.", "lightgbm"),
            (r"LogisticRegression|logistic", "logistic"),
            (r"RandomForest|ExtraTrees", "random_forest"),
            (r"XGBoost|xgboost|xgb\.", "xgboost"),
            (r"CatBoost|catboost", "catboost"),
        ]
        for pat, kw in model_patterns:
            if re.search(pat, code, re.IGNORECASE):
                keywords.append(kw)
                keywords.append("model")

        if re.search(r"delta|diff|change|slope|trend", code, re.IGNORECASE):
            keywords.extend(["delta", "trend"])

        if re.search(r"threshold|alarm", code, re.IGNORECASE):
            keywords.append("threshold")

        if re.search(r"vendor|model", code, re.IGNORECASE):
            keywords.append("vendor")

        if re.search(r"weight|sample_weight|class_weight", code, re.IGNORECASE):
            keywords.append("class_weight")

        if re.search(r"fillna|NaN|missing", code, re.IGNORECASE):
            keywords.append("missing_values")

        if re.search(r"f1|precision|recall|auprc", code, re.IGNORECASE):
            keywords.append("evaluation")

        if re.search(r"groupby|pivot", code, re.IGNORECASE):
            keywords.append("feature_engineering")

        if re.search(r"oof|cross_val|KFold", code, re.IGNORECASE):
            keywords.append("cv")

        return list(set(keywords))

    def api_notes(self) -> str:
        """Get HDD-specific library API notes.

        Returns notes about common API pitfalls for LightGBM, pandas, etc.
        """
        return HDD_API_NOTES

    def data_schema(self) -> str:
        """Get HDD data schema for prompt injection.

        Helps LLM understand available columns and avoid inventing columns.
        """
        return HDD_DATA_SCHEMA

    def edit_guidance(self) -> str:
        """Get edit guidance for minimal changes.

        Encourages minimal edits instead of full file rewrites.
        """
        return HDD_EDIT_GUIDANCE

    def _get_data_dir(self, task_spec: TaskSpec) -> Path:
        """Get the data directory for the task."""
        data_root = os.environ.get("HDD_BENCH_DATA_ROOT")
        if data_root:
            return Path(data_root) / "public"
        task_data = task_spec.task_dir / "data" / "public"
        if task_data.exists():
            return task_data
        return task_spec.task_dir / "data"

    def data_status(self, task_dir: Path) -> DataStatus:
        """Check public split files exist (existence only, no file reads)."""
        task_dir = task_dir.resolve()
        task_spec = TaskSpec(
            task_dir=task_dir,
            problem_md="",
            prompt_md="",
            init_code="",
            evaluator_path=task_dir / "evaluator.py",
        )
        data_dir = self._get_data_dir(task_spec)
        required = [
            "train_history.csv.gz",
            "train_labels.csv",
            "val_history.csv.gz",
            "val_index.csv",
        ]
        missing = [name for name in required if not (data_dir / name).exists()]
        ok = not missing
        message = f"data dir {data_dir}"
        if missing:
            message += f"; missing: {missing}"
            prepare = task_dir / "prepare_data.py"
            if prepare.exists():
                message += f"; run: python {prepare} --help"
        env_val = os.environ.get("HDD_BENCH_DATA_ROOT")
        if env_val:
            message += f" (HDD_BENCH_DATA_ROOT={env_val})"
        return DataStatus(
            ok=ok,
            data_dir=str(data_dir),
            missing=missing,
            message=message,
        )

    def objective_brief(self, task_spec: TaskSpec) -> str:
        """Evaluator-aware ROS trade-off summary for generation prompts."""
        return HDD_OBJECTIVE_BRIEF

    def cleanup_analysis_data(self) -> None:
        """Remove cached dev-split temp directory and in-memory analysis tables."""
        if self._analysis_data_dir is not None and self._analysis_data_dir.exists():
            shutil.rmtree(self._analysis_data_dir, ignore_errors=True)
        self._analysis_data_dir = None
        self._analysis_labels = None
        self._analysis_features = None

    @staticmethod
    def _capacity_bucket(capacity_bytes: float) -> str:
        tb = float(capacity_bytes) / TB
        if tb < 6:
            return "<6TB"
        if tb < 10:
            return "6-<10TB"
        if tb < 14:
            return "10-<14TB"
        return ">=14TB"

    @staticmethod
    def _vendor_prefix(model: str) -> str:
        token = str(model).split("_")[0].split()[0]
        return token[:3] if len(token) >= 3 else token

    @staticmethod
    def _row_is_silent(row: pd.Series) -> bool:
        for col in SILENT_SMART_COLS:
            if col not in row.index:
                return True
            val = row[col]
            if pd.isna(val) or float(val) != 0.0:
                return False
        return True

    def _build_analysis_data(self, task_spec: TaskSpec) -> tuple[Path, pd.DataFrame, pd.DataFrame]:
        if (
            self._analysis_data_dir is not None
            and self._analysis_labels is not None
            and self._analysis_features is not None
        ):
            return self._analysis_data_dir, self._analysis_labels, self._analysis_features

        data_dir = self._get_data_dir(task_spec)
        labels_path = data_dir / "train_labels.csv"
        history_path = data_dir / "train_history.csv.gz"
        if not labels_path.exists() or not history_path.exists():
            raise FileNotFoundError("public train_labels.csv or train_history.csv.gz not found")

        labels = pd.read_csv(labels_path)
        required = {"serial_number", "model", "cutoff_date", "label", "weight"}
        if not required.issubset(labels.columns):
            raise ValueError(f"train_labels missing columns: {required - set(labels.columns)}")

        dates = sorted(labels["cutoff_date"].unique())
        if len(dates) < 2:
            raise ValueError("need at least two distinct cutoff_date values for dev split")
        split_idx = max(1, min(len(dates) - 1, int(round((1 - self.dev_late_fraction) * len(dates)))))
        early_dates = set(dates[:split_idx])
        late_dates = set(dates[split_idx:])
        if not early_dates or not late_dates:
            raise ValueError("empty early or late cutoff partition")

        early_labels = labels[labels["cutoff_date"].isin(early_dates)].copy()
        late_labels = labels[labels["cutoff_date"].isin(late_dates)].copy()
        if early_labels.empty or late_labels.empty:
            raise ValueError("empty early or late label partition")

        analysis_dir = Path(tempfile.mkdtemp(prefix="fe_analysis_"))
        early_serials = set(early_labels["serial_number"])
        late_serials = set(late_labels["serial_number"])

        early_labels.to_csv(analysis_dir / "train_labels.csv", index=False)
        late_index = late_labels[["serial_number", "model", "cutoff_date"]]
        late_index.to_csv(analysis_dir / "val_index.csv", index=False)

        def _stream_history(out_path: Path, serials: set[str]) -> None:
            first_chunk = True
            with gzip.open(history_path, "rt", encoding="utf-8") as src:
                reader = pd.read_csv(src, chunksize=200_000)
                with gzip.open(out_path, "wt", encoding="utf-8", newline="") as dst:
                    for chunk in reader:
                        filtered = chunk[chunk["serial_number"].isin(serials)]
                        if filtered.empty:
                            continue
                        filtered.to_csv(dst, index=False, header=first_chunk)
                        first_chunk = False

        _stream_history(analysis_dir / "train_history.csv.gz", early_serials)
        _stream_history(analysis_dir / "val_history.csv.gz", late_serials)

        feature_rows: list[dict[str, Any]] = []
        late_lookup = late_labels.set_index("serial_number")
        with gzip.open(history_path, "rt", encoding="utf-8") as src:
            for chunk in pd.read_csv(src, chunksize=200_000):
                chunk = chunk[chunk["serial_number"].isin(late_serials)]
                if chunk.empty:
                    continue
                for serial, grp in chunk.groupby("serial_number"):
                    if serial not in late_lookup.index:
                        continue
                    cutoff = late_lookup.at[serial, "cutoff_date"]
                    model = late_lookup.at[serial, "model"]
                    before = grp[grp["date"] <= cutoff]
                    if before.empty:
                        row = grp.iloc[-1]
                    else:
                        row = before.sort_values("date").iloc[-1]
                    cap = row.get("capacity_bytes", np.nan)
                    feature_rows.append({
                        "serial_number": serial,
                        "vendor_prefix": self._vendor_prefix(model),
                        "model": str(model),
                        "capacity_bucket": self._capacity_bucket(cap) if pd.notna(cap) else "unknown",
                        "silent": self._row_is_silent(row),
                    })

        features = pd.DataFrame(feature_rows).drop_duplicates(subset=["serial_number"])
        self._analysis_data_dir = analysis_dir
        self._analysis_labels = late_labels
        self._analysis_features = features
        return analysis_dir, late_labels, features

    def _weighted_confusion(
        self, y: np.ndarray, alarm: np.ndarray, w: np.ndarray,
    ) -> tuple[float, float, float, float]:
        tp = float(np.sum(w * (y == 1) * (alarm == 1)))
        fp = float(np.sum(w * (y == 0) * (alarm == 1)))
        fn = float(np.sum(w * (y == 1) * (alarm == 0)))
        tn = float(np.sum(w * (y == 0) * (alarm == 0)))
        return tp, fp, fn, tn

    def _top_groups(
        self,
        merged: pd.DataFrame,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float | None, str]:
        notes: list[str] = []
        failure_cols = ("days_to_failure", "failure_date", "fail_date")
        has_failure_date = any(c in merged.columns for c in failure_cols)

        fn_mask = (merged["label"] == 1) & (merged["alarm"] == 0)
        fp_mask = (merged["label"] == 0) & (merged["alarm"] == 1)
        total_fn = int(fn_mask.sum())
        total_fp = int(fp_mask.sum())
        silent_share: float | None = None
        if total_fn > 0 and "silent" in merged.columns:
            silent_n = int(merged.loc[fn_mask, "silent"].sum())
            silent_share = silent_n / total_fn

        if not has_failure_date:
            notes.append("days_to_failure grouping skipped: no failure date columns in labels")

        fn_groups: list[dict[str, Any]] = []
        fp_groups: list[dict[str, Any]] = []
        dimensions: list[tuple[str, str]] = [
            ("vendor_prefix", "vendor_prefix"),
            ("model", "model"),
            ("capacity_bucket", "capacity_bucket"),
            ("silent", "silent_label"),
        ]
        work = merged.copy()
        work["silent_label"] = work["silent"].map({True: "yes", False: "no"}) if "silent" in work.columns else "no"

        for dimension, col in dimensions:
            if col not in work.columns:
                continue
            for value in work[col].dropna().unique():
                sub = work[work[col] == value]
                y = sub["label"].to_numpy(dtype=int)
                alarm = sub["alarm"].to_numpy(dtype=int)
                w = sub["weight"].to_numpy(dtype=float)
                tp, fp, fn, _tn = self._weighted_confusion(y, alarm, w)

                n_fn = int(((y == 1) & (alarm == 0)).sum())
                if n_fn >= self.analysis_min_group_count:
                    denom = tp + fn
                    fn_groups.append({
                        "dimension": dimension,
                        "value": str(value),
                        "n": n_fn,
                        "share": n_fn / total_fn if total_fn else 0.0,
                        "group_recall": tp / denom if denom > 0 else 0.0,
                    })

                n_fp = int(((y == 0) & (alarm == 1)).sum())
                w_fp = float(np.sum(w[(y == 0) & (alarm == 1)]))
                if n_fp >= self.analysis_min_group_count:
                    neg_w = float(np.sum(w[y == 0]))
                    fp_groups.append({
                        "dimension": dimension,
                        "value": str(value),
                        "n": n_fp,
                        "weighted_n": w_fp,
                        "share": n_fp / total_fp if total_fp else 0.0,
                        "group_far": w_fp / neg_w if neg_w > 0 else 0.0,
                    })

        fn_groups.sort(key=lambda g: (-g["n"], g["dimension"], g["value"]))
        fp_groups.sort(key=lambda g: (-g["weighted_n"], g["dimension"], g["value"]))
        return fn_groups[:5], fp_groups[:5], silent_share, "; ".join(notes)

    def analyze(self, code: str, task_spec: TaskSpec, timeout: int) -> dict[str, Any]:
        dev_dir, late_labels, features = self._build_analysis_data(task_spec)
        candidate_path = ""
        out_path = Path()
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8",
            ) as f:
                f.write(code)
                candidate_path = f.name
            out_path = Path(tempfile.mktemp(suffix=".csv"))

            cmd = [
                sys.executable, candidate_path,
                "--data-dir", str(dev_dir),
                "--split", "val",
                "--out", str(out_path),
            ]
            proc = subprocess.run(
                cmd,
                timeout=timeout,
                cwd=task_spec.task_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                raise ValueError(f"analysis subprocess exit code {proc.returncode}")

            if not out_path.exists():
                raise ValueError("analysis output file not created")

            pred = pd.read_csv(out_path)
            required_cols = {"serial_number", "score", "alarm"}
            if set(pred.columns) != required_cols:
                raise ValueError(f"output columns must be exactly {required_cols}")

            expected = late_labels["serial_number"].astype(str)
            pred_serials = pred["serial_number"].astype(str)
            if pred_serials.duplicated().any():
                raise ValueError("duplicate serial_number in predictions")
            expected_set = set(expected)
            pred_set = set(pred_serials)
            if pred_set != expected_set:
                raise ValueError("serial_number set mismatch vs dev val_index")

            if not np.isfinite(pred["score"].to_numpy(dtype=float)).all():
                raise ValueError("non-finite score values")
            if not pred["alarm"].isin([0, 1]).all():
                raise ValueError("alarm must be 0 or 1")

            merged = late_labels.merge(pred, on="serial_number", how="left")
            feat_cols = features.drop(columns=["model"], errors="ignore")
            merged = merged.merge(feat_cols, on="serial_number", how="left")
            y = merged["label"].to_numpy(dtype=int)
            alarm = merged["alarm"].to_numpy(dtype=int)
            w = merged["weight"].to_numpy(dtype=float)
            tp, fp, fn, tn = self._weighted_confusion(y, alarm, w)
            precision = tp / (tp + fp) if tp + fp > 0 else 0.0
            recall = tp / (tp + fn) if tp + fn > 0 else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0
            neg_w = float(np.sum(w[y == 0]))
            false_alarm_rate = fp / neg_w if neg_w > 0 else 0.0

            fn_groups, fp_groups, silent_share, notes = self._top_groups(merged)

            return {
                "dev_metrics": {
                    "precision": precision,
                    "recall": recall,
                    "f1": f1,
                    "false_alarm_rate": false_alarm_rate,
                    "n_positive": float(np.sum(w[y == 1])),
                    "n_negative_weighted": neg_w,
                },
                "fn_groups": fn_groups,
                "fp_groups": fp_groups,
                "silent_share": silent_share,
                "notes": notes,
            }
        finally:
            if candidate_path:
                Path(candidate_path).unlink(missing_ok=True)
            if out_path and out_path.exists():
                out_path.unlink(missing_ok=True)

    def build_smoke_data_dir(
        self,
        task_spec: TaskSpec,
        sample_fraction: float = 0.02,
        min_positives: int = 20,
        seed: int = 20260926,
        cache_dir: Path | None = None,
    ) -> Path | None:
        """Build a small sampled data directory for smoke testing.

        Creates a temp directory with ~sample_fraction of serial_numbers.
        Caps positives at sample_fraction worth of total disks (min min_positives),
        then samples ~10 negatives per sampled positive to achieve ~2-3% total.

        Args:
            task_spec: Task specification
            sample_fraction: Fraction of serials to sample (default 0.02 = 2%)
            min_positives: Minimum number of positive samples to keep
            seed: Random seed for reproducibility
            cache_dir: Directory to cache the sampled data (optional)

        Returns:
            Path to the sampled data directory, or None if data files not found
            or on error
        """
        data_dir = self._get_data_dir(task_spec)

        if cache_dir and (cache_dir / "smoke_data" / "_ready").exists():
            return cache_dir / "smoke_data"

        train_labels_path = data_dir / "train_labels.csv"
        val_index_path = data_dir / "val_index.csv"
        if not train_labels_path.exists() or not val_index_path.exists():
            return None

        try:
            train_labels = pd.read_csv(train_labels_path)
            val_index = pd.read_csv(val_index_path)

            positive_serials = set(train_labels[train_labels["label"] == 1]["serial_number"])
            all_train_serials = set(train_labels["serial_number"])
            all_val_serials = set(val_index["serial_number"])

            negative_serials = list(all_train_serials - positive_serials)
            positive_serials_list = list(positive_serials)

            rng = np.random.default_rng(seed)

            total_train = len(all_train_serials)
            negatives_ratio = 10
            total_sample_target = int(total_train * sample_fraction)
            max_positives = max(min_positives, total_sample_target // (1 + negatives_ratio))
            n_positives = min(len(positive_serials_list), max_positives)

            if n_positives < len(positive_serials_list):
                sampled_positives = set(rng.choice(
                    positive_serials_list, size=n_positives, replace=False
                ))
            else:
                sampled_positives = positive_serials
                n_positives = len(sampled_positives)

            n_negatives = min(n_positives * negatives_ratio, len(negative_serials))
            sampled_negatives = set(rng.choice(
                negative_serials, size=n_negatives, replace=False
            ))
            sampled_train_serials = sampled_positives | sampled_negatives

            n_val = max(int(len(all_val_serials) * sample_fraction), 50)
            n_val = min(n_val, len(all_val_serials))
            sampled_val_serials = set(rng.choice(
                list(all_val_serials), size=n_val, replace=False
            ))

            if cache_dir:
                smoke_dir = cache_dir / "smoke_data"
            else:
                smoke_dir = Path(tempfile.mkdtemp(prefix="fe_smoke_"))

            smoke_dir.mkdir(parents=True, exist_ok=True)

            sampled_train_labels = train_labels[
                train_labels["serial_number"].isin(sampled_train_serials)
            ]
            sampled_train_labels.to_csv(smoke_dir / "train_labels.csv", index=False)

            sampled_val_index = val_index[
                val_index["serial_number"].isin(sampled_val_serials)
            ]
            sampled_val_index.to_csv(smoke_dir / "val_index.csv", index=False)

            train_history_path = data_dir / "train_history.csv.gz"
            if train_history_path.exists():
                with gzip.open(train_history_path, "rt", encoding="utf-8") as f:
                    header = f.readline()
                    chunks = []
                    for line in f:
                        serial = line.split(",")[1]
                        if serial in sampled_train_serials:
                            chunks.append(line)

                with gzip.open(smoke_dir / "train_history.csv.gz", "wt", encoding="utf-8") as f:
                    f.write(header)
                    f.writelines(chunks)

            val_history_path = data_dir / "val_history.csv.gz"
            if val_history_path.exists():
                with gzip.open(val_history_path, "rt", encoding="utf-8") as f:
                    header = f.readline()
                    chunks = []
                    for line in f:
                        serial = line.split(",")[1]
                        if serial in sampled_val_serials:
                            chunks.append(line)

                with gzip.open(smoke_dir / "val_history.csv.gz", "wt", encoding="utf-8") as f:
                    f.write(header)
                    f.writelines(chunks)

            (smoke_dir / "_ready").touch()

            return smoke_dir

        except Exception as e:
            logger.warning("Failed to build smoke data dir: %s", e)
            return None

    def smoke_test(
        self,
        code: str,
        task_spec: TaskSpec,
        timeout: int = 60,
        sample_fraction: float = 0.02,
        smoke_data_dir: Path | None = None,
    ) -> EvalResult:
        """Run smoke test on a small data sample.

        Args:
            code: Candidate code to test
            task_spec: Task specification
            timeout: Timeout in seconds
            sample_fraction: Fraction of data to sample
            smoke_data_dir: Pre-built smoke data directory (optional)

        Returns:
            EvalResult with validity=1 if smoke passes, 0 otherwise
        """
        if smoke_data_dir is None:
            smoke_data_dir = self.build_smoke_data_dir(
                task_spec, sample_fraction=sample_fraction
            )
            if smoke_data_dir is None:
                return super().smoke_test(code, task_spec, timeout=timeout)
            cleanup_dir = smoke_data_dir
        else:
            cleanup_dir = None

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            candidate_path = f.name

        out_path = Path(tempfile.mktemp(suffix=".csv"))

        try:
            cmd = [
                sys.executable, candidate_path,
                "--data-dir", str(smoke_data_dir),
                "--split", "val",
                "--out", str(out_path),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=task_spec.task_dir,
            )

            if result.returncode != 0:
                error_info = result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr
                return EvalResult(
                    validity=0.0,
                    combined_score=0.0,
                    cost_time=0.0,
                    error_info=f"Smoke test exit code {result.returncode}:\n{error_info}",
                    metric={},
                )

            if not out_path.exists():
                return EvalResult(
                    validity=0.0,
                    combined_score=0.0,
                    cost_time=0.0,
                    error_info="Smoke test: output file not created",
                    metric={},
                )

            try:
                pred = pd.read_csv(out_path)
                required_cols = {"serial_number", "score", "alarm"}
                if not required_cols.issubset(set(pred.columns)):
                    missing = required_cols - set(pred.columns)
                    return EvalResult(
                        validity=0.0,
                        combined_score=0.0,
                        cost_time=0.0,
                        error_info=f"Smoke test: missing columns {missing}",
                        metric={},
                    )

                val_index = pd.read_csv(smoke_data_dir / "val_index.csv")
                expected_serials = set(val_index["serial_number"])
                pred_serials = set(pred["serial_number"])

                if not expected_serials.issubset(pred_serials):
                    missing_count = len(expected_serials - pred_serials)
                    return EvalResult(
                        validity=0.0,
                        combined_score=0.0,
                        cost_time=0.0,
                        error_info=f"Smoke test: missing {missing_count} serial_numbers in output",
                        metric={},
                    )

            except Exception as e:
                return EvalResult(
                    validity=0.0,
                    combined_score=0.0,
                    cost_time=0.0,
                    error_info=f"Smoke test: invalid output format: {e}",
                    metric={},
                )

            return EvalResult(
                validity=1.0,
                combined_score=0.0,
                cost_time=0.0,
                error_info="",
                metric={"smoke_passed": True},
            )

        except subprocess.TimeoutExpired:
            return EvalResult(
                validity=0.0,
                combined_score=0.0,
                cost_time=float(timeout),
                error_info=f"Smoke test timeout after {timeout}s (likely perf issue)",
                metric={},
            )
        except Exception as e:
            return EvalResult(
                validity=0.0,
                combined_score=0.0,
                cost_time=0.0,
                error_info=f"Smoke test error: {e}",
                metric={},
            )
        finally:
            Path(candidate_path).unlink(missing_ok=True)
            out_path.unlink(missing_ok=True)
            if cleanup_dir and cleanup_dir.exists():
                shutil.rmtree(cleanup_dir, ignore_errors=True)

    def cleanup_smoke_data(self, smoke_dir: Path) -> None:
        """Clean up the smoke data directory."""
        if smoke_dir and smoke_dir.exists():
            shutil.rmtree(smoke_dir, ignore_errors=True)

    def discovery_input_columns(self) -> tuple[str, ...]:
        """Columns an HDD factor may read; see ``HDD_DISCOVERY_INPUT_COLUMNS``."""
        return HDD_DISCOVERY_INPUT_COLUMNS

    def factor_mock_feature(self) -> tuple[str, str]:
        """Offline stand-in proposal: the last ``smart_3_raw`` value per disk."""
        code = (
            "import pandas as pd\n\n"
            "def feature(history):\n"
            "    return history.groupby('serial_number')['smart_3_raw'].last().astype(float)\n"
        )
        return code, "mock smart_3_raw last"

    def discovery_frames(self, task_spec: TaskSpec) -> DiscoveryFrames:
        if self._discovery_cache is not None:
            return self._discovery_cache
        data_dir = self._get_data_dir(task_spec)
        labels_path = data_dir / "train_labels.csv"
        history_path = data_dir / "train_history.csv.gz"
        if not labels_path.exists() or not history_path.exists():
            raise FileNotFoundError("train_labels.csv or train_history.csv.gz missing")
        labels = pd.read_csv(labels_path)
        labels = labels.drop_duplicates(subset=["serial_number"], keep="last")
        serials = set(labels["serial_number"])
        cutoff_map = labels.set_index("serial_number")["cutoff_date"].to_dict()
        meta_path = data_dir.parent / "meta.json"
        history_days = 14
        if meta_path.exists():
            with meta_path.open(encoding="utf-8") as mf:
                history_days = int(json.load(mf).get("history_days", 14))
        lag_rows = 14
        tail_rows = max(int(history_days), lag_rows + 1) + 1
        with gzip.open(history_path, "rt", encoding="utf-8") as src:
            header = src.readline()
        header_cols = header.strip().split(",")
        numeric_cols = [c for c in HDD_K0_COLUMNS if c in header_cols]
        usecols = [c for c in HDD_DISCOVERY_COLUMNS if c in header_cols]
        chunks: list[pd.DataFrame] = []
        with gzip.open(history_path, "rt", encoding="utf-8") as src:
            for chunk in pd.read_csv(src, usecols=usecols, chunksize=200_000):
                chunk = chunk[chunk["serial_number"].isin(serials)]
                if chunk.empty:
                    continue
                cut = chunk["serial_number"].map(cutoff_map)
                cut = cut.fillna(chunk["date"])
                chunk = chunk[chunk["date"] <= cut]
                if "model" in chunk.columns:
                    chunk["model"] = chunk["model"].astype(str).fillna("")
                numeric_history_cols = [
                    c for c in chunk.columns if c not in ("serial_number", "date", "model")
                ]
                for col in numeric_history_cols:
                    chunk[col] = pd.to_numeric(chunk[col], errors="coerce")
                chunks.append(chunk)
        history = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=usecols)
        if not history.empty:
            history = history.sort_values(["serial_number", "date"])
            history = (
                history.groupby("serial_number", sort=False)
                .tail(tail_rows)
                .reset_index(drop=True)
            )
        if "smart_187_raw" in history.columns and not history.empty:
            censor_map = history.groupby("serial_number")["smart_187_raw"].max().gt(0)
        else:
            censor_map = pd.Series(dtype=bool)
        models = labels["model"].astype(str) if "model" in labels.columns else pd.Series("", index=labels.index)
        families = models.str.split().str[0]
        families = families.where(models.str.len() > 0, "unknown").fillna("unknown")
        cutoffs = labels["cutoff_date"].astype(str)
        quarters = cutoffs.where(cutoffs.str.len() < 7, cutoffs.str[:7])
        censor_vals = labels["serial_number"].map(censor_map).fillna(False).astype(int)
        env_frame = pd.DataFrame(
            {
                "env": families + "|" + quarters,
                "conf": families,
                "time": cutoffs,
                "censor": censor_vals,
            }
        )
        _contract_text, contract_json = build_history_contract(
            history, "serial_number", "date",
        )
        frames = DiscoveryFrames(
            labels=labels[["serial_number", "label"]],
            history=history,
            unit_col="serial_number",
            time_col="date",
            label_col="label",
            baseline_cols=numeric_cols,
            # schema_note 保留本地实现：由真实列推导，且被
            # tests/test_hdd_discovery_frames.py 双向锁住（每条真实列都要出现，
            # 长度 <= 1500）。服务端那套契约文字（contract_text）不拼进来，避免
            # 顶破长度预算；它的机器可读部分作为 history_schema 一并带上，由
            # pipeline.py 写成 <artifacts>/discovery/history_schema.json。
            schema_note=_discovery_schema_note(list(history.columns), tail_rows),
            history_schema=contract_json,
            env_frame=env_frame,
        )
        self._discovery_cache = frames
        return frames

    def discovery_frames_val(self, task_spec: TaskSpec) -> DiscoveryFrames:
        """Public val history + eval_only labels (explicit transfer only; not discovery default)."""
        data_dir = self._get_data_dir(task_spec)
        labels_path = data_dir / "eval_only" / "val_labels.csv"
        history_path = data_dir / "val_history.csv.gz"
        if not labels_path.exists() or not history_path.exists():
            raise FileNotFoundError("val_labels or val_history.csv.gz missing")
        labels = pd.read_csv(labels_path)
        labels = labels.drop_duplicates(subset=["serial_number"], keep="last")
        serials = set(labels["serial_number"])
        cutoff_map = (
            labels.set_index("serial_number")["cutoff_date"].to_dict()
            if "cutoff_date" in labels.columns
            else {}
        )
        meta_path = data_dir.parent / "meta.json"
        history_days = 14
        if meta_path.exists():
            with meta_path.open(encoding="utf-8") as mf:
                history_days = int(json.load(mf).get("history_days", 14))
        lag_rows = 14
        tail_rows = max(int(history_days), lag_rows + 1) + 1
        with gzip.open(history_path, "rt", encoding="utf-8") as src:
            header = src.readline()
        header_cols = header.strip().split(",")
        numeric_cols = [c for c in HDD_K0_COLUMNS if c in header_cols]
        usecols = [c for c in HDD_DISCOVERY_COLUMNS if c in header_cols]
        chunks: list[pd.DataFrame] = []
        with gzip.open(history_path, "rt", encoding="utf-8") as src:
            for chunk in pd.read_csv(src, usecols=usecols, chunksize=200_000):
                chunk = chunk[chunk["serial_number"].isin(serials)]
                if chunk.empty:
                    continue
                if cutoff_map:
                    cut = chunk["serial_number"].map(cutoff_map)
                    cut = cut.fillna(chunk["date"])
                    chunk = chunk[chunk["date"] <= cut]
                if "model" in chunk.columns:
                    chunk["model"] = chunk["model"].astype(str).fillna("")
                numeric_history_cols = [
                    c for c in chunk.columns if c not in ("serial_number", "date", "model")
                ]
                for col in numeric_history_cols:
                    chunk[col] = pd.to_numeric(chunk[col], errors="coerce")
                chunks.append(chunk)
        history = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=usecols)
        if not history.empty:
            history = history.sort_values(["serial_number", "date"])
            history = (
                history.groupby("serial_number", sort=False)
                .tail(tail_rows)
                .reset_index(drop=True)
            )
        if "smart_187_raw" in history.columns and not history.empty:
            censor_map = history.groupby("serial_number")["smart_187_raw"].max().gt(0)
        else:
            censor_map = pd.Series(dtype=bool)
        models = labels["model"].astype(str) if "model" in labels.columns else pd.Series("", index=labels.index)
        families = models.str.split().str[0]
        families = families.where(models.str.len() > 0, "unknown").fillna("unknown")
        if "cutoff_date" in labels.columns:
            cutoffs = labels["cutoff_date"].astype(str)
            quarters = cutoffs.where(cutoffs.str.len() < 7, cutoffs.str[:7])
            time_col = cutoffs
        else:
            quarters = pd.Series("unknown", index=labels.index)
            time_col = quarters
        censor_vals = labels["serial_number"].map(censor_map).fillna(False).astype(int)
        env_frame = pd.DataFrame(
            {
                "env": families + "|" + quarters,
                "conf": families,
                "time": time_col,
                "censor": censor_vals,
            }
        )
        _contract_text, contract_json = build_history_contract(
            history, "serial_number", "date",
        )
        return DiscoveryFrames(
            labels=labels[["serial_number", "label"]],
            history=history,
            unit_col="serial_number",
            time_col="date",
            label_col="label",
            baseline_cols=numeric_cols,
            schema_note=_discovery_schema_note(list(history.columns), tail_rows),
            history_schema=contract_json,
            env_frame=env_frame,
        )

    def checkup_extras(self) -> pd.DataFrame | None:
        return None
