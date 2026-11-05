from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

from search_engine import Candidate, EvaluationResult, SearchEngine, aggregate_scores


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def render_command(command: list[str], candidate_file: Path, result_file: Path) -> list[str]:
    replacements = {
        "{candidate_file}": str(candidate_file),
        "{result_file}": str(result_file),
    }
    return [replacements.get(part, part) for part in command]


def evaluate_candidate(
    candidate: Candidate,
    section: dict[str, Any],
    direction: str,
    base_dir: Path,
    output_dir: Path,
    phase: str,
) -> EvaluationResult:
    started = time.monotonic()
    command = section.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(part, str) for part in command):
        return EvaluationResult(False, None, [], 0.0, False, error=f"{phase}.command 必须是字符串数组")
    repetitions = max(1, int(section.get("repetitions", 1)))
    timeout_seconds = max(1, int(section.get("timeout_seconds", 600)))
    aggregation = section.get("aggregation", "mean")
    samples: list[float] = []
    evidence: list[dict[str, Any]] = []
    integrity_passed = True

    for repetition in range(1, repetitions + 1):
        run_dir = output_dir / "runs" / candidate.candidate_id / phase / f"repeat-{repetition:02d}"
        candidate_file = run_dir / "candidate.json"
        result_file = run_dir / "result.json"
        write_json(
            candidate_file,
            {
                "candidate_id": candidate.candidate_id,
                "route_id": candidate.route_id,
                "parameters": candidate.parameters,
                "phase": phase,
                "repetition": repetition,
            },
        )
        rendered = render_command(command, candidate_file.resolve(), result_file.resolve())
        try:
            completed = subprocess.run(
                rendered,
                cwd=base_dir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return EvaluationResult(
                False,
                None,
                samples,
                time.monotonic() - started,
                False,
                evidence,
                f"Evaluator 启动或超时失败: {exc}",
            )
        run_evidence = {
            "repetition": repetition,
            "command": rendered,
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "result_file": str(result_file),
        }
        evidence.append(run_evidence)
        if completed.returncode != 0:
            return EvaluationResult(
                False,
                None,
                samples,
                time.monotonic() - started,
                False,
                evidence,
                f"Evaluator 退出码为 {completed.returncode}",
            )
        if not result_file.exists():
            return EvaluationResult(False, None, samples, time.monotonic() - started, False, evidence, "Evaluator 未写入结果文件")
        try:
            payload = json.loads(result_file.read_text(encoding="utf-8"))
            score = float(payload["score"])
            current_integrity = bool(payload.get("integrity_passed", True))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return EvaluationResult(False, None, samples, time.monotonic() - started, False, evidence, f"结果解析失败: {exc}")
        samples.append(score)
        integrity_passed = integrity_passed and current_integrity

    try:
        score = aggregate_scores(samples, aggregation, direction)
    except ValueError as exc:
        return EvaluationResult(False, None, samples, time.monotonic() - started, False, evidence, str(exc))
    return EvaluationResult(True, score, samples, time.monotonic() - started, integrity_passed, evidence)


def run(spec_path: Path, output_dir: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    engine = SearchEngine(spec)
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "ledger.json"
    started = time.monotonic()
    evaluation = spec.get("evaluation", {})
    concurrency_mode = evaluation.get("concurrency_mode", "serial/v1")
    max_parallel = int(spec["budgets"]["max_parallel_trials"]) if concurrency_mode == "shared-readonly/v1" else 1
    futures: dict[Future[EvaluationResult], str] = {}

    with ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix="search-worker") as executor:
        while True:
            elapsed = time.monotonic() - started
            while len(futures) < max_parallel:
                candidate = engine.reserve_next(elapsed)
                if candidate is None:
                    break
                future = executor.submit(
                    evaluate_candidate,
                    candidate,
                    evaluation,
                    engine.direction,
                    spec_path.parent,
                    output_dir,
                    "validation",
                )
                futures[future] = candidate.candidate_id

            write_json(ledger_path, engine.ledger(time.monotonic() - started))
            if not futures:
                engine.mark_exhausted_if_idle()
                break

            completed, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                candidate_id = futures.pop(future)
                try:
                    result = future.result()
                except Exception as exc:  # Defensive boundary around external evaluator execution.
                    result = EvaluationResult(False, None, [], 0.0, False, error=f"Worker 异常: {exc}")
                engine.record_result(candidate_id, result)
            write_json(ledger_path, engine.ledger(time.monotonic() - started))

    holdout_report: dict[str, Any] | None = None
    holdout = spec.get("holdout", {})
    if holdout.get("enabled") and engine.best_candidate_id and holdout.get("command"):
        best = engine.candidates[engine.best_candidate_id]
        result = evaluate_candidate(best, holdout, engine.direction, spec_path.parent, output_dir, "holdout")
        threshold = holdout.get("minimum_acceptable_score")
        accepted = result.succeeded and result.integrity_passed and result.score is not None
        if accepted and threshold is not None:
            accepted = result.score >= float(threshold) if engine.direction == "maximize" else result.score <= float(threshold)
        holdout_report = {
            "candidate_id": best.candidate_id,
            "route_id": best.route_id,
            "parameters": best.parameters,
            "score": result.score,
            "samples": result.samples,
            "accepted": accepted,
            "integrity_passed": result.integrity_passed,
            "error": result.error,
            "evidence": result.evidence,
        }

    ledger = engine.ledger(time.monotonic() - started, holdout_report)
    write_json(ledger_path, ledger)
    write_json(
        output_dir / "summary.json",
        {
            "stop_reason": ledger["stop_reason"],
            "best_candidate": ledger["best_candidate"],
            "holdout": holdout_report,
            "ledger": str(ledger_path.resolve()),
        },
    )
    return ledger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行分层 AutoResearch 搜索")
    parser.add_argument("--spec", type=Path, required=True, help="ExperimentSpec JSON 文件")
    parser.add_argument("--output-dir", type=Path, required=True, help="账本与执行证据输出目录")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        ledger = run(args.spec.resolve(), args.output_dir.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"搜索启动失败: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"stop_reason": ledger["stop_reason"], "best_candidate": ledger["best_candidate"], "holdout": ledger["holdout"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
