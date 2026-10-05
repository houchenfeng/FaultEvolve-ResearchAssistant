"""Stable error codes returned by the Web API.

Front-end code keys its Chinese message table off these values, so the set is
append-only: never rename or remove a code, only add new ones.
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """Machine-readable error identifiers."""

    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"

    # request validation
    INVALID_REQUEST = "request.invalid"
    PATH_NOT_ALLOWED = "path.not_allowed"
    PATH_NOT_FOUND = "path.not_found"
    PATH_NOT_DIRECTORY = "path.not_directory"

    # run artifacts
    RUN_NOT_FOUND = "run.not_found"
    RUN_UNREADABLE = "run.unreadable"
    ARTIFACT_MISSING = "artifact.missing"
    ARTIFACT_INVALID_JSON = "artifact.invalid_json"
    ARTIFACT_NOT_DOWNLOADABLE = "artifact.not_downloadable"
    NODE_NOT_FOUND = "node.not_found"

    # task catalogue (phase 4)
    TASK_NOT_FOUND = "task.not_found"
    TASK_NOT_READY = "task.not_ready"

    # execution targets (phase 4)
    SERVER_NOT_FOUND = "server.not_found"

    # evolution presets (phase 4)
    PRESET_UNKNOWN = "preset.unknown"
    PRESET_INVALID = "preset.invalid"

    # capability gaps -- reported instead of faking a feature
    NOT_SUPPORTED = "not_supported"

    # execution backends
    BACKEND_UNAVAILABLE = "backend.unavailable"
    BACKEND_AUTH_FAILED = "backend.auth_failed"
    BACKEND_HOST_KEY_MISMATCH = "backend.host_key_mismatch"
    ENVIRONMENT_NOT_READY = "environment.not_ready"
    LLM_KEY_MISSING = "llm.key_missing"

    # fallback
    INTERNAL = "internal"


#: Error codes that mean "this capability does not exist yet", as opposed to
#: "your request was wrong". The UI disables the control instead of retrying.
UNSUPPORTED_CODES: frozenset[ErrorCode] = frozenset({ErrorCode.NOT_SUPPORTED})


class WebApiError(Exception):
    """Domain error carrying the HTTP status and the stable code.

    Every handler raises one of these instead of ``HTTPException`` so the reply
    shape is decided in one place (``app._error_response``) and no message can
    accidentally carry a host path or a key fragment.
    """

    error_code: ErrorCode = ErrorCode.INTERNAL
    http_status: int = 500
    #: Chinese text shown to the user. Never built from user input.
    message_zh: str = "服务内部错误"
    #: Extra machine-readable context. Must not contain paths or secrets.
    detail: str | None = None
    #: Request field the error belongs to, for form-level UI highlighting.
    field: str | None = None

    def __init__(
        self,
        *,
        message_zh: str | None = None,
        detail: str | None = None,
        field: str | None = None,
    ) -> None:
        self.detail = detail if detail is not None else self.detail
        self.field = field
        if message_zh is not None:
            self.message_zh = message_zh
        super().__init__(f"{self.error_code.value}: {self.message_zh}")


class InvalidQwenConfigError(WebApiError):
    error_code = ErrorCode.INVALID_REQUEST
    http_status = 422
    message_zh = "Qwen Base URL 格式不正确"


class InvalidIdentifierError(WebApiError):
    """A path parameter failed the character whitelist (TODO §2.3)."""

    error_code = ErrorCode.INVALID_REQUEST
    http_status = 400
    message_zh = "标识符不合法"

    def __init__(self, kind: str, field: str | None = None) -> None:
        # The offending value is deliberately *not* echoed back: it is attacker
        # input and may contain a path fragment.
        super().__init__(detail=f"{kind} must match the allowed id pattern", field=field)
        self.kind = kind


class RunNotFoundError(WebApiError):
    """No run directory with that id under the configured roots."""

    error_code = ErrorCode.RUN_NOT_FOUND
    http_status = 404
    message_zh = "找不到该运行"

    def __init__(self, run_id: str) -> None:
        super().__init__(field="run_id")
        self.run_id = run_id


class RunUnreadableError(WebApiError):
    """The run directory exists but nothing in it can be read."""

    error_code = ErrorCode.RUN_UNREADABLE
    http_status = 500
    message_zh = "该运行的数据无法读取"

    def __init__(self, run_id: str, detail: str | None = None) -> None:
        super().__init__(detail=detail or "no readable artifact in the run directory")
        self.run_id = run_id


class ArtifactInvalidJsonError(WebApiError):
    """A JSON artifact exists but cannot be parsed (TODO §2.3)."""

    error_code = ErrorCode.ARTIFACT_INVALID_JSON
    http_status = 500
    message_zh = "该运行的数据文件已损坏"

    def __init__(self, name: str) -> None:
        # Only the artifact's *name* travels; never its resolved path.
        super().__init__(detail=f"{name} is not valid JSON")
        self.name = name


class ArtifactMissingError(WebApiError):
    """An artifact id that the server never minted."""

    error_code = ErrorCode.ARTIFACT_MISSING
    http_status = 404
    message_zh = "找不到该制品"

    def __init__(self, artifact_id: str) -> None:
        super().__init__(field="artifact_id")
        self.artifact_id = artifact_id


class ArtifactNotDownloadableError(WebApiError):
    """A registered artifact that this build refuses to serve as a download."""

    error_code = ErrorCode.ARTIFACT_NOT_DOWNLOADABLE
    http_status = 403
    message_zh = "该制品不提供下载"

    def __init__(self, artifact_id: str, reason: str = "") -> None:
        super().__init__(detail=reason or "download disabled for this artifact kind")
        self.artifact_id = artifact_id


class NodeNotFoundError(WebApiError):
    """No such node in this run's tree."""

    error_code = ErrorCode.NODE_NOT_FOUND
    http_status = 404
    message_zh = "找不到该节点"

    def __init__(self, node_id: str) -> None:
        super().__init__(field="node_id")
        self.node_id = node_id


