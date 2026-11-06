#!/usr/bin/env python
"""Remote self-evolution loop for the local-cloud hybrid mode.

Runs on the cloud server (standard library only) inside one session directory
that the laptop prepared over SFTP:

    config.json            mode / provider / model / generations
    task/prompt.md         task description handed to the LLM
    seeds/<id>.py          starting population (code only, never data)
    .llm_env               DASHSCOPE_API_KEY=... (mode 600, qwen provider only)

Each generation the evolver picks a parent, produces a child program and writes
``candidates/<cid>.py`` + ``candidates/<cid>.json``. It then waits for the
laptop to write ``results/<cid>.json``: the whitelisted scalar scores of the
local sandbox evaluation. The data never reaches this machine; only scores do.

Providers:
    replay  demo mode: emit the recorded programs in ``replay/`` in order, no LLM
    qwen    DashScope OpenAI-compatible chat completions (urllib)
    codex   the laptop's ``codex exec`` with its local ChatGPT login: the prompt
            goes to ``llm_requests/<cid>.json``, the answer comes back in
            ``llm_responses/<cid>.txt``

Writing ``STOP`` into the session directory ends the loop after the current step.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
import traceback
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
QWEN_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


def now() -> float:
    return round(time.time(), 3)


def write_json(path: Path, data: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Evolver:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.cfg = read_json(root / "config.json") or {}
        self.provider = self.cfg.get("provider", "qwen")
        self.model = self.cfg.get("model", "qwen3.8-max-0902")
        self.generations = int(self.cfg.get("generations", 3))
        self.result_timeout = float(self.cfg.get("result_timeout_s", 1800))
        for sub in ("candidates", "results", "llm_requests", "llm_responses"):
            (root / sub).mkdir(exist_ok=True)
        self.population: list[dict] = []
        self.history: list[dict] = []
        self.tokens = 0
        self.state = "starting"
        self.current: dict | None = None
        self.started_at = now()
        self._load_env()

    # ------------------------------------------------------------ plumbing
    def _load_env(self) -> None:
        env_file = Path(self.cfg.get("llm_env_file") or self.root / ".llm_env")
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    def event(self, kind: str, text: str, **extra: object) -> None:
        rec = {"at": now(), "kind": kind, "text": text, **extra}
        with (self.root / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{time.strftime('%H:%M:%S')}] {kind}: {text}", flush=True)

    def status(self) -> None:
        best = max(self.population, key=lambda c: c["score"], default=None)
        write_json(self.root / "status.json", {
            "pid": os.getpid(),
            "host": os.uname().nodename if hasattr(os, "uname") else "",
            "state": self.state,
            "mode": self.cfg.get("mode"),
            "provider": self.provider,
            "model": self.model if self.provider != "replay" else None,
            "generation": len(self.history),
            "generations": self.generations,
            "tokens": self.tokens,
            "started_at": self.started_at,
            "updated_at": now(),
            "current": self.current,
            "best": best,
            "population": sorted(self.population, key=lambda c: -c["score"]),
            "history": self.history,
        })

    def stopped(self) -> bool:
        return (self.root / "STOP").exists()

    # ----------------------------------------------------------- candidates
    def submit(self, cid: str, code: str, parent: str | None, origin: str) -> dict | None:
        """Hand one program to the laptop and block until its scores come back."""
        meta = {"id": cid, "parent": parent, "origin": origin, "created_at": now(),
                "generation": len(self.history), "lines": code.count("\n") + 1}
        (self.root / "candidates" / f"{cid}.py").write_text(code, encoding="utf-8")
        write_json(self.root / "candidates" / f"{cid}.json", meta)
        self.current = {**meta, "phase": "local_eval"}
        self.state = "waiting_local_eval"
        self.status()
        self.event("submit", f"候选 {cid} 已下发，等待本地沙箱评估", candidate=cid, parent=parent)
        deadline = time.time() + self.result_timeout
        result_path = self.root / "results" / f"{cid}.json"
        while time.time() < deadline:
            if self.stopped():
                return None
            res = read_json(result_path)
            if res is not None:
                return res
            time.sleep(1.0)
        self.event("timeout", f"候选 {cid} 本地评估超时")
        return {"validity": 0, "combined_score": 0, "error": "local eval timeout"}

    def record(self, cid: str, parent: str | None, origin: str, res: dict, code: str) -> None:
        score = float(res.get("combined_score") or 0) if res.get("validity") else 0.0
        entry = {"id": cid, "parent": parent, "origin": origin, "score": round(score, 4),
                 "validity": res.get("validity"), "metrics": res, "at": now()}
        self.history.append(entry)
        if res.get("validity"):
            self.population.append({"id": cid, "parent": parent, "score": round(score, 4), "origin": origin,
                                    "metrics": res})
            (self.root / "programs").mkdir(exist_ok=True)
            (self.root / "programs" / f"{cid}.py").write_text(code, encoding="utf-8")
        best = max(self.population, key=lambda c: c["score"], default=None)
        self.event("result", f"候选 {cid} 本地 ROS={score:.2f}，当前最佳 {best['id'] if best else '-'}"
                   f"（{best['score'] if best else 0:.2f}）", candidate=cid, score=score)
        self.current = None
        self.status()

    def pick_parent(self) -> dict:
        ranked = sorted(self.population, key=lambda c: -c["score"])
        # Mostly exploit the best; sometimes branch from the runner-up. Replay stays deterministic.
        if self.provider != "replay" and len(ranked) > 1 and random.random() < 0.25:
            return ranked[1]
        return ranked[0]

    # ------------------------------------------------------------- LLM side
    def build_prompt(self, parent: dict, parent_code: str) -> str:
        task = (self.root / "task" / "prompt.md").read_text(encoding="utf-8")
        metrics = parent.get("metrics") or {}
        feedback = {k: metrics.get(k) for k in (
            "combined_score", "f1_p10", "auprc", "recall_at_far", "precision", "recall",
            "false_alarm_rate", "run_time_s", "noise_band", "caught", "false_alarms",
            "failures_observed", "disks_monitored") if metrics.get(k) is not None}
        tried = [f"- {h['id']} (parent {h['parent']}): ROS {h['score']}"
                 + (f", FAILED with {h['metrics'].get('error_kind')}" if not h.get("validity") else "")
                 for h in self.history[-6:]]
        return (
            f"{task}\n\n# Current parent program ({parent['id']}, local ROS {parent['score']})\n\n"
            f"```python\n{parent_code}\n```\n\n"
            f"# Scalar feedback from the private local evaluator (the only data you get)\n\n"
            f"{json.dumps(feedback, ensure_ascii=False)}\n\n"
            f"`caught`/`false_alarms` come from a 300-disk data-hall stream on an edge tablet "
            f"(10 real failures in the following 7 days).\n\n"
            f"# Recent attempts\n\n" + ("\n".join(tried) or "- none") + "\n\n"
            "# Instructions\n\nPropose ONE focused improvement over the parent that should raise "
            "combined_score (robust alarm threshold, better temporal features, model choice). "
            "Keep the runtime well under 300 s on a laptop CPU. Return the COMPLETE program in a "
            "single ```python code block, preceded by one sentence describing the change."
        )

    def call_qwen(self, prompt: str) -> tuple[str, int]:
        key = os.environ.get("DASHSCOPE_API_KEY", "")
        if not key:
            raise RuntimeError("DASHSCOPE_API_KEY missing on server")
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": "You are a senior ML engineer. Output runnable Python."},
                         {"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": int(self.cfg.get("max_tokens", 16000)),
            "stream": True,
            "stream_options": {"include_usage": True},
            # Deep thinking costs ~10 min per candidate on this model; off keeps a generation under a minute.
            "enable_thinking": bool(self.cfg.get("enable_thinking", False)),
        }).encode()
        req = urllib.request.Request(os.environ.get("FE_QWEN_URL", QWEN_URL), data=body, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        last: Exception | None = None
        for attempt in range(3):
            content: list[str] = []
            reasoning = 0
            tokens = 0
            last_report = time.time()
            try:
                # The read timeout applies per chunk: a silent connection fails fast, a long answer does not.
                with urllib.request.urlopen(req, timeout=180) as resp:
                    for raw in resp:
                        if self.stopped():
                            raise RuntimeError("stopped")
                        line = raw.decode("utf-8", "replace").strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        chunk = json.loads(payload)
                        if chunk.get("usage"):
                            tokens = int(chunk["usage"].get("total_tokens") or 0)
                        for choice in chunk.get("choices") or []:
                            delta = choice.get("delta") or {}
                            content.append(delta.get("content") or "")
                            reasoning += len(delta.get("reasoning_content") or "")
                        if time.time() - last_report > 3 and self.current is not None:
                            last_report = time.time()
                            self.current["llm_chars"] = sum(map(len, content))
                            self.current["reasoning_chars"] = reasoning
                            self.status()
                text = "".join(content)
                if text.strip():
                    return text, tokens
                last = RuntimeError("empty answer")
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError) as exc:
                last = exc
            self.event("llm", f"Qwen 请求第 {attempt + 1} 次失败：{last}，重试")
            time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"qwen request failed: {last}")

    def call_codex_bridge(self, cid: str, prompt: str) -> tuple[str, int]:
        write_json(self.root / "llm_requests" / f"{cid}.json", {"id": cid, "prompt": prompt, "at": now()})
        self.event("llm", f"提示词已交给本地 Codex（{cid}）")
        resp = self.root / "llm_responses" / f"{cid}.txt"
        deadline = time.time() + float(self.cfg.get("codex_timeout_s", 1200))
        while time.time() < deadline:
            if self.stopped():
                raise RuntimeError("stopped")
            if resp.exists():
                return resp.read_text(encoding="utf-8"), 0
            time.sleep(1.0)
        raise RuntimeError("codex bridge timeout")

    @staticmethod
    def extract_code(text: str) -> str:
        blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, flags=re.S)
        if not blocks:
            raise ValueError("no python code block in LLM answer")
        code = max(blocks, key=len).strip() + "\n"
        if "--data-dir" not in code or "--out" not in code:
            raise ValueError("answer does not keep the CLI contract")
        return code

    # ----------------------------------------------------------------- loop
    def seed(self) -> None:
        seeds = sorted((self.root / "seeds").glob("*.py"))
        for path in seeds:
            cid = path.stem
            code = path.read_text(encoding="utf-8")
            res = self.submit(cid, code, None, "seed")
            if res is None:
                return
            self.record(cid, None, "seed", res, code)

    def generate(self, parent: dict) -> tuple[str, str, str]:
        cid = uuid.uuid4().hex[:8]
        if self.provider == "replay":
            bank = sorted((self.root / "replay").glob("*.py"))
            idx = len([h for h in self.history if h["origin"] == "replay"])
            if idx >= len(bank):
                raise StopIteration
            path = bank[idx]
            time.sleep(float(self.cfg.get("replay_think_s", 3)))
            return path.stem.split("_", 1)[-1], path.read_text(encoding="utf-8"), "replay"
        parent_code = (self.root / "programs" / f"{parent['id']}.py").read_text(encoding="utf-8")
        prompt = self.build_prompt(parent, parent_code)
        self.current = {"id": cid, "parent": parent["id"], "phase": "llm", "provider": self.provider}
        self.state = "generating"
        self.status()
        self.event("llm", f"以 {parent['id']}（{parent['score']:.2f}）为父代，请求 {self.provider}/{self.model} 生成候选 {cid}")
        t0 = time.time()
        if self.provider == "codex":
            text, tokens = self.call_codex_bridge(cid, prompt)
        else:
            text, tokens = self.call_qwen(prompt)
        self.tokens += tokens
        (self.root / "llm_responses").mkdir(exist_ok=True)
        (self.root / "llm_responses" / f"{cid}.answer.md").write_text(text, encoding="utf-8")
        code = self.extract_code(text)
        idea = text.split("```", 1)[0].strip().splitlines()
        self.event("llm", f"候选 {cid} 生成完成（{time.time() - t0:.0f}s，{tokens} tokens）：{(idea[-1] if idea else '')[:120]}")
        return cid, code, self.provider

    def run(self) -> None:
        self.event("start", f"远端自进化启动：mode={self.cfg.get('mode')} provider={self.provider} generations={self.generations}")
        self.seed()
        failures = 0
        while len([h for h in self.history if h["origin"] != "seed"]) < self.generations and not self.stopped():
            if not self.population:
                self.event("error", "没有有效的种子程序")
                break
            parent = self.pick_parent()
            try:
                cid, code, origin = self.generate(parent)
            except StopIteration:
                break
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                failures += 1
                self.event("error", f"生成失败：{type(exc).__name__}: {exc}")
                if failures >= 4:
                    break
                continue
            res = self.submit(cid, code, parent["id"], origin)
            if res is None:
                break
            self.record(cid, parent["id"], origin, res, code)
        self.state = "stopped" if self.stopped() else "done"
        self.current = None
        self.status()
        best = max(self.population, key=lambda c: c["score"], default=None)
        self.event("done", f"远端自进化结束：{len(self.history)} 个候选，最佳 {best['id'] if best else '-'}"
                   f"（ROS {best['score'] if best else 0:.2f}）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(HERE))
    args = ap.parse_args()
    ev = Evolver(Path(args.root))
    try:
        ev.run()
    except Exception:  # noqa: BLE001
        ev.state = "error"
        ev.status()
        ev.event("error", traceback.format_exc()[-1500:])
        raise


if __name__ == "__main__":
    main()
