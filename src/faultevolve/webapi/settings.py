"""Web service settings and path allow-listing (TODO §2.2).

Deliberately a plain object that the caller constructs: nothing here reads the
environment at import time, and no secret is ever resolved into a field. Keys are
addressed by *name* (``api_token_env``) and looked up at request time.

Every filesystem path handed to the API is resolved and then checked against
``allowed_path_roots``, which is what makes traversal and holdout reads
impossible rather than merely discouraged.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PathNotAllowedError(Exception):
    """Raised when a path escapes the configured allow-list."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"path is outside the allowed roots: {path}")
        self.path = path


def _empty_paths() -> list[Path]:
    return []


class WebSettings(BaseSettings):
    """Runtime configuration of the Web API layer."""

    model_config = SettingsConfigDict(
        env_prefix="FE_WEB_",
        env_file=None,
        extra="forbid",
    )

    # --- artifact roots -----------------------------------------------------
    runs_root: Path | None = None
    artifacts_root: Path | None = None
    task_roots: list[Path] = Field(default_factory=_empty_paths)
    allowed_path_roots: list[Path] = Field(default_factory=_empty_paths)

    # --- behaviour ----------------------------------------------------------
    poll_interval_ms: int = Field(default=1000, gt=0)
    enable_process_control: bool = False
    demo_run_ids: list[str] = Field(default_factory=list)

    # --- auth ---------------------------------------------------------------
    #: *Name* of the env var holding the single-user API token. The value itself
    #: is never stored on this object.
    api_token_env: str = "FE_API_KEY"

    # --- execution targets --------------------------------------------------
    server_profile_store: Path | None = None
    ssh_known_hosts: Path | None = None
    #: Ledger of the runs this service started (TODO 7.2). Unset means the write
    #: side of the API has nowhere to record a run, so launching is reported as
    #: unavailable rather than attempted and half-done.
    run_registry: Path | None = None

    def allowed_roots(self) -> list[Path]:
        """Resolved allow-list, including the artifact roots themselves."""
        roots = list(self.allowed_path_roots)
        for candidate in (self.runs_root, self.artifacts_root,
                          self.server_profile_store, self.ssh_known_hosts,
                          self.run_registry):
            if candidate is not None:
                roots.append(candidate.parent if candidate.suffix else candidate)
        for task_root in self.task_roots:
            roots.append(task_root)
        resolved: list[Path] = []
        for root in roots:
            try:
                resolved.append(root.resolve())
            except OSError:
                continue
        return resolved

    def ensure_allowed(self, path: Path) -> Path:
        """Resolve ``path`` and assert it sits under an allowed root.

        Returns the resolved path so callers cannot accidentally keep using the
        unresolved one.
        """
        try:
            resolved = path.resolve()
        except OSError as exc:
            raise PathNotAllowedError(path) from exc
        roots = self.allowed_roots()
        if not roots:
            # No roots configured means "nothing is reachable", not "everything".
            raise PathNotAllowedError(path)
        for root in roots:
            if resolved == root or root in resolved.parents:
                return resolved
        raise PathNotAllowedError(path)

    def is_allowed(self, path: Path) -> bool:
        """Non-raising variant of :meth:`ensure_allowed`."""
        try:
            self.ensure_allowed(path)
        except PathNotAllowedError:
            return False
        return True

    def token_required(self) -> bool:
        """Whether auth is enforced. Looked up lazily, never at import."""
        import os

        return bool(os.environ.get(self.api_token_env))
