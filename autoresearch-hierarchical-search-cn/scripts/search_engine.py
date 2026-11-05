from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass, field
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def oriented(value: float, direction: str) -> float:
    return value if direction == "maximize" else -value


def directional_improvement(score: float, baseline: float, direction: str) -> float:
    return score - baseline if direction == "maximize" else baseline - score


@dataclass
class EvaluationResult:
    succeeded: bool
    score: float | None
    samples: list[float]
    duration_seconds: float
    integrity_passed: bool
    evidence: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


@dataclass
class Candidate:
    candidate_id: str
    route_id: str
    parent_id: str | None
    parameters: dict[str, Any]
    changed_parameter: str | None
    depth: int
    backprop_path: list[str]
    status: str = "pending"
    score: float | None = None
    duration_seconds: float = 0.0
    visits: int = 0
    virtual_visits: int = 0
    reward_sum: float = 0.0
    selection: dict[str, Any] = field(default_factory=dict)
    execution_id: str | None = None
    dispatch_order: int | None = None

    @property
    def mean_reward(self) -> float:
        return self.reward_sum / self.visits if self.visits else 0.0


class SearchEngine:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self._validate_spec()
        self.contract_hash = stable_hash(spec)
        self.direction = spec["metric"]["direction"]
        self.min_delta = float(spec["metric"].get("min_delta", 0.0))
        self.target = spec["metric"].get("target")
        self.max_trials = int(spec["budgets"]["max_trials"])
        self.routes = {route["id"]: route for route in spec["routes"]}
        self.route_order = [route["id"] for route in spec["routes"]]
        self.candidates: dict[str, Candidate] = {}
        self.root_ids: dict[str, str] = {}
        self.route_visits = {route_id: 0 for route_id in self.route_order}
        self.route_virtual_visits = {route_id: 0 for route_id in self.route_order}
        self.route_rewards: dict[str, list[float]] = {route_id: [] for route_id in self.route_order}
        self.trials: list[dict[str, Any]] = []
        self.dispatch_count = 0
        self.completion_count = 0
        self.best_candidate_id: str | None = None
        self.stop_reason: str | None = None
        self.default_barrier_open = False
        self._register_roots()

    def _validate_spec(self) -> None:
        routes = self.spec.get("routes")
        single = self.spec.get("search", {}).get("allow_single_route", False)
        if not isinstance(routes, list) or len(routes) < (1 if single else 2):
            raise ValueError("routes 必须至少包含两条方法路线")
        route_ids = [route.get("id") for route in routes]
        if any(not route_id for route_id in route_ids) or len(route_ids) != len(set(route_ids)):
            raise ValueError("route.id 不能为空且必须唯一")
        metric = self.spec.get("metric", {})
        if metric.get("direction") not in {"maximize", "minimize"}:
            raise ValueError("metric.direction 必须是 maximize 或 minimize")
        budgets = self.spec.get("budgets", {})
        if int(budgets.get("max_trials", 0)) < len(routes):
            raise ValueError("max_trials 不能小于路线默认配置数量")
        if int(budgets.get("max_wall_seconds", 0)) <= 0:
            raise ValueError("max_wall_seconds 必须大于 0")
        if int(budgets.get("max_parallel_trials", 0)) <= 0:
            raise ValueError("max_parallel_trials 必须大于 0")
        for route in routes:
            defaults = route.get("default_parameters")
            domains = route.get("parameter_domains")
            if not isinstance(defaults, dict) or not isinstance(domains, dict) or (not domains and not single):
                raise ValueError(f"路线 {route['id']} 缺少默认参数或参数域")
            for key, values in domains.items():
                if not isinstance(values, list) or not values:
                    raise ValueError(f"路线 {route['id']} 的参数 {key} 必须有非空离散域")
                if key not in defaults or defaults[key] not in values:
                    raise ValueError(f"路线 {route['id']} 的默认参数 {key} 不在参数域中")

    def _register_roots(self) -> None:
        for route_id in self.route_order:
            parameters = dict(self.routes[route_id]["default_parameters"])
            candidate = self._make_candidate(route_id, None, parameters, None, 0, [])
            candidate.backprop_path = [candidate.candidate_id]
            self.candidates[candidate.candidate_id] = candidate
            self.root_ids[route_id] = candidate.candidate_id

    def _make_candidate(
        self,
        route_id: str,
        parent_id: str | None,
        parameters: dict[str, Any],
        changed_parameter: str | None,
        depth: int,
        parent_path: list[str],
    ) -> Candidate:
        candidate_id = stable_hash(
            {
                "contract_version": self.spec.get("version", "experiment.spec/v1"),
                "route_id": route_id,
                "parameters": parameters,
            }
        )[:20]
        return Candidate(
            candidate_id=candidate_id,
            route_id=route_id,
            parent_id=parent_id,
            parameters=dict(parameters),
            changed_parameter=changed_parameter,
            depth=depth,
            backprop_path=[*parent_path, candidate_id],
        )

    def _all_defaults_terminal(self) -> bool:
        return all(
            self.candidates[root_id].status in {"evaluated", "failed"}
            for root_id in self.root_ids.values()
        )

    def _open_default_barrier(self) -> None:
        if self.default_barrier_open or not self._all_defaults_terminal():
            return
        self.default_barrier_open = True
        roots = [self.candidates[root_id] for root_id in self.root_ids.values()]
        scored = [candidate for candidate in roots if candidate.score is not None]
        if scored:
            self.best_candidate_id = max(
                scored,
                key=lambda candidate: (oriented(candidate.score or 0.0, self.direction), candidate.candidate_id),
            ).candidate_id

    def _target_reached(self) -> bool:
        if not self.default_barrier_open or self.target is None or self.best_candidate_id is None:
            return False
        best_score = self.candidates[self.best_candidate_id].score
        if best_score is None:
            return False
        return best_score >= float(self.target) if self.direction == "maximize" else best_score <= float(self.target)

    def can_dispatch(self, elapsed_seconds: float) -> bool:
        if self.stop_reason is not None:
            return False
        self._open_default_barrier()
        if self._target_reached():
            self.stop_reason = "target_score_reached"
            return False
        if self.dispatch_count >= self.max_trials:
            self.stop_reason = "trial_budget_exhausted"
            return False
        if elapsed_seconds >= float(self.spec["budgets"]["max_wall_seconds"]):
            self.stop_reason = "wall_time_budget_exhausted"
            return False
        return True

    def reserve_next(self, elapsed_seconds: float) -> Candidate | None:
        if not self.can_dispatch(elapsed_seconds):
            return None

        if not self.default_barrier_open:
            for route_id in self.route_order:
                root = self.candidates[self.root_ids[route_id]]
                if root.status == "pending":
                    return self._reserve(root, {"phase": "default_route_evaluation"})
            return None

        route_options: list[tuple[float, int, str, list[Candidate], dict[str, Any]]] = []
        for route_index, route_id in enumerate(self.route_order):
            frontier = self._active_frontier(route_id)
            if not frontier:
                continue
            details = self._route_score(route_id)
            route_options.append((details["score"], -self.route_visits[route_id], route_id, frontier, details))

        if not route_options:
            return None

        _, _, route_id, frontier, route_details = max(
            route_options,
            key=lambda item: (item[0], item[1], -self.route_order.index(item[2])),
        )
        parent, node_details = self._select_parent(route_id, frontier)
        child = self._next_unseen_child(parent)
        if child is None:
            return None
        self.candidates[child.candidate_id] = child
        selection = {
            "phase": "parameter_search",
            "frontier_kind": "beam" if parent.selection.get("beam_rank") else "exploration",
            "beam_rank": parent.selection.get("beam_rank", 0),
            "route": route_details,
            "node": node_details,
        }
        return self._reserve(child, selection)

    def _reserve(self, candidate: Candidate, selection: dict[str, Any]) -> Candidate:
        self.dispatch_count += 1
        candidate.status = "running"
        candidate.dispatch_order = self.dispatch_count
        candidate.execution_id = f"execution-{self.dispatch_count:04d}-{candidate.candidate_id[:8]}"
        candidate.selection = selection
        for node_id in candidate.backprop_path:
            self.candidates[node_id].virtual_visits += 1
        self.route_virtual_visits[candidate.route_id] += 1
        return candidate

    def _candidate_sort_key(self, candidate: Candidate) -> tuple[float, float, str]:
        assert candidate.score is not None
        return (-oriented(candidate.score, self.direction), candidate.duration_seconds, candidate.candidate_id)

    def _active_frontier(self, route_id: str) -> list[Candidate]:
        eligible = [
            candidate
            for candidate in self.candidates.values()
            if candidate.route_id == route_id
            and candidate.status == "evaluated"
            and candidate.score is not None
            and self._has_unseen_child(candidate)
        ]
        if not eligible:
            return []
        eligible.sort(key=self._candidate_sort_key)
        beam_width = int(self.spec.get("search", {}).get("beam_width", 3))
        exploration_slots = int(self.spec.get("search", {}).get("exploration_slots", 1))
        beam = eligible[:beam_width]
        for rank, candidate in enumerate(beam, start=1):
            candidate.selection["beam_rank"] = rank
        beam_ids = {candidate.candidate_id for candidate in beam}
        exploration_pool = [candidate for candidate in eligible if candidate.candidate_id not in beam_ids]
        exploration_pool.sort(key=lambda candidate: (candidate.visits + candidate.virtual_visits, candidate.candidate_id))
        return beam + exploration_pool[:exploration_slots]

    def _route_score(self, route_id: str) -> dict[str, Any]:
        search = self.spec.get("search", {})
        top_k = max(1, int(search.get("beam_width", 3)))
        rewards = sorted(self.route_rewards[route_id], reverse=True)[:top_k]
        prior = search.get("route_priors", {}).get(route_id, {})
        prior_visits = min(0.75, max(0.0, float(prior.get("visits", 0.0))))
        prior_reward = float(prior.get("reward", 0.0))
        denominator = len(rewards) + prior_visits
        quality = (sum(rewards) + prior_reward * prior_visits) / denominator if denominator else 0.0
        total = sum(self.route_visits.values()) + sum(self.route_virtual_visits.values())
        effective = self.route_visits[route_id] + self.route_virtual_visits[route_id] + prior_visits
        c_route = float(search.get("route_exploration_c", 0.35))
        virtual_penalty = float(search.get("virtual_visit_penalty", 0.05))
        exploration = c_route * math.sqrt(math.log(max(2.0, float(total))) / max(1.0, effective))
        penalty = virtual_penalty * self.route_virtual_visits[route_id]
        return {
            "route_id": route_id,
            "quality": quality,
            "exploration_bonus": exploration,
            "virtual_penalty": penalty,
            "real_visits": self.route_visits[route_id],
            "virtual_visits": self.route_virtual_visits[route_id],
            "prior_reward": prior_reward,
            "prior_visits": prior_visits,
            "score": quality + exploration - penalty,
        }

    def _select_parent(self, route_id: str, frontier: list[Candidate]) -> tuple[Candidate, dict[str, Any]]:
        search = self.spec.get("search", {})
        c_node = float(search.get("node_exploration_c", 0.35))
        virtual_penalty = float(search.get("virtual_visit_penalty", 0.05))
        route_visits = max(2, self.route_visits[route_id] + self.route_virtual_visits[route_id])
        options: list[tuple[float, Candidate, dict[str, Any]]] = []
        for candidate in frontier:
            exploration = c_node * math.sqrt(
                math.log(float(route_visits)) / max(1, candidate.visits + candidate.virtual_visits)
            )
            penalty = virtual_penalty * candidate.virtual_visits
            details = {
                "parent_id": candidate.candidate_id,
                "mean_reward": candidate.mean_reward,
                "exploration_bonus": exploration,
                "virtual_penalty": penalty,
                "visits": candidate.visits,
                "virtual_visits": candidate.virtual_visits,
                "score": candidate.mean_reward + exploration - penalty,
            }
            options.append((details["score"], candidate, details))
        _, candidate, details = max(options, key=lambda item: (item[0], -item[1].visits, item[1].candidate_id))
        return candidate, details

    def _possible_children(self, parent: Candidate) -> list[Candidate]:
        route = self.routes[parent.route_id]
        children: list[Candidate] = []
        for key in sorted(route["parameter_domains"]):
            values = route["parameter_domains"][key]
            current = parent.parameters[key]
            index = values.index(current)
            neighbor_indexes = [candidate_index for candidate_index in (index - 1, index + 1) if 0 <= candidate_index < len(values)]
            for neighbor_index in neighbor_indexes:
                parameters = dict(parent.parameters)
                parameters[key] = values[neighbor_index]
                children.append(
                    self._make_candidate(
                        parent.route_id,
                        parent.candidate_id,
                        parameters,
                        key,
                        parent.depth + 1,
                        parent.backprop_path,
                    )
                )
        children.sort(key=lambda candidate: (candidate.changed_parameter or "", canonical_json(candidate.parameters)))
        return children

    def _has_unseen_child(self, parent: Candidate) -> bool:
        return any(child.candidate_id not in self.candidates for child in self._possible_children(parent))

    def _next_unseen_child(self, parent: Candidate) -> Candidate | None:
        return next(
            (child for child in self._possible_children(parent) if child.candidate_id not in self.candidates),
            None,
        )

    def record_result(self, candidate_id: str, result: EvaluationResult) -> dict[str, Any]:
        candidate = self.candidates[candidate_id]
        if candidate.status != "running":
            raise ValueError(f"候选 {candidate_id} 当前状态不是 running")
        for node_id in candidate.backprop_path:
            self.candidates[node_id].virtual_visits = max(0, self.candidates[node_id].virtual_visits - 1)
        self.route_virtual_visits[candidate.route_id] = max(0, self.route_virtual_visits[candidate.route_id] - 1)

        candidate.status = "evaluated" if result.succeeded and result.integrity_passed else "failed"
        candidate.score = result.score if candidate.status == "evaluated" else None
        candidate.duration_seconds = result.duration_seconds
        reward = self._reward(candidate, result)
        self.route_visits[candidate.route_id] += 1
        self.route_rewards[candidate.route_id].append(reward)
        for node_id in candidate.backprop_path:
            node = self.candidates[node_id]
            node.visits += 1
            node.reward_sum += reward

        best_before = self.best_candidate_id
        decision = self._decision(candidate, result)
        if candidate.depth > 0 and decision["status"] == "keep":
            self.best_candidate_id = candidate.candidate_id
        self.completion_count += 1
        self._open_default_barrier()

        record = {
            "contract_hash": self.contract_hash,
            "trial_number": candidate.dispatch_order,
            "candidate_id": candidate.candidate_id,
            "route_id": candidate.route_id,
            "parent_id": candidate.parent_id,
            "depth": candidate.depth,
            "changed_parameter": candidate.changed_parameter,
            "parameters": candidate.parameters,
            "selection": candidate.selection,
            "execution": {
                "execution_id": candidate.execution_id,
                "dispatch_order": candidate.dispatch_order,
                "completion_order": self.completion_count,
                "duration_seconds": result.duration_seconds,
                "status": candidate.status,
            },
            "evaluation": {
                "samples": result.samples,
                "score": result.score,
                "reward": reward,
                "integrity_passed": result.integrity_passed,
                "succeeded": result.succeeded,
                "error": result.error,
                "evidence": result.evidence,
            },
            "decision": {
                **decision,
                "best_before": best_before,
                "best_after": self.best_candidate_id,
            },
            "backprop_path": candidate.backprop_path,
        }
        self.trials.append(record)
        return record

    def _reward(self, candidate: Candidate, result: EvaluationResult) -> float:
        search = self.spec.get("search", {})
        duration_weight = float(search.get("duration_weight", 0.0001))
        failure_penalty = float(search.get("failure_penalty", 1.0))
        if not result.succeeded or not result.integrity_passed or result.score is None or not math.isfinite(result.score):
            return -failure_penalty - duration_weight * result.duration_seconds
        root = self.candidates[self.root_ids[candidate.route_id]]
        baseline = root.score if root.score is not None else result.score
        delta = directional_improvement(result.score, baseline, self.direction)
        scale_floor = float(search.get("metric_scale_floor", 1.0))
        normalized = delta / max(abs(baseline), scale_floor)
        return normalized - duration_weight * result.duration_seconds

    def _decision(self, candidate: Candidate, result: EvaluationResult) -> dict[str, Any]:
        if candidate.depth == 0:
            return {"status": "default_observed" if candidate.status == "evaluated" else "default_failed", "reason": result.error}
        if not result.succeeded:
            return {"status": "reject", "reason": "evaluator_failed"}
        if not result.integrity_passed:
            return {"status": "reject", "reason": "integrity_failed"}
        if result.score is None or not math.isfinite(result.score):
            return {"status": "reject", "reason": "invalid_score"}
        if self.best_candidate_id is None:
            return {"status": "keep", "reason": "first_valid_candidate"}
        best_score = self.candidates[self.best_candidate_id].score
        if best_score is None:
            return {"status": "keep", "reason": "first_valid_candidate"}
        improvement = directional_improvement(result.score, best_score, self.direction)
        if improvement >= self.min_delta:
            return {"status": "keep", "reason": "metric_improvement", "improvement": improvement}
        return {"status": "reject", "reason": "insufficient_improvement", "improvement": improvement}

    def mark_exhausted_if_idle(self) -> None:
        if self.stop_reason is None and self.default_barrier_open:
            self.stop_reason = "candidate_space_exhausted"

    def ledger(self, elapsed_seconds: float, holdout: dict[str, Any] | None = None) -> dict[str, Any]:
        best = self.candidates.get(self.best_candidate_id or "")
        return {
            "version": "experiment.ledger/v1",
            "contract_hash": self.contract_hash,
            "stop_reason": self.stop_reason,
            "elapsed_seconds": elapsed_seconds,
            "dispatch_count": self.dispatch_count,
            "completion_count": self.completion_count,
            "default_barrier_open": self.default_barrier_open,
            "best_candidate": None
            if best is None
            else {
                "candidate_id": best.candidate_id,
                "route_id": best.route_id,
                "parameters": best.parameters,
                "score": best.score,
            },
            "route_summaries": [self._route_summary(route_id) for route_id in self.route_order],
            "trials": sorted(self.trials, key=lambda trial: int(trial["trial_number"] or 0)),
            "holdout": holdout,
        }

    def _route_summary(self, route_id: str) -> dict[str, Any]:
        candidates = [
            candidate for candidate in self.candidates.values() if candidate.route_id == route_id and candidate.score is not None
        ]
        candidates.sort(key=self._candidate_sort_key)
        return {
            "route_id": route_id,
            "real_visits": self.route_visits[route_id],
            "virtual_visits": self.route_virtual_visits[route_id],
            "default_score": self.candidates[self.root_ids[route_id]].score,
            "best_candidates": [
                {"candidate_id": candidate.candidate_id, "score": candidate.score, "parameters": candidate.parameters}
                for candidate in candidates[: int(self.spec.get("search", {}).get("beam_width", 3))]
            ],
        }


def aggregate_scores(samples: list[float], aggregation: str, direction: str) -> float:
    if not samples:
        raise ValueError("没有可聚合的分数")
    if aggregation == "mean":
        return statistics.fmean(samples)
    if aggregation == "median":
        return statistics.median(samples)
    if aggregation == "worst":
        return min(samples) if direction == "maximize" else max(samples)
    raise ValueError(f"不支持的聚合方式: {aggregation}")