class CapabilityNotSupportedError(WebApiError):
    """The capability does not exist in this build (TODO §15).

    Raised rather than returning a plausible-looking fake. ``reason`` is the
    text the UI shows next to the disabled control, so it must say *why*.
    """

    error_code = ErrorCode.NOT_SUPPORTED
    http_status = 501
    message_zh = "当前版本不支持该能力"

    def __init__(self, reason: str) -> None:
        super().__init__(detail=reason)


class TaskNotFoundError(WebApiError):
    """No task directory with that id under ``WebSettings.task_roots``."""

    error_code = ErrorCode.TASK_NOT_FOUND
    http_status = 404
    message_zh = "找不到该任务"

    def __init__(self, task_id: str) -> None:
        super().__init__(field="task_id")
        self.task_id = task_id


class TaskNotReadyError(WebApiError):
    """Pre-flight found blocking problems, so the task cannot be used yet."""

    error_code = ErrorCode.TASK_NOT_READY
    http_status = 409
    message_zh = "该任务尚未就绪"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail=detail or "task readiness check failed")


class ServerNotFoundError(WebApiError):
    """No stored execution profile with that id."""

    error_code = ErrorCode.SERVER_NOT_FOUND
    http_status = 404
    message_zh = "找不到该服务器配置"

    def __init__(self, profile_id: str) -> None:
        super().__init__(field="profile_id")
        self.profile_id = profile_id


class PresetUnknownError(WebApiError):
    """A preset name this build does not define."""

    error_code = ErrorCode.PRESET_UNKNOWN
    http_status = 400
    message_zh = "未知的进化强度预设"

    def __init__(self, preset: str) -> None:
        # Only a fixed reason string travels: the name is attacker input.
        super().__init__(detail="unknown preset name", field="preset")
        self.preset = preset


class PresetInvalidError(WebApiError):
    """Merging the client patch produced a config ``EvolveConfig`` rejects.

    Only the offending *field names* travel, never the values: a value could
    carry a path or a key fragment.
    """

    error_code = ErrorCode.PRESET_INVALID
    http_status = 422
    message_zh = "配置合并后不合法"

    def __init__(self, fields: list[str]) -> None:
        super().__init__(detail="; ".join(fields) or "invalid configuration")
        self.fields = fields


class RunControlConflictError(WebApiError):
    """A lifecycle action that cannot be honoured in the current state.

    Pausing is the canonical case: the engine has no safe point to stop at, so
    the honest reply is a conflict carrying the reason -- never a 200 that
    quietly did nothing (TODO 7.4).
    """

    #: ``not_supported`` so the UI disables the control instead of retrying it.
    error_code = ErrorCode.NOT_SUPPORTED
    #: 409 rather than 501: the route exists and the request is well-formed;
    #: it is the run's state (or the engine's capability) that refuses.
    http_status = 409
    message_zh = "该生命周期操作当前不可用"

    def __init__(self, reason: str) -> None:
        super().__init__(detail=reason)


class RunNotRegisteredError(WebApiError):
    """No registry row claims this run id.

    Deliberately distinct from ``RunNotFoundError``: the run's artifacts may be
    perfectly readable, it just was not started by *this* service, so the
    lifecycle controls have nothing to act on.
    """

    error_code = ErrorCode.RUN_NOT_FOUND
    http_status = 404
    message_zh = "该运行不是由本服务启动的"

    def __init__(self, run_id: str) -> None:
        super().__init__(field="run_id")
        self.run_id = run_id
