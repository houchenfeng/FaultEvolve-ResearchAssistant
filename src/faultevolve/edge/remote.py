"""Laptop side of remote self-evolution: SSH (via a jump host) to the cloud server.

The server runs ``scripts/edge_remote_evolver.py`` detached (``setsid nohup``), so
the evolution keeps going on its own. This module

1. deploys a session directory over SFTP (evolver, task prompt, seed programs --
   code only, never data),
2. polls the session for new candidates, evaluates each one in the local sandbox
   (:mod:`faultevolve.edge.local_eval`, tablet scene + val split + GPU bootstrap),
3. writes back ``results/<cid>.json`` containing only whitelisted scalars,
4. for the ``codex`` provider, answers the evolver's prompts with the local
   ``codex exec`` (ChatGPT login stays on this machine).

Modes: ``demo`` replays recorded programs on the server (no LLM call);
``real`` lets the server call the LLM for every generation.

Configuration comes from the environment (or the repo ``.env``):
``FE_SSH_JUMP=user@host:port``, ``FE_SSH_JUMP_PASSWORD``, ``FE_SSH_TARGET=user@host:port``,
``FE_SSH_TARGET_PASSWORD``, ``FE_REMOTE_ROOT``, ``FE_REMOTE_PYTHON``,
``DASHSCOPE_API_KEY``, ``FE_QWEN_MODEL``, ``FE_LLM_PROVIDER``.
"""

from __future__ import annotations

import asyncio
import json
import os
import posixpath
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from faultevolve.edge import boundary, local_eval, paths

EVOLVER_SCRIPT = paths.REPO_ROOT / "scripts" / "edge_remote_evolver.py"
DEFAULT_MODEL = "qwen3.8-max-0902"


