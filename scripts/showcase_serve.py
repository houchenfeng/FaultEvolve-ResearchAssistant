#!/usr/bin/env python
"""启动 FaultEvolve 比赛展示后端。

服务会把仓库内的只读 HDD 展示运行复制到临时目录，因此浏览、回放和
下载制品不会修改提交包本身。
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SHOWCASE_RUN_ID = "hdd_mvp_showcase_c89e2a01"


def build_settings(scratch: Path):
    from faultevolve.webapi.settings import WebSettings

    source_run = REPO_ROOT / "showcase" / "runs" / SHOWCASE_RUN_ID
    runs_root = scratch / "runs"
    shutil.copytree(source_run, runs_root / SHOWCASE_RUN_ID)

    return WebSettings(
        runs_root=runs_root,
        artifacts_root=runs_root,
        task_roots=[REPO_ROOT / "benchmark"],
        allowed_path_roots=[REPO_ROOT / "benchmark", source_run],
        run_registry=scratch / "runs_registry.json",
        server_profile_store=scratch / "server_profiles.json",
        enable_process_control=True,
        demo_run_ids=[SHOWCASE_RUN_ID],
        poll_interval_ms=250,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()

    scratch = Path(tempfile.mkdtemp(prefix="faultevolve_showcase_"))
    settings = build_settings(scratch)

    from faultevolve.webapi.app import create_app
    import uvicorn

    print(
        f"FaultEvolve showcase API: http://{args.host}:{args.port} "
        f"(run={SHOWCASE_RUN_ID})",
        flush=True,
    )
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
