"""Island runtimes and the coordinator that rotates attempts between them.

One parent experiment owns several islands. Each island keeps its own tree,
selector, operator bandit, repair memory, deferred-evaluation queue and local
best; the coordinator owns only the rotation cursor and the per-island
counters that must survive a restart. Nothing in this module evaluates or
generates -- it holds state and answers "which island runs next".
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any

from faultevolve.common.schemas import IslandState, IslandStatus, SchedulerState
from faultevolve.config import IslandSpec

#: Engine attributes that hold one island's own search state. The engine swaps
#: these when it activates an island, so the single-tree code paths below keep
#: reading ``self.tree`` / ``self._jev_values`` and simply see the active
#: island's object. Attributes absent from this tuple are run-global: the task
#: adapter, store, cost ledger, metrics and LLM client are shared on purpose.
ISLAND_ATTRS: tuple[str, ...] = (
    "tree",
    "selector",
    "_jev_values",
    "_deferred",
    "_op_tokens",
    "_op_rng",
    "_crossover_partners",
    "_offered_insights",
    "_summary_contexts",
    "_summary_applications",
    "error_class_counts",
    "_quota_counts",
    "_plateau_evals_since_improve",
    "_hpo_family_cursor",
    "_hpo_family_trial_index",
    "_hpo_used_fits",
    "_hpo_dev_ctx",
    "_island_focus",
)

#: Soft strategy bias per profile. An island may still reach any operator --
#: ``IslandSpec.exploration_ratio`` reserves part of the choices for that --
#: but these are the operators its profile actually aims at.
PROFILE_OPERATOR_BIAS: dict[str, tuple[str, ...]] = {
    "performance": ("refine", "crossover", "threshold_calibrate"),
    "miss_alert": ("recall_focus", "inject", "refine"),
    "efficiency": ("threshold_calibrate", "refine", "hpo"),
    "custom": (),
}

#: What each profile tells the generator to care about. Task metrics still come
#: from the evaluator; this text only steers which direction to explore.
PROFILE_FOCUS: dict[str, str] = {
    "performance": "优先提升综合指标，允许在多个维度上权衡。",
    "miss_alert": "优先降低漏报与误报：关注假阴性分组与召回-精确率折中。",
    "efficiency": "优先提升效率与稳健性：关注推理耗时、内存与跨窗口稳定性。",
    "custom": "",
}


def profile_focus(profile: str) -> str:
    """Return the documented focus text for a profile (empty for unknown)."""
    return PROFILE_FOCUS.get(profile, "")


def profile_operator_bias(profile: str) -> list[str]:
    """Return the default operator bias for a profile."""
    return list(PROFILE_OPERATOR_BIAS.get(profile, ()))


def apply_profile_defaults(spec: IslandSpec) -> IslandSpec:
    """Fill the focus/operator bias a profile implies, without overwriting
    anything the user already set. Returns the same instance when complete."""
    changed = False
    focus = spec.focus
    if not focus.strip():
        focus = profile_focus(spec.profile)
        changed = True
    bias = list(spec.operator_bias)
    if not bias:
        bias = profile_operator_bias(spec.profile)
        changed = True
    if not changed:
        return spec
    return spec.model_copy(update={"focus": focus, "operator_bias": bias})


def legacy_island_spec() -> IslandSpec:
    """The implicit single island of a pre-island (legacy) run.

    Its id is the empty string because that is what a migrated ``node`` row
    carries; giving it a name would make the legacy tree look empty.
    """
    return IslandSpec(
        island_id="",
        profile="performance",
        focus=profile_focus("performance"),
        max_attempts=10**9,
    )


@dataclass
class IslandRuntime:
    """Everything one island needs to search on its own."""

    spec: IslandSpec
    state: IslandState
    tree: Any = None
    selector: Any = None
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def island_id(self) -> str:
        return self.spec.island_id

    @property
    def profile(self) -> str:
        return self.spec.profile

    @property
    def exhausted(self) -> bool:
        return self.state.attempts >= self.spec.max_attempts

    @property
    def runnable(self) -> bool:
        return (
            self.state.status in (IslandStatus.PENDING, IslandStatus.RUNNING)
            and not self.exhausted
        )

    def load_into(self, engine: Any) -> None:
        """Install this island's state onto the engine."""
        for name, value in self.attrs.items():
            setattr(engine, name, value)

    def store_from(self, engine: Any) -> None:
        """Capture the engine's current island state back into this runtime."""
        for name in ISLAND_ATTRS:
            if hasattr(engine, name):
                self.attrs[name] = getattr(engine, name)