def load_dotenv(path: Path = paths.REPO_ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _split_addr(addr: str, default_port: int = 22) -> tuple[str, str, int]:
    user, _, hostport = addr.partition("@")
    host, _, port = hostport.partition(":")
    return user, host, int(port or default_port)


@dataclass
class RemoteConfig:
    jump: str | None
    jump_password: str | None
    target: str
    target_password: str | None
    root: str
    python: str

    @classmethod
    def from_env(cls) -> "RemoteConfig":
        load_dotenv()
        target = os.environ.get("FE_SSH_TARGET", "").strip()
        if not target:
            raise RuntimeError("未配置 FE_SSH_TARGET（user@host:port）")
        return cls(
            jump=os.environ.get("FE_SSH_JUMP", "").strip() or None,
            jump_password=os.environ.get("FE_SSH_JUMP_PASSWORD") or None,
            target=target,
            target_password=os.environ.get("FE_SSH_TARGET_PASSWORD") or None,
            root=os.environ.get("FE_REMOTE_ROOT", "").strip() or "~/faultevolve_edge_hybrid",
            python=os.environ.get("FE_REMOTE_PYTHON", "").strip() or "python3",
        )

    def describe(self) -> dict[str, Any]:
        tu, th, tp = _split_addr(self.target)
        out = {"target": f"{tu}@{th}:{tp}", "root": self.root, "python": self.python}
        if self.jump:
            ju, jh, jp = _split_addr(self.jump)
            out["jump"] = f"{ju}@{jh}:{jp}"
        return out


def describe_ssh_error(exc: BaseException, cfg: RemoteConfig) -> str:
    """Turn asyncssh failures into a hint that says which hop broke."""
    raw = f"{type(exc).__name__}: {exc}"
    name = type(exc).__name__
    if cfg.jump and name == "ChannelOpenError":
        _, th, tp = _split_addr(cfg.target)
        return (f"{raw}。跳板机已登录，但跳板机上 {th}:{tp} 没有服务在监听——"
                "服务器到跳板机的反向隧道（frpc / ssh -R）已断开，请在服务器上重启隧道后重试。")
    if name == "PermissionDenied":
        return f"{raw}。用户名或密码错误（检查 FE_SSH_JUMP* / FE_SSH_TARGET*）。"
    if isinstance(exc, (TimeoutError, OSError)) and not name.startswith("Channel"):
        return f"{raw}。连不上跳板机（{cfg.describe().get('jump', cfg.describe()['target'])}），检查网络或地址端口。"
    return raw


class _Conn:
    """Jump host + target connection pair."""

    def __init__(self, cfg: RemoteConfig) -> None:
        self.cfg = cfg
        self.jump: Any = None
        self.conn: Any = None
        self.host_keys: dict[str, str] = {}

    async def __aenter__(self) -> "_Conn":
        import asyncssh

        tunnel = None
        if self.cfg.jump:
            ju, jh, jp = _split_addr(self.cfg.jump)
            self.jump = await asyncssh.connect(jh, port=jp, username=ju, password=self.cfg.jump_password,
                                               known_hosts=None, connect_timeout=15)
            key = self.jump.get_server_host_key()
            self.host_keys["jump"] = key.get_fingerprint() if key else ""
            tunnel = self.jump
        tu, th, tp = _split_addr(self.cfg.target)
        self.conn = await asyncssh.connect(th, port=tp, username=tu, password=self.cfg.target_password,
                                           known_hosts=None, tunnel=tunnel, connect_timeout=15)
        key = self.conn.get_server_host_key()
        self.host_keys["target"] = key.get_fingerprint() if key else ""
        return self

    async def __aexit__(self, *exc: object) -> None:
        for c in (self.conn, self.jump):
            if c is not None:
                c.close()

    async def run(self, cmd: str, timeout: float = 30) -> str:
        r = await asyncio.wait_for(self.conn.run(cmd, check=False), timeout=timeout)
        return ((r.stdout or "") + (r.stderr or "")).strip()


async def _probe(cfg: RemoteConfig) -> dict[str, Any]:
    t0 = time.perf_counter()
    async with _Conn(cfg) as c:
        latency = round((time.perf_counter() - t0) * 1000)
        host = await c.run("hostname -I 2>/dev/null | cut -d' ' -f1; hostname")
        gpus = await c.run("nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total "
                           "--format=csv,noheader,nounits 2>/dev/null")
        py = await c.run(f"{cfg.python} -c 'import sys;print(sys.version.split()[0])'")
        net = await c.run("curl -s -o /dev/null -m 8 -w '%{http_code}' "
                          "https://dashscope.aliyuncs.com/compatible-mode/v1/models")
        return {
            "ok": True, "latency_ms": latency, "host": host.splitlines(), "python": py,
            "gpus": _parse_gpus(gpus), "dashscope_http": net, "host_keys": c.host_keys,
            "config": cfg.describe(),
        }


def _parse_gpus(text: str) -> list[dict[str, Any]]:
    out = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 4:
            try:
                out.append({"name": parts[0], "util": float(parts[1]), "mem_used_mb": float(parts[2]),
                            "mem_total_mb": float(parts[3])})
            except ValueError:
                continue
    return out


def llm_status() -> dict[str, Any]:
    """Both LLM providers: Qwen key presence and the local Codex login."""
    load_dotenv()
    codex = os.environ.get("FE_CODEX_CMD") or shutil.which("codex")
    codex_login = None
    if codex:
        try:
            r = subprocess.run([codex, "login", "status"], capture_output=True, text=True, timeout=15,
                               encoding="utf-8", errors="replace")
            codex_login = {"ok": r.returncode == 0, "text": (r.stdout or r.stderr).strip()[:200]}
        except (OSError, subprocess.TimeoutExpired) as exc:
            codex_login = {"ok": False, "text": str(exc)[:200]}
    return {
        "default": os.environ.get("FE_LLM_PROVIDER", "qwen"),
        "qwen": {"key_present": bool(os.environ.get("DASHSCOPE_API_KEY", "").strip()),
                 "model": os.environ.get("FE_QWEN_MODEL", DEFAULT_MODEL),
                 "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
        "codex": {"installed": bool(codex), "command": codex, "login": codex_login,
                  "hint": "npm i -g @openai/codex && codex login"},
    }


def run_codex(prompt: str, timeout: int = 1200) -> str:
    codex = os.environ.get("FE_CODEX_CMD") or shutil.which("codex")
    if not codex:
        raise RuntimeError("本机未安装 codex CLI")
    with tempfile.TemporaryDirectory(prefix="fe_codex_") as tmp:
        out = Path(tmp) / "last.md"
        r = subprocess.run(
            [codex, "exec", "--skip-git-repo-check", "--sandbox", "read-only",
             "--output-last-message", str(out), "-"],
            input=prompt, capture_output=True, text=True, timeout=timeout, cwd=tmp,
            encoding="utf-8", errors="replace",
        )
        if out.exists() and out.read_text("utf-8").strip():
            return out.read_text("utf-8")
        if r.returncode != 0:
            raise RuntimeError(f"codex exec 失败：{(r.stderr or r.stdout)[-400:]}")
        return r.stdout


class RemoteSession:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.events: deque[dict[str, Any]] = deque(maxlen=200)
        self._reset()

    def _reset(self) -> None:
        self.session_id: str | None = None
        self.mode: str | None = None
        self.provider: str | None = None
        self.model: str | None = None
        self.phase = "idle"
        self.error: str | None = None
        self.remote_dir: str | None = None
        self.remote_status: dict[str, Any] | None = None
        self.server_gpus: list[dict[str, Any]] = []
        self.candidates: list[dict[str, Any]] = []
        self.local_step: str | None = None
        self.codes: dict[str, str] = {}
        self.stop_requested = False
        self.started_at: float | None = None
        self.host_keys: dict[str, str] = {}
        self.pid: str | None = None

    def log(self, kind: str, text: str, source: str = "local") -> None:
        self.events.appendleft({"at": time.time(), "kind": kind, "text": text, "source": source})

    # -------------------------------------------------------------- control
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def probe(self) -> dict[str, Any]:
        try:
            cfg = RemoteConfig.from_env()
            return asyncio.run(_probe(cfg))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": describe_ssh_error(exc, RemoteConfig.from_env())}

    def start(self, mode: str = "demo", provider: str | None = None, model: str | None = None,
              generations: int = 3, hub: Any = None) -> dict[str, Any]:
        if self.running():
            return {"started": False, "reason": "已有远端会话在运行"}
        load_dotenv()
        with self.lock:
            self._reset()
            self.events.clear()
            self.mode = "real" if mode == "real" else "demo"
            self.provider = "replay" if self.mode == "demo" else (provider or os.environ.get("FE_LLM_PROVIDER", "qwen"))
            self.model = None if self.provider == "replay" else (model or os.environ.get("FE_QWEN_MODEL", DEFAULT_MODEL))
            self.session_id = time.strftime("s%Y%m%d-%H%M%S")
            self.started_at = time.time()
            self.phase = "connecting"
        self.hub = hub
        self.thread = threading.Thread(target=lambda: asyncio.run(self._main(generations)),
                                       name="fe-edge-remote", daemon=True)
        self.thread.start()
        return {"started": True, "session_id": self.session_id, "mode": self.mode, "provider": self.provider}

    def stop(self) -> dict[str, Any]:
        self.stop_requested = True
        return {"stopping": self.running()}

    # ------------------------------------------------------------ main loop
    async def _main(self, generations: int) -> None:
        try:
            cfg = RemoteConfig.from_env()
            async with _Conn(cfg) as c:
                self.host_keys = c.host_keys
                self.log("link", f"已经跳板机 {cfg.describe().get('jump', '-')} 连接服务器 {cfg.describe()['target']}")
                await self._deploy(c, cfg, generations)
                await self._poll(c)
        except Exception as exc:  # noqa: BLE001
            self.error = describe_ssh_error(exc, RemoteConfig.from_env())
            self.phase = "error"
            self.log("error", f"远端会话异常：{self.error}")

    async def _deploy(self, c: _Conn, cfg: RemoteConfig, generations: int) -> None:
        root = cfg.root
        if root.startswith("~"):
            home = await c.run("echo $HOME")
            root = home + root[1:]
        self.remote_dir = posixpath.join(root, self.session_id or "session")
        rd = self.remote_dir
        await c.run(f"mkdir -p {rd}/task {rd}/seeds {rd}/replay {rd}/programs")
        self.phase = "deploying"
        config = {"mode": self.mode, "provider": self.provider, "model": self.model,
                  "generations": generations, "session": self.session_id, "result_timeout_s": 1800,
                  "enable_thinking": os.environ.get("FE_QWEN_THINKING", "0") == "1"}
        async with c.conn.start_sftp_client() as sftp:
            async def put_text(rel: str, text: str) -> None:
                async with sftp.open(posixpath.join(rd, rel), "w") as fh:
                    await fh.write(text)

            await put_text("evolver.py", EVOLVER_SCRIPT.read_text("utf-8"))
            await put_text("config.json", json.dumps(config, ensure_ascii=False, indent=1))
            await put_text("task/prompt.md", (paths.TASK_DIR / "prompt.md").read_text("utf-8"))
            init_code = paths.BASELINE_PROGRAM.read_text("utf-8")
            await put_text("seeds/init.py", init_code)
            self.codes["init"] = init_code
            if self.mode == "demo":
                await put_text("replay/01_rule_baseline.py",
                               (paths.TASK_DIR / "candidates" / "rule_baseline.py").read_text("utf-8"))
                await put_text(f"replay/02_{paths.EVOLVED_NODE_ID}.py", paths.EVOLVED_PROGRAM.read_text("utf-8"))
            else:
                evolved = paths.EVOLVED_PROGRAM.read_text("utf-8")
                await put_text(f"seeds/{paths.EVOLVED_NODE_ID}.py", evolved)
                self.codes[paths.EVOLVED_NODE_ID] = evolved
                if self.provider == "qwen":
                    # The session dir may sit on a shared NAS: the key goes to the server's own home, mode 600.
                    secret_dir = posixpath.join(await c.run("echo $HOME"), ".fe_edge")
                    await c.run(f"mkdir -p {secret_dir} && chmod 700 {secret_dir}")
                    secret = posixpath.join(secret_dir, f"{self.session_id}.env")
                    async with sftp.open(secret, "w") as fh:
                        await fh.write(f"DASHSCOPE_API_KEY={os.environ.get('DASHSCOPE_API_KEY', '')}\n")
                    await sftp.chmod(secret, 0o600)
                    config["llm_env_file"] = secret
                    await put_text("config.json", json.dumps(config, ensure_ascii=False, indent=1))
        # `cd X; cmd &` (not `cd X && cmd &`): otherwise a subshell keeps the SSH channel open.
        self.pid = await c.run(f"cd {rd}; setsid nohup {cfg.python} -u evolver.py --root {rd} "
                               f"> evolver.log 2>&1 < /dev/null & echo $!")
        self.log("deploy", f"会话 {self.session_id} 已部署到 {rd}，远端进化器 PID {self.pid}"
                           f"（{'回放已落盘候选' if self.mode == 'demo' else f'{self.provider}/{self.model} 实时生成'}）")
        self.phase = "evolving"

    async def _poll(self, c: _Conn) -> None:
        rd = self.remote_dir or ""
        done: set[str] = set()
        answered: set[str] = set()
        events_offset = 0
        last_gpu = 0.0
        async with c.conn.start_sftp_client() as sftp:
            async def read_text(rel: str) -> str | None:
                try:
                    async with sftp.open(posixpath.join(rd, rel), "r") as fh:
                        return await fh.read()
                except (OSError, Exception):  # noqa: BLE001
                    return None

            async def write_text(rel: str, text: str) -> None:
                tmp = posixpath.join(rd, rel + ".part")
                async with sftp.open(tmp, "w") as fh:
                    await fh.write(text)
                await sftp.posix_rename(tmp, posixpath.join(rd, rel))

            while True:
                if self.stop_requested:
                    await write_text("STOP", "stop requested from laptop\n")
                    self.stop_requested = False
                    self.log("control", "已向远端进化器发送 STOP")

                status_text = await read_text("status.json")
                if status_text:
                    try:
                        self.remote_status = json.loads(status_text)
                    except ValueError:
                        pass

                ev_text = await read_text("events.jsonl")
                if ev_text and len(ev_text) > events_offset:
                    for line in ev_text[events_offset:].splitlines():
                        try:
                            rec = json.loads(line)
                            self.log(rec.get("kind", "remote"), rec.get("text", ""), source="server")
                        except ValueError:
                            continue
                    events_offset = len(ev_text)

                if time.time() - last_gpu > 8:
                    last_gpu = time.time()
                    alive = await c.run(f"kill -0 {self.pid} 2>/dev/null && echo alive || echo gone", timeout=15)
                    if alive.strip() == "gone" and (self.remote_status or {}).get("state") not in ("done", "stopped"):
                        tail = await c.run(f"tail -3 {rd}/evolver.log", timeout=15)
                        self.phase = "error"
                        self.error = f"远端进化器进程已退出：{tail[-300:]}"
                        self.log("error", self.error, source="server")
                        return
                    try:
                        self.server_gpus = _parse_gpus(await c.run(
                            "nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total "
                            "--format=csv,noheader,nounits", timeout=15))
                    except Exception:  # noqa: BLE001
                        pass

                if self.provider == "codex":
                    for name in await sftp.listdir(posixpath.join(rd, "llm_requests")):
                        cid = name.removesuffix(".json")
                        if not name.endswith(".json") or cid in answered:
                            continue
                        answered.add(cid)
                        req = json.loads(await read_text(f"llm_requests/{name}") or "{}")
                        self.local_step = f"本地 Codex 生成候选 {cid}"
                        self.log("llm", f"远端请求本地 Codex 生成候选 {cid}")
                        try:
                            answer = await asyncio.to_thread(run_codex, req.get("prompt", ""))
                        except Exception as exc:  # noqa: BLE001
                            answer = f"codex error: {exc}"
                            self.log("error", f"Codex 生成失败：{exc}")
                        await write_text(f"llm_responses/{cid}.txt", answer)
                        self.local_step = None

                names = sorted(await sftp.listdir(posixpath.join(rd, "candidates")))
                for name in names:
                    cid = name.removesuffix(".py")
                    # The evolver writes the .json meta after the program: its presence marks completion.
                    if not name.endswith(".py") or cid in done or f"{cid}.json" not in names:
                        continue
                    done.add(cid)
                    await self._evaluate(cid, read_text, write_text)

                state = (self.remote_status or {}).get("state")
                if state in ("done", "stopped", "error"):
                    self.phase = state
                    self.log("done", f"远端会话结束（{state}）")
                    return
                await asyncio.sleep(1.5)

    async def _evaluate(self, cid: str, read_text: Any, write_text: Any) -> None:
        code = await read_text(f"candidates/{cid}.py") or ""
        meta = json.loads(await read_text(f"candidates/{cid}.json") or "{}")
        self.codes[cid] = code
        parent = meta.get("parent")
        entry: dict[str, Any] = {"id": cid, "parent": parent, "origin": meta.get("origin"),
                                 "lines": meta.get("lines"), "status": "evaluating", "received_at": time.time()}
        self.candidates.append(entry)
        index = len(self.candidates)
        self.log("eval", f"收到候选 {cid}（父代 {parent or '无'}，{meta.get('lines')} 行），开始本地沙箱评估")
        hub = self.hub
        tablet: dict[str, Any] = {"linked": bool(hub is not None and hub.tablet_linked)}
        entry["tablet"] = tablet
        if hub is not None and tablet["linked"]:
            self.local_step = f"{cid}：请求平板上报机房 SMART 窗口"
            tablet["phase"] = "uploading"
            got = await asyncio.to_thread(hub.exchange, cid, {
                "type": "eval_request", "candidate": cid, "parent": parent, "index": index,
            }, "snapshot", 30.0)
            tablet.update(hub.exchanges.get(cid, {}), uploaded=got, phase="uploaded" if got else "timeout")
            if not got:
                self.log("error", f"平板 30s 内未上报候选 {cid} 的 SMART 窗口，改用本机已有场景")
        scene = local_eval.scene_from_hub(self.hub) or local_eval.scene_from_replay()
        with tempfile.TemporaryDirectory(prefix="fe_cand_") as tmp:
            path = Path(tmp) / f"{cid}.py"
            path.write_text(code, encoding="utf-8")

            def step(text: str) -> None:
                self.local_step = f"{cid}：{text}"

            try:
                res = await asyncio.to_thread(local_eval.evaluate_candidate, path,
                                              parent_code=self.codes.get(parent) if parent else None,
                                              scene=scene, progress=step)
            except Exception as exc:  # noqa: BLE001
                res = {"valid": False, "error": f"{type(exc).__name__}: {exc}",
                       "packet": {"validity": 0, "combined_score": 0.0}}
        self.local_step = None
        gated = boundary.gate(f"remote_candidate_{cid}", {
            "candidate_id": cid, **res["packet"],
            "per_disk_predictions": res.get("scene_alarm_serials", []),
            "serial_numbers": list(scene["disks"].keys()),
            "smart_rows": scene["rows"],
            "val_labels": "eval_only/val_labels.csv",
            "evaluator_source": "evaluator.py",
        })
        sc = res.get("scene") or {}
        alarm_serials = res.get("scene_alarm_serials", [])
        if hub is not None and tablet["linked"]:
            self.local_step = f"{cid}：预警下发平板机房孪生"
            tablet["phase"] = "downlink"
            acked = await asyncio.to_thread(hub.exchange, cid, {
                "type": "candidate_alarms", "candidate": cid, "parent": parent, "index": index,
                "valid": bool(res.get("valid")), "ros": res.get("ros"), "alarms": alarm_serials,
                "caught": sc.get("caught"), "failures": sc.get("failures"), "false_alarms": sc.get("false_alarms"),
            }, "ack", 10.0)
            tablet.update(acked=acked, alarms_sent=len(alarm_serials), phase="acked" if acked else "no_ack")
            self.local_step = None
        if self.hub is not None:
            self.hub.uploads.appendleft(gated)
        await write_text(f"results/{cid}.json", json.dumps(gated["allowed"], ensure_ascii=False))
        entry.update({
            "status": "done" if res.get("valid") else "invalid",
            "ros": res.get("ros"), "scene": res.get("scene"), "gpu": res.get("gpu"),
            "bootstrap": res.get("bootstrap"), "metric": res.get("metric"), "error": res.get("error"),
            "elapsed_s": res.get("elapsed_s"), "uploaded": gated["allowed"],
            "blocked": [b["field"] for b in gated["blocked"]],
            # Local-only (the gate above blocked it from the server): lets the UI paint
            # this candidate's alarms onto the tablet scene.
            "alarm_serials": alarm_serials,
        })
        g = res.get("gpu") or {}
        if res.get("valid"):
            self.log("eval", f"候选 {cid}：ROS {res['ros']:.2f}，平板场景预警命中 {sc.get('caught')}/{sc.get('failures')}"
                             f"、误报 {sc.get('false_alarms')}；GPU 峰值 {g.get('peak_util')}%、"
                             f"显存峰值 {g.get('peak_mem_mb')} MB；仅白名单标量已回传")
        else:
            self.log("error", f"候选 {cid} 无效：{str(res.get('error'))[:200]}")

    # ------------------------------------------------------------- snapshot
    def snapshot(self) -> dict[str, Any]:
        try:
            cfg = RemoteConfig.from_env().describe()
        except RuntimeError as exc:
            cfg = {"error": str(exc)}
        rs = self.remote_status or {}
        return {
            "session_id": self.session_id, "mode": self.mode, "provider": self.provider, "model": self.model,
            "phase": self.phase, "running": self.running(), "error": self.error, "config": cfg,
            "remote_dir": self.remote_dir, "remote_pid": self.pid, "host_keys": self.host_keys,
            "started_at": self.started_at, "local_step": self.local_step,
            "remote": {k: rs.get(k) for k in ("state", "generation", "generations", "tokens", "current",
                                               "best", "population", "updated_at", "host", "pid")},
            "server_gpus": self.server_gpus,
            "candidates": list(self.candidates),
            "events": list(self.events)[:80],
        }


REMOTE = RemoteSession()
