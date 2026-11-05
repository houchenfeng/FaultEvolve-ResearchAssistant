"""Local synthetic classifier evaluation; never reads external or private data."""

import ast
import time
from pathlib import Path


def static_check(source):
    try:
        tree = ast.parse(source)
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assign):
            return "候选只能声明 THRESHOLD 数值参数"
        statement = tree.body[0]
        if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
            return "候选参数声明不合法"
        threshold = ast.literal_eval(statement.value)
        if statement.targets[0].id != "THRESHOLD" or type(threshold) not in (int, float):
            return "候选只能声明 THRESHOLD 数值参数"
        if not 0 <= threshold <= 1:
            return "阈值必须在 [0, 1] 内"
    except (SyntaxError, ValueError, TypeError):
        return "无法解析候选参数"
    return ""


def evaluate(path_user_py, timeout=900):
    started = time.monotonic()
    source = Path(path_user_py).read_text(encoding="utf-8")
    error = static_check(source)
    if error:
        return {"validity": 0., "combined_score": 0., "cost_time": 0., "error_info": error}
    threshold = ast.literal_eval(ast.parse(source).body[0].value)
    features = [.1, .2, .4, .6, .8, .9]
    labels = [0, 0, 0, 1, 1, 1]
    alarms = [int(value >= threshold) for value in features]
    tp = sum(label == 1 and alarm == 1 for label, alarm in zip(labels, alarms))
    fp = sum(label == 0 and alarm == 1 for label, alarm in zip(labels, alarms))
    fn = sum(label == 1 and alarm == 0 for label, alarm in zip(labels, alarms))
    precision, recall = tp / max(1, tp + fp), tp / max(1, tp + fn)
    f1 = 2 * tp / max(1, 2 * tp + fp + fn)
    return {"validity": 1., "combined_score": 100 * f1,
            "cost_time": time.monotonic() - started, "error_info": "",
            "metric": {"split": "val", "precision": precision, "recall": recall, "f1": f1,
                       "false_alarm_rate": fp / 3, "missed_detection_rate": fn / 3,
                       "parameter_count": 1}}