class IslandCoordinator:
    """Round-robin scheduling over islands, with persisted rotation cursor.

    A paused island is skipped but stays in the ring: when it resumes the
    cursor continues from where the ring stands, so it is never starved and
    never mistaken for finished.
    """

    def __init__(
        self,
        experiment_id: str,
        runtimes: list[IslandRuntime],
        store: Any,
        log_event: Any = None,
    ) -> None:
        if not runtimes:
            raise ValueError("coordinator needs at least one island")
        self.experiment_id = experiment_id
        self.runtimes = {rt.island_id: rt for rt in runtimes}
        if len(self.runtimes) != len(runtimes):
            raise ValueError("duplicate island_id in coordinator")
        self.order = [rt.island_id for rt in runtimes]
        self.store = store
        self._log_event = log_event
        self._index = 0
        #: Filled by the engine: the coordinator owns the rotation, the engine owns
        #: the per-island objects the rotation has to resume inside.
        self.rng_snapshot: Any = lambda: {}
        #: Read back by the engine after ``restore_cursor``.
        self.rng_states: dict[str, str] = {}

    @property
    def multi(self) -> bool:
        return len(self.order) > 1

    def runtime(self, island_id: str) -> IslandRuntime:
        rt = self.runtimes.get(island_id)
        if rt is None:
            raise KeyError(f"unknown island {island_id!r}")
        return rt

    def persist_cursor(self) -> None:
        self.store.save_scheduler_state(
            SchedulerState(
                experiment_id=self.experiment_id,
                next_island_index=self._index % len(self.order),
                rng_state_json=self._rng_json(),
                updated_at=_now(),
            )
        )

    def _rng_json(self) -> str:
        """The engine's exploration streams, as far as they can be described.

        Saved next to the cursor because they belong together: which island is up
        and where that island's operator choices had got to are the same piece of
        state seen two ways. A stream that cannot be serialised is saved as absent,
        which resumes as a re-derived seed rather than as a wrong continuation.
        """
        try:
            states = self.rng_snapshot()
        except Exception:
            return ""
        if not states:
            return ""
        return json.dumps(states)

    def restore_cursor(self) -> None:
        state = self.store.get_scheduler_state(self.experiment_id)
        if state is None:
            return
        self._index = state.next_island_index % len(self.order)
        try:
            raw = json.loads(state.rng_state_json) if state.rng_state_json else {}
        except (ValueError, TypeError):
            raw = {}
        self.rng_states = raw if isinstance(raw, dict) else {}

    def runnable_islands(self) -> list[IslandRuntime]:
        return [self.runtime(iid) for iid in self.order if self.runtime(iid).runnable]

    def next_runnable(self) -> IslandRuntime | None:
        """Return the next island to take an attempt, or None to end the run.

        The cursor advances over the skipped islands as it searches, so a
        three-island ring yields A/B/C/A/B/C and, with B paused, A/C/A/C.
        """
        count = len(self.order)
        for step in range(count):
            idx = (self._index + step) % count
            rt = self.runtime(self.order[idx])
            if rt.runnable:
                self._index = (idx + 1) % count
                self.persist_cursor()
                return rt
        return None

    def stop_reasons(self) -> dict[str, str]:
        return {
            iid: self.runtime(iid).state.stop_reason
            for iid in self.order
            if self.runtime(iid).state.stop_reason
        }

    def all_finished(self) -> bool:
        return all(
            self.runtime(iid).state.status == IslandStatus.FINISHED
            for iid in self.order
        )

    def save_state(self, island_id: str) -> None:
        """Persist one island's counters.

        The attempt counter is saved when the attempt starts; evaluation
        outcomes arrive later, inside code that has no idea how many islands
        exist. Saving the active island after each outcome keeps the database
        and the running island's own view of itself in step, so a crash or a
        resume never re-plays evaluations the counters already counted.
        """
        rt = self.runtime(island_id)
        rt.state.updated_at = _now()
        self.store.upsert_island_state(rt.state)

    def save_states(self) -> None:
        for iid in self.order:
            self.save_state(iid)

    def log(self, event: str, payload: dict[str, Any]) -> None:
        if self._log_event is not None:
            self._log_event(event, payload)


def build_runtimes(
    experiment_id: str,
    specs: list[IslandSpec],
    store: Any,
) -> list[IslandRuntime]:
    """Create one runtime per island spec, restoring any persisted state."""
    runtimes: list[IslandRuntime] = []
    for spec in specs:
        existing = store.get_island_state(experiment_id, spec.island_id)
        state = existing or IslandState(
            experiment_id=experiment_id,
            island_id=spec.island_id,
            profile=spec.profile,
            status=IslandStatus.PENDING,
            created_at=_now(),
        )
        runtimes.append(IslandRuntime(spec=spec, state=state))
    return runtimes


def _now() -> str:
    from faultevolve.cloud.store import now_iso

    return now_iso()


def seeded_island_rng(seed: int, island_id: str, offset: int) -> random.Random:
    """Deterministic per-island RNG: same seed plus island name, no cross-talk."""
    return random.Random(f"{seed}:{island_id}:{offset}")
