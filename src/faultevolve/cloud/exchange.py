"""Island-to-island exchange of strategy summaries, never candidate code.

A sibling island may learn *what was tried, under which conditions, and what
the evaluator said*. It may not learn the program that produced it: every text
here is assembled from already-recorded evidence (intent, hypothesis, insight,
error class) and passed through :func:`sanitize`, and every number comes from
the local evaluator rather than from a model. The receiving side only ever
gets the DTOs returned by :meth:`IslandExchange.accept_for`, so the context
builder has no source-code field it could copy.

Delivery and adoption are separate facts. A row in ``exchange_delivery`` means
the target *could* see the summary; ``accepted``/``rejected`` record the
target's own applicability decision with a reason; a row in
``summary_application`` means the summary actually entered one candidate's
prompt, and that candidate's real score is filled in afterwards -- the
summary's own score is never copied onto the candidate.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from faultevolve.cloud.store import Store
from faultevolve.common.schemas import (
    CONFIDENCE_LEVELS,
    NodeStatus,
    SUMMARY_TEXT_MAX_CHARS,
    ExchangeDelivery,
    ExchangeSummary,
    IslandState,
    Node,
    SummaryApplication,
)
from faultevolve.config import IslandsConfig

#: A single line longer than this is a raw trace line or a pasted program, not
#: a method description, so it is dropped instead of being cut mid-sentence.
MAX_LINE_CHARS = 160
#: Overall budget for one summary body (requirements: ~1200 chars).
MAX_SUMMARY_CHARS = SUMMARY_TEXT_MAX_CHARS

_CODE_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`[^`\n]{1,40}`")
_WINDOWS_PATH = re.compile(r"[A-Za-z]:\\[^\s'\"]+")
_POSIX_PATH = re.compile(r"(?:/[\w.+-]+){3,}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?")
_LONG_DIGITS = re.compile(r"\d{6,}")
_WHITESPACE = re.compile(r"\s+")
#: A description arrives either as trace lines or as clauses this module joined
#: with "；"; both are segments, so the length limits apply per segment.
_SEGMENT_SPLIT = re.compile(r"\n|；")
#: Traceback boilerplate carries frame paths and line numbers but no lesson; the
#: classified error type is already in the line above it.
_TRACEBACK_LINE = re.compile(
    r'^\s*(?:File\s+".*?", line \d+.*|Traceback \(most recent call last\):?|line \d+.*|at 0x[0-9a-f]+)\s*$',
    re.I,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def sanitize(text: str) -> str:
    """Reduce free text to an island-safe method description.

    Pasted programs, absolute paths, timestamps and long digit runs (serial
    numbers, disk identifiers) are removed rather than truncated, lines that
    are too long to be a description are dropped whole, and an over-budget body
    loses trailing segments instead of ending mid-sentence.
    """
    if not text:
        return ""
    text = _CODE_FENCE.sub(" [代码已省略] ", text)
    text = _INLINE_CODE.sub(" [代码已省略] ", text)
    text = _WINDOWS_PATH.sub(" [路径已省略] ", text)
    text = _POSIX_PATH.sub(" [路径已省略] ", text)
    text = _TIMESTAMP.sub(" [时间已省略] ", text)
    text = _LONG_DIGITS.sub(" [编号已省略] ", text)

    kept: list[str] = []
    for raw in _SEGMENT_SPLIT.split(text):
        segment = _WHITESPACE.sub(" ", raw).strip()
        if not segment or _TRACEBACK_LINE.match(segment):
            continue
        if len(segment) > MAX_LINE_CHARS:
            continue
        kept.append(segment)
    while len(kept) > 1 and len("；".join(kept)) > MAX_SUMMARY_CHARS:
        # Over budget: drop whole trailing segments. Cutting mid-sentence would
        # leave a half claim for the reader to guess the rest of, which is the
        # one thing a summary must never become.
        kept.pop()
    return "；".join(kept)


def content_hash(kind: str, text: str, conditions: str) -> str:
    """Normalized hash used to deduplicate identical conclusions."""
    normalized = _WHITESPACE.sub(" ", f"{kind}|{text}|{conditions}").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def task_fingerprint(task_spec: Any) -> str:
    """What the islands were asked to solve (problem + instruction text)."""
    parts = "\n".join(
        str(getattr(task_spec, name, "") or "") for name in ("problem_md", "prompt_md")
    )
    if not parts.strip():
        return ""
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


def evaluator_fingerprint(task_spec: Any) -> str:
    """Which scoring program produced the numbers, or "" when unknown.

    An unknown fingerprint is not a match: two summaries with an empty
    fingerprint still deduplicate by content, but a cross-task check cannot be
    claimed, so the reason stays visible instead of pretending compatibility.
    """
    path = getattr(task_spec, "evaluator_path", None)
    if not path:
        return ""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(data).hexdigest()[:16]


def _scalar_metrics(node: Node) -> dict[str, Any]:
    """Numbers the evaluator actually reported, nothing else."""
    evaluation = node.evidence.evaluation
    if evaluation is None:
        return {}
    out: dict[str, Any] = {
        "combined_score": evaluation.combined_score,
        "validity": evaluation.validity,
        "cost_time": evaluation.cost_time,
    }
    if node.evidence.delta_score is not None:
        out["delta_vs_parent"] = node.evidence.delta_score
    metric = evaluation.metric or {}
    for key in ("precision", "recall", "f1", "f1_p10", "ros"):
        value = metric.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = value
    return out


def error_class_of(node: Node) -> str:
    """The classified error kind of a candidate, never the raw trace.

    ``error_info`` can carry a traceback with paths and identifiers, so only the
    leading class token is taken and it still goes through :func:`sanitize`.
    """
    if node.error_class:
        return sanitize(node.error_class)[:60]
    evaluation = node.evidence.evaluation
    if evaluation is not None and evaluation.error_info:
        return sanitize(evaluation.error_info.split(":")[0].strip())[:60] or "unknown"
    return "unknown"


def _next_confidence(current: str) -> str:
    """Independent evidence replicates the conclusion, one step at a time."""
    try:
        index = CONFIDENCE_LEVELS.index(current)
    except ValueError:
        return "single_observation"
    return CONFIDENCE_LEVELS[min(index + 1, len(CONFIDENCE_LEVELS) - 1)]


@dataclass
class SummaryContext:
    """One accepted summary as the receiving island may use it."""

    delivery_id: str
    summary_id: str
    kind: str
    source_island_id: str
    source_node_id: str
    text: str
    conditions: str
    metrics: dict[str, Any]
    created_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "delivery_id": self.delivery_id,
            "summary_id": self.summary_id,
            "kind": self.kind,
            "source_island_id": self.source_island_id,
            "source_node_id": self.source_node_id,
            "summary_text": self.text,
            "conditions": self.conditions,
            "metrics": self.metrics,
        }


@dataclass
class ExchangeOutcome:
    """What one exchange checkpoint did."""

    published: int = 0
    delivered: int = 0
    zero_send: bool = True

    def as_payload(self, island_id: str) -> dict[str, Any]:
        return {
            "island_id": island_id,
            "published": self.published,
            "delivered": self.delivered,
            "zero_send": self.zero_send,
        }


class IslandExchange:
    """Produce, deduplicate and deliver island summaries on its own cursor."""

    def __init__(
        self,
        *,
        store: Store,
        experiment_id: str,
        islands: IslandsConfig,
        log_event: Callable[[str, dict[str, Any]], None],
        task_fp: str = "",
        evaluator_fp: str = "",
    ) -> None:
        self.store = store
        self.experiment_id = experiment_id
        self.islands = islands
        self._log_event = log_event
        self.task_fp = task_fp
        self.evaluator_fp = evaluator_fp

    # ------------------------------------------------------------------
    # cursor (D3.3)
    # ------------------------------------------------------------------

    def due(self, state: IslandState) -> bool:
        """True when this island completed ``exchange_interval`` attempts
        since its last checkpoint. The cursor moves even on a zero send."""
        return state.attempts - state.last_exchange_attempt >= self.islands.exchange_interval

    def _published_best(self, island_id: str) -> tuple[float, str]:
        """Best score this island already announced, with its evidence ref.

        Read back from the store rather than memory, so a resumed run does not
        re-publish the champion it published before the interruption.
        """
        best = (-1.0, "")
        for summary in self.store.get_summaries_by_experiment(self.experiment_id, kinds=("best",)):
            if summary.source_island_id != island_id:
                continue
            score = summary.metrics.get("combined_score")
            if isinstance(score, (int, float)) and score > best[0]:
                best = (float(score), summary.source_node_id)
        return best

    def summarized_nodes(self, island_id: str, kind: str) -> set[str]:
        """Node ids of this island whose failure has already been published."""
        seen: set[str] = set()
        for summary in self.store.get_summaries_by_experiment(self.experiment_id, kinds=(kind,)):
            if summary.source_island_id != island_id:
                continue
            for ref in summary.evidence_refs:
                if ref.startswith("node:"):
                    seen.add(ref[5:])
        return seen

    # ------------------------------------------------------------------
    # publication (D3.1 / D3.2)
    # ------------------------------------------------------------------

    def checkpoint(
        self,
        source: IslandState,
        *,
        best_node: Node | None,
        failed_nodes: list[Node],
        target_islands: list[str],
    ) -> ExchangeOutcome:
        """Run one exchange round for ``source``: repair, publish, then deliver.

        A failure here is recorded and never touches the candidate's real
        score: summaries are derived from evidence that is already stored.
        """
        outcome = ExchangeOutcome()
        try:
            # Repair an unfinished send before starting a new one: a summary this
            # island wrote but never offered is a lesson no sibling can read.
            outcome.delivered += self.backfill_deliveries(source, target_islands)
            if (
                best_node is not None
                and self.islands.max_positive_per_exchange > 0
            ):
                published_score, _ = self._published_best(source.island_id)
                evaluation = best_node.evidence.evaluation
                score = evaluation.combined_score if evaluation else 0.0
                # The shared initialization root is a baseline, not an
                # improvement, and it is the only thing an island has at
                # attempt 0 -- so only a real gain over it may be published.
                if published_score < 0 or score > published_score:
                    summary = self._publish_best(source, best_node, published_score)
                    if summary is not None:
                        outcome.published += 1
                        outcome.delivered += self._deliver(summary, source, target_islands)
            for node in failed_nodes[: self.islands.max_negative_per_exchange]:
                summary = self._publish_failure(source, node)
                if summary is None:
                    continue
                outcome.published += 1
                outcome.delivered += self._deliver(summary, source, target_islands)
        except Exception as exc:  # never let bookkeeping break a real run
            self._log_event("exchange_summary_failed", {
                "island_id": source.island_id,
                "error_type": type(exc).__name__,
                "reason": sanitize(str(exc))[:120],
                "iterations_done": source.attempts,
            })
        outcome.zero_send = outcome.delivered == 0
        self._log_event("exchange_check", outcome.as_payload(source.island_id))
        return outcome

    def share_error(
        self, source: IslandState, node: Node, target_islands: list[str]
    ) -> int:
        """Send one new failure mode immediately, without waiting for the cursor.

        A sibling should not spend an attempt rediscovering a bug this island
        already hit. The content hash and the one-delivery-per-(summary, target)
        rule mean this early channel cannot become a per-attempt broadcast.
        """
        try:
            summary = self._publish_failure(source, node)
            if summary is None:
                return 0
            return self._deliver(summary, source, target_islands)
        except Exception as exc:
            self._log_event("exchange_summary_failed", {
                "island_id": source.island_id,
                "error_type": type(exc).__name__,
                "reason": sanitize(str(exc))[:120],
                "node_id": node.id,
            })
            return 0

    def _new_summary(
        self,
        *,
        kind: str,
        source: IslandState,
        node: Node,
        parts: list[str],
        conditions: str,
        confidence: str,
        metrics: dict[str, Any],
    ) -> ExchangeSummary | None:
        text = sanitize("；".join(p for p in parts if p))
        if not text:
            self._log_event("exchange_summary_failed", {
                "island_id": source.island_id,
                "reason": "empty_after_sanitize",
                "node_id": node.id,
            })
            return None
        digest = content_hash(kind, text, conditions)
        evidence = f"node:{node.id}"
        existing = self.store.get_summary_by_content_hash(self.experiment_id, digest)
        if existing is not None:
            # Same conclusion, new evidence: keep one summary and record the
            # extra source instead of broadcasting a duplicate.
            if evidence not in existing.evidence_refs:
                self.store.add_summary_evidence(
                    existing.summary_id,
                    evidence,
                    _next_confidence(existing.confidence_status),
                    metrics,
                )
                self._log_event("exchange_summary_replicated", {
                    "island_id": source.island_id,
                    "summary_id": existing.summary_id,
                    "evidence_ref": evidence,
                })
            return None
        return ExchangeSummary(
            summary_id=_new_id("sum"),
            experiment_id=self.experiment_id,
            kind=kind,
            source_island_id=source.island_id,
            source_node_id=node.id,
            task_fingerprint=self.task_fp,
            evaluator_fingerprint=self.evaluator_fp,
            summary_text=text,
            conditions=conditions,
            evidence_refs=[evidence],
            metrics=metrics,
            confidence_status=confidence,
            content_hash=digest,
        )

    def _publish_best(
        self, source: IslandState, node: Node, published_score: float
    ) -> ExchangeSummary | None:
        insight_text = ""
        conditions = ""
        for insight in self.store.get_insights_by_experiment(
            self.experiment_id, island_id=source.island_id
        ):
            if insight.origin_node != node.id:
                continue
            insight_text = insight.change_summary or insight.mechanism
            conditions = insight.conditions
            break
        summary = self._new_summary(
            kind="best",
            source=source,
            node=node,
            parts=[
                node.artifact.intent,
                node.artifact.hypothesis,
                insight_text,
            ],
            conditions=conditions,
            confidence="single_observation",
            metrics=_scalar_metrics(node),
        )
        if summary is None:
            return None
        if published_score >= 0:
            summary.metrics["previous_published_best"] = published_score
            summary.metrics["gain_vs_published_best"] = round(
                summary.metrics.get("combined_score", 0.0) - published_score, 4
            )
        if not self.store.create_summary(summary):
            return None
        self._log_event("exchange_summary_published", {
            "island_id": source.island_id,
            "summary_id": summary.summary_id,
            "kind": "best",
            "source_node_id": node.id,
            "score": summary.metrics.get("combined_score"),
        })
        return summary

    def _failure_stats(self, island_id: str, error_class: str) -> dict[str, Any]:
        """Occurrence counts read from stored candidates, not from a model.

        Kept out of the summary body on purpose: the text states the lesson and
        stays stable, so a repeat of the same error adds evidence to the same
        summary instead of broadcasting a new one every attempt.
        """
        occurrences = 0
        repair_attempts = 0
        for node in self.store.get_nodes_by_experiment(
            self.experiment_id, island_id=island_id
        ):
            if node.status != NodeStatus.INVALID or error_class_of(node) != error_class:
                continue
            occurrences += 1
            repair_attempts = max(repair_attempts, node.repair_count)
        return {
            "occurrences": occurrences,
            "repair_attempts": repair_attempts,
        }

    def _publish_failure(self, source: IslandState, node: Node) -> ExchangeSummary | None:
        error_class = error_class_of(node)
        text = (
            f"错误类型 {error_class}"
            f"；发生条件：在岛 {source.island_id} 的方案上扩展时出现"
            "；当前结论：同类写法在该岛不可用，生成新方案时先排除"
        )
        summary = self._new_summary(
            kind="failure",
            source=source,
            node=node,
            parts=[text],
            conditions=f"岛 {source.island_id}",
            confidence="single_observation",
            metrics=self._failure_stats(source.island_id, error_class),
        )
        if summary is None:
            return None
        if not self.store.create_summary(summary):
            return None
        self._log_event("exchange_summary_published", {
            "island_id": source.island_id,
            "summary_id": summary.summary_id,
            "kind": "failure",
            "source_node_id": node.id,
            "error_class": error_class,
        })
        return summary

    # ------------------------------------------------------------------
    # delivery (D3.3 / D3.4)
    # ------------------------------------------------------------------

    def _deliver(
        self, summary: ExchangeSummary, source: IslandState, target_islands: list[str]
    ) -> int:
        sent = 0
        for target in target_islands:
            if target == source.island_id:
                continue
            delivery = ExchangeDelivery(
                delivery_id=_new_id("dlv"),
                experiment_id=self.experiment_id,
                summary_id=summary.summary_id,
                source_island_id=source.island_id,
                target_island_id=target,
                status="offered",
            )
            if self.store.create_delivery(delivery):
                sent += 1
                self._log_event("exchange_delivered", {
                    "summary_id": summary.summary_id,
                    "delivery_id": delivery.delivery_id,
                    "from": source.island_id,
                    "to": target,
                    "kind": summary.kind,
                })
        return sent

    def backfill_deliveries(
        self, source: IslandState, target_islands: list[str]
    ) -> int:
        """Offer what this island published but never got out.

        Writing a summary and offering it are two inserts, so a process can die
        between them and leave a lesson in the database that no sibling can ever
        read -- and the content-hash dedup means the next round will not re-publish
        it, so nothing would repair it on its own. The gap is looked up rather than
        remembered: a summary of this island with no delivery row for a target that
        is *still* actionable is offered now. The one-delivery-per-(summary, target)
        key makes this idempotent, so a backfill can never become a re-broadcast, and
        a target that stopped for its own reasons is not in ``target_islands``.
        """
        delivered = {
            (row.summary_id, row.target_island_id)
            for row in self.store.get_deliveries(self.experiment_id)
        }
        sent = 0
        for summary in self.store.get_summaries_by_experiment(self.experiment_id):
            if summary.source_island_id != source.island_id:
                continue
            for target in target_islands:
                if target == source.island_id:
                    continue
                if (summary.summary_id, target) in delivered:
                    continue
                delivery = ExchangeDelivery(
                    delivery_id=_new_id("dlv"),
                    experiment_id=self.experiment_id,
                    summary_id=summary.summary_id,
                    source_island_id=source.island_id,
                    target_island_id=target,
                    status="offered",
                )
                if self.store.create_delivery(delivery):
                    sent += 1
                    delivered.add((summary.summary_id, target))
                    self._log_event("exchange_delivery_backfilled", {
                        "island_id": source.island_id,
                        "summary_id": summary.summary_id,
                        "delivery_id": delivery.delivery_id,
                        "to": target,
                        "kind": summary.kind,
                        "source_node_id": summary.source_node_id,
                    })
        return sent

    # ------------------------------------------------------------------
    # adoption (D3.4)
    # ------------------------------------------------------------------

    def accept_for(
        self,
        island_id: str,
        *,
        runnable: bool,
        best_score: float,
    ) -> list[SummaryContext]:
        """Decide applicability of everything offered to this island.

        Offered means visible, not adopted: each delivery becomes ``accepted``
        or ``rejected`` here, with the reason kept so a report can say why a
        summary was ignored. An already accepted delivery stays reusable --
        adoption is not a one-shot token -- so the queue is re-read every
        generation and capped by ``max_summaries_in_context`` instead of
        letting history pile up in the prompt.
        """
        inbox: list[tuple[ExchangeDelivery, ExchangeSummary]] = []
        for delivery in self.store.get_deliveries(
            self.experiment_id,
            target_island_id=island_id,
            statuses=("offered", "accepted"),
        ):
            summary = self.store.get_summary(delivery.summary_id)
            if summary is not None:
                inbox.append((delivery, summary))
        ceiling = self._best_ceiling(inbox)

        contexts: list[SummaryContext] = []
        for delivery, summary in inbox:
            if delivery.status == "offered":
                reason = self._rejection_reason(
                    summary, runnable=runnable, ceiling=ceiling
                )
                if reason:
                    self.store.update_delivery_decision(
                        delivery.delivery_id, "rejected", reason
                    )
                    self._log_event("exchange_rejected", {
                        "island_id": island_id,
                        "summary_id": summary.summary_id,
                        "delivery_id": delivery.delivery_id,
                        "reason": reason,
                    })
                    continue
                self.store.update_delivery_decision(
                    delivery.delivery_id, "accepted", "applicable"
                )
            contexts.append(SummaryContext(
                delivery_id=delivery.delivery_id,
                summary_id=summary.summary_id,
                kind=summary.kind,
                source_island_id=summary.source_island_id,
                source_node_id=summary.source_node_id,
                text=summary.summary_text,
                conditions=summary.conditions,
                metrics=summary.metrics,
                created_at=summary.created_at,
            ))
        # Newest first, then relevance: the stable second sort keeps arrival
        # order inside each relevance group instead of flattening it.
        contexts.sort(key=lambda item: item.created_at, reverse=True)
        contexts.sort(key=lambda item: self._rank(item, best_score))
        return contexts[: self.islands.max_summaries_in_context]

    @staticmethod
    def _best_ceiling(
        inbox: list[tuple[ExchangeDelivery, ExchangeSummary]]
    ) -> dict[str, float]:
        """Highest score each sibling has announced, per source island.

        The source publishes its best as it improves, so an older 'best' summary
        in the queue is already overtaken -- keeping it would let the receiver
        graft a method its own author abandoned.
        """
        ceiling: dict[str, float] = {}
        for _, summary in inbox:
            if summary.kind != "best":
                continue
            score = summary.metrics.get("combined_score")
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                current = ceiling.get(summary.source_island_id)
                if current is None or float(score) > current:
                    ceiling[summary.source_island_id] = float(score)
        return ceiling

    def _rejection_reason(
        self,
        summary: ExchangeSummary,
        *,
        runnable: bool,
        ceiling: dict[str, float],
    ) -> str:
        if not runnable:
            return "target_island_not_runnable"
        if self.task_fp and summary.task_fingerprint and self.task_fp != summary.task_fingerprint:
            return "task_fingerprint_mismatch"
        if (
            self.evaluator_fp
            and summary.evaluator_fingerprint
            and self.evaluator_fp != summary.evaluator_fingerprint
        ):
            return "evaluator_fingerprint_mismatch"
        top = ceiling.get(summary.source_island_id)
        score = summary.metrics.get("combined_score")
        if (
            summary.kind == "best"
            and top is not None
            and isinstance(score, (int, float))
            and not isinstance(score, bool)
            and float(score) < top
        ):
            return "superseded_by_newer_best"
        return ""

    @staticmethod
    def _rank(item: SummaryContext, best_score: float) -> tuple[float, float]:
        """Relevance first: a sibling that is genuinely ahead leads the queue.

        A 'best' summary that still beats this island's own best is the one most
        worth grafting; everything else keeps arrival order through the stable
        sort above rather than being buried under an old conclusion.
        """
        score = item.metrics.get("combined_score")
        gain = (
            float(score) - best_score
            if isinstance(score, (int, float)) and not isinstance(score, bool)
            else -1.0
        )
        return (0.0 if item.kind == "best" and gain > 0 else 1.0, -gain)

    def record_applications(self, items: list[SummaryContext], candidate_node_id: str) -> list[str]:
        """Mark the summaries that entered this candidate's prompt as applied."""
        applied: list[str] = []
        for item in items:
            application = SummaryApplication(
                application_id=_new_id("app"),
                delivery_id=item.delivery_id,
                experiment_id=self.experiment_id,
                candidate_node_id=candidate_node_id,
            )
            if self.store.record_application(application):
                applied.append(application.application_id)
                self._log_event("exchange_applied", {
                    "summary_id": item.summary_id,
                    "delivery_id": item.delivery_id,
                    "candidate_node_id": candidate_node_id,
                    "kind": item.kind,
                    "from": item.source_island_id,
                })
        return applied

    def complete_applications(
        self, application_ids: list[str], *, evaluation_id: str, score: float | None
    ) -> None:
        """Attach the candidate's own real result to each application row."""
        for application_id in application_ids:
            self.store.complete_application(application_id, evaluation_id, score)
