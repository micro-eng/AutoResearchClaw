"""Execution-artefact reconciliation — the single source of truth for
"did any experiment actually produce a number?".

Principle (FAB-1)
-----------------
**A verifier must reconcile reported numbers against the experiment artefacts,
never against the text it is verifying, and never against a log string that the
failure path itself emits.**

The 2026-07-31 fabrication incident had three proxies standing in for evidence:

1. ``_paper_writing.py`` accepted ``>= 3`` occurrences of the regex
   ``condition[=:]`` in raw sandbox *stdout* as proof that real metrics existed.
   A crashed run prints ``Running condition: <name>`` before dying, so the
   pipeline's own progress messages satisfied its own anti-fabrication guard.
2. ``_analysis.py`` promoted the metrics of a refinement sandbox that exited
   ``returncode=1`` into ``best_run.status = "completed"``.
3. ``_review_publish.py`` then read that laundered summary and reported
   ``has_real_data: true``, ``fabrication_suspected: false``, ``verdict:
   Accept``.

This module keys on the only artefacts that record what a process actually did:

* ``stage-*/runs/*.json`` — ``status``, ``metrics``, ``timed_out``
* ``stage-13*/refinement_log.json`` — per-iteration ``sandbox`` /
  ``sandbox_after_fix`` entries carrying ``returncode``, ``metrics``,
  ``timed_out`` (both fields are always written by
  ``_execution.py::_execute_iterative_refine``).

It never reads ``experiment_summary.json`` (a derived artefact), never reads
paper text, and never pattern-matches log output.

Outcome vocabulary
------------------
``success``
    Process terminated normally (``status`` in :data:`_SUCCESS_STATUSES`, or
    ``returncode == 0``) and did not time out.
``degraded``
    Timed out but emitted metrics.  A timeout is a *budget* outcome, not a
    correctness failure, so its emitted numbers remain traceable to a process.
``failed``
    Non-zero exit, ``status: failed``, or a normal exit with no metrics at all.
    **A non-zero exit never counts as evidence**, however many metric lines the
    process printed before raising — the program's own contract broke, so the
    condition set it claims to cover is unknowable.
``simulated``
    Synthetic data.  Never evidence.
``unknown``
    Artefact does not record a terminal outcome.  Never evidence.

Only ``success`` and ``degraded`` executions that carry at least one finite,
non-infrastructure metric value count as evidence.

Scope boundary — provenance, NOT validity
-----------------------------------------
``has_real_metrics`` answers exactly one question: **did a process actually
emit this number?**  It does not, and deliberately must not, answer *is the
number meaningful?*  A run whose evaluator is nonsense will exit cleanly, emit
finite metrics, and pass this module — correctly, because the numbers really
were produced.

This is not hypothetical.  The 2026-07-31 baseline evaluator
(``stage-10/experiment/evaluation.py``) computed::

    crps = (y_pred[:, 1] - y_pred[:, 0]) / 2   # the interval HALF-WIDTH

with ``predict()`` returning ``np.array(X) * 1.0`` — so ``y_pred[:, 0]`` and
``y_pred[:, 1]`` were *feature columns*, and no model regressed anything.
Under ``metric_key: CRPS`` + ``metric_direction: minimize`` the global optimum
of that objective is ``lower == upper``: zero-width intervals with coverage 0.
``Coverage90`` was computed and printed but was not the adoption objective, so
nothing penalised the collapse.

Such a run would pass every check in this module.  **That is the intended
division of labour, not a gap to close here.** Deciding that CRPS must be
minimised *subject to* a coverage floor is authoring the experiment's
evaluation — a research decision belonging in the experiment plan and the
generated evaluator, not in an integrity gate.  A gate that silently invented
an objective would be committing the same category error as the guard it
replaced: substituting its own proxy for the thing it is meant to protect.

State the guarantee precisely when quoting it: *every reported number traces to
a process that produced it* — never *the results are correct*.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "ExecutionRecord",
    "ResultsEvidence",
    "collect_results_evidence",
]

# Exact, whole-token status values.  Compared with ``==`` after
# ``strip().lower()`` — never with ``in`` against the raw string, because
# substring matching is how this codebase produced its trap in the first place.
_SUCCESS_STATUSES: frozenset[str] = frozenset(
    {"completed", "complete", "done", "success", "succeeded", "ok", "passed"}
)
_FAILED_STATUSES: frozenset[str] = frozenset(
    {"failed", "failure", "error", "errored", "crashed", "timeout", "timed_out"}
)
_SIMULATED_STATUSES: frozenset[str] = frozenset({"simulated", "synthetic", "mock"})
_DEGRADED_STATUSES: frozenset[str] = frozenset({"partial"})

# Infrastructure counters — real numbers, but not experimental results.
# Compared case-insensitively against the *whole* metric key (or its last
# path segment), never as a substring.
_INFRA_METRIC_KEYS: frozenset[str] = frozenset(
    k.lower()
    for k in (
        "elapsed_sec",
        "total_elapsed_seconds",
        "time_estimate",
        "seed_count",
        "n_seeds",
        "time_budget_sec",
        "condition_count",
        "total_runs",
        "total_conditions",
        "total_metric_keys",
        "stopped_early",
        "training_steps",
        "total_steps",
        "batch_size",
        "num_workers",
        "total_params",
        "max_epochs",
        "num_seeds",
        "gpu_memory",
    )
)

# "Cond/0/metric" and "Cond/metric"
_PER_SEED_KEY = re.compile(r"^(?P<cond>.+)/(?P<seed>\d+)/(?P<metric>.+)$")
_COND_KEY = re.compile(r"^(?P<cond>[^/]+)/(?P<metric>[^/]+)$")


def _is_finite_number(value: Any) -> bool:
    """True for a finite int/float that is not a bool."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _is_infra_key(key: str) -> bool:
    """Whole-token infrastructure-key test (never a substring match)."""
    lowered = key.strip().lower()
    if lowered in _INFRA_METRIC_KEYS:
        return True
    tail = lowered.rsplit("/", 1)[-1]
    return tail in _INFRA_METRIC_KEYS


def _extract_metrics(metrics: Any) -> tuple[tuple[float, ...], tuple[str, ...]]:
    """Return (finite result values, condition names) from a metrics mapping."""
    if not isinstance(metrics, dict):
        return (), ()
    values: list[float] = []
    conditions: set[str] = set()
    for key, value in metrics.items():
        if not isinstance(key, str):
            continue
        if _is_infra_key(key):
            continue
        if not _is_finite_number(value):
            continue
        values.append(float(value))
        m = _PER_SEED_KEY.match(key) or _COND_KEY.match(key)
        if m:
            cond = m.group("cond").strip()
            if cond and not _is_infra_key(cond):
                conditions.add(cond)
    return tuple(values), tuple(sorted(conditions))


@dataclass(frozen=True)
class ExecutionRecord:
    """One process execution, as recorded by its own artefact."""

    source: str
    kind: str  # "run" | "refine_sandbox"
    outcome: str  # success | degraded | failed | simulated | unknown
    detail: str
    metric_values: tuple[float, ...] = ()
    conditions: tuple[str, ...] = ()

    @property
    def is_evidence(self) -> bool:
        """True only when a terminating process actually emitted a number."""
        return self.outcome in ("success", "degraded") and bool(self.metric_values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "kind": self.kind,
            "outcome": self.outcome,
            "detail": self.detail,
            "finite_metric_count": len(self.metric_values),
            "conditions": list(self.conditions),
            "is_evidence": self.is_evidence,
        }


@dataclass
class ResultsEvidence:
    """Reconciliation verdict built purely from execution artefacts."""

    run_dir: str = ""
    executions: list[ExecutionRecord] = field(default_factory=list)

    # -- basic views -------------------------------------------------------
    @property
    def is_authoritative(self) -> bool:
        """True when at least one execution artefact was found.

        With zero execution artefacts this module has nothing to say, and
        callers must fall back to their previous behaviour rather than block
        an execution path that does not record runs (e.g. purely theoretical
        domains).  It never means "assume success".
        """
        return bool(self.executions)

    @property
    def supporting(self) -> list[ExecutionRecord]:
        return [e for e in self.executions if e.is_evidence]

    @property
    def has_real_metrics(self) -> bool:
        """The load-bearing predicate: did *any* terminating execution emit a
        finite result value?"""
        return bool(self.supporting)

    @property
    def finite_metric_values(self) -> tuple[float, ...]:
        vals: list[float] = []
        for e in self.supporting:
            vals.extend(e.metric_values)
        return tuple(vals)

    @property
    def verified_conditions(self) -> tuple[str, ...]:
        names: set[str] = set()
        for e in self.supporting:
            names.update(e.conditions)
        return tuple(sorted(names))

    @property
    def unverified_conditions(self) -> tuple[str, ...]:
        """Conditions OBSERVED in a non-evidence execution's metrics.

        These are the dangerous ones: a crashed process printed numbers for
        them, so they look real in stdout and in any summary derived from it.

        **This is not the full set of unsupported conditions, and must never be
        read as one.** It can only name conditions that emitted at least one
        metric key. A condition that was declared and then never ran at all
        emits nothing, so it is invisible here.

        In the 2026-07-31 run, five conditions were registered
        (``NoWidening`` plus four wideners) and only ``NoWidening`` ever emitted
        a metric — it crashed on condition 2 of 5. This property therefore
        reports exactly ``("NoWidening",)``, and a reader who took that as "one
        condition is questionable" would miss that **four more were declared and
        never executed**.

        Establishing the declared set requires the experiment plan/spec, not the
        execution record, so it is deliberately out of scope here: comparing a
        paper's claimed conditions against the declared set is a separate check
        that must be built explicitly rather than inferred from this field.
        """
        claimed: set[str] = set()
        for e in self.executions:
            if not e.is_evidence:
                claimed.update(e.conditions)
        return tuple(sorted(claimed - set(self.verified_conditions)))

    @property
    def orphan_metric_count(self) -> int:
        """Finite values emitted by executions that did NOT terminate cleanly."""
        return sum(len(e.metric_values) for e in self.executions if not e.is_evidence)

    # -- reporting ---------------------------------------------------------
    def blocking_reasons(self) -> list[str]:
        """Human-readable reasons this run cannot support reported numbers."""
        if not self.is_authoritative:
            return []
        if self.has_real_metrics:
            return []
        reasons: list[str] = []
        n = len(self.executions)
        reasons.append(
            f"No execution produced a finite metric: {n} execution artefact(s) "
            f"examined, 0 terminated successfully with results."
        )
        for e in self.executions:
            reasons.append(f"  {e.source}: {e.outcome} — {e.detail}")
        if self.orphan_metric_count:
            reasons.append(
                f"{self.orphan_metric_count} metric value(s) were emitted by "
                f"executions that did not terminate cleanly; they are NOT "
                f"verified results and must not appear in a paper."
            )
        if self.unverified_conditions:
            reasons.append(
                "Conditions named only by failed executions: "
                + ", ".join(self.unverified_conditions)
            )
        return reasons

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_dir": self.run_dir,
            "authoritative": self.is_authoritative,
            "has_real_metrics": self.has_real_metrics,
            "executions_examined": len(self.executions),
            "executions_supporting": len(self.supporting),
            "verified_conditions": list(self.verified_conditions),
            "unverified_conditions": list(self.unverified_conditions),
            "finite_metric_count": len(self.finite_metric_values),
            "orphan_metric_count": self.orphan_metric_count,
            "blocking_reasons": self.blocking_reasons(),
            "executions": [e.to_dict() for e in self.executions],
        }


def _classify_run_json(path: Path, payload: dict[str, Any]) -> ExecutionRecord:
    values, conditions = _extract_metrics(payload.get("metrics"))
    raw_status = payload.get("status")
    status = str(raw_status).strip().lower() if raw_status is not None else ""
    timed_out = bool(payload.get("timed_out"))

    if status in _SIMULATED_STATUSES:
        return ExecutionRecord(
            source=path.name,
            kind="run",
            outcome="simulated",
            detail=f"status={raw_status!r} — synthetic data, never evidence",
        )
    if status in _FAILED_STATUSES:
        return ExecutionRecord(
            source=path.name,
            kind="run",
            outcome="failed",
            detail=(
                f"status={raw_status!r}, {len(values)} finite metric(s) recorded "
                f"before termination"
            ),
            metric_values=values,
            conditions=conditions,
        )
    if status in _DEGRADED_STATUSES or (timed_out and values):
        return ExecutionRecord(
            source=path.name,
            kind="run",
            outcome="degraded" if values else "failed",
            detail=f"status={raw_status!r}, timed_out={timed_out}",
            metric_values=values,
            conditions=conditions,
        )
    if status in _SUCCESS_STATUSES:
        if not values:
            return ExecutionRecord(
                source=path.name,
                kind="run",
                outcome="failed",
                detail=(
                    f"status={raw_status!r} but metrics are empty — a clean exit "
                    f"with no metrics is not a result"
                ),
            )
        return ExecutionRecord(
            source=path.name,
            kind="run",
            outcome="success",
            detail=f"status={raw_status!r}, {len(values)} finite metric(s)",
            metric_values=values,
            conditions=conditions,
        )
    return ExecutionRecord(
        source=path.name,
        kind="run",
        outcome="unknown",
        detail=f"status={raw_status!r} is not a recognised terminal outcome",
        metric_values=values,
        conditions=conditions,
    )


def _classify_sandbox_entry(
    source: str, entry: dict[str, Any]
) -> ExecutionRecord | None:
    values, conditions = _extract_metrics(entry.get("metrics"))
    returncode = entry.get("returncode")
    timed_out = bool(entry.get("timed_out"))
    has_any_field = bool(entry)
    if not has_any_field:
        return None

    if returncode is None:
        return ExecutionRecord(
            source=source,
            kind="refine_sandbox",
            outcome="unknown",
            detail="no returncode recorded — cannot establish terminal outcome",
            metric_values=values,
            conditions=conditions,
        )
    try:
        rc = int(returncode)
    except (TypeError, ValueError):
        return ExecutionRecord(
            source=source,
            kind="refine_sandbox",
            outcome="unknown",
            detail=f"returncode={returncode!r} is not an integer",
            metric_values=values,
            conditions=conditions,
        )

    if rc != 0:
        if timed_out and values:
            return ExecutionRecord(
                source=source,
                kind="refine_sandbox",
                outcome="degraded",
                detail=f"returncode={rc} via timeout, {len(values)} finite metric(s)",
                metric_values=values,
                conditions=conditions,
            )
        return ExecutionRecord(
            source=source,
            kind="refine_sandbox",
            outcome="failed",
            detail=(
                f"returncode={rc}, {len(values)} finite metric(s) emitted before "
                f"the process died"
            ),
            metric_values=values,
            conditions=conditions,
        )
    if not values:
        return ExecutionRecord(
            source=source,
            kind="refine_sandbox",
            outcome="failed",
            detail="returncode=0 but no finite metrics emitted",
        )
    return ExecutionRecord(
        source=source,
        kind="refine_sandbox",
        outcome="degraded" if timed_out else "success",
        detail=f"returncode=0, timed_out={timed_out}, {len(values)} finite metric(s)",
        metric_values=values,
        conditions=conditions,
    )


def collect_results_evidence(run_dir: Path) -> ResultsEvidence:
    """Build a :class:`ResultsEvidence` for *run_dir* from execution artefacts only."""
    run_dir = Path(run_dir)
    evidence = ResultsEvidence(run_dir=run_dir.name)

    for runs_dir in sorted(run_dir.glob("stage-*/runs")):
        for run_file in sorted(runs_dir.glob("*.json")):
            if run_file.name == "results.json":
                continue  # no terminal-outcome field; run-N.json covers it
            try:
                payload = json.loads(run_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.debug("results_evidence: unreadable %s", run_file)
                continue
            if not isinstance(payload, dict):
                continue
            rel = f"{runs_dir.parent.name}/runs/{run_file.name}"
            record = _classify_run_json(run_file, payload)
            evidence.executions.append(
                ExecutionRecord(
                    source=rel,
                    kind=record.kind,
                    outcome=record.outcome,
                    detail=record.detail,
                    metric_values=record.metric_values,
                    conditions=record.conditions,
                )
            )

    for log_path in sorted(run_dir.glob("stage-13*/refinement_log.json")):
        try:
            log_data = json.loads(log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.debug("results_evidence: unreadable %s", log_path)
            continue
        if not isinstance(log_data, dict):
            continue
        for iteration in log_data.get("iterations", []) or []:
            if not isinstance(iteration, dict):
                continue
            version = str(iteration.get("version_dir", "?")).rstrip("/")
            for key in ("sandbox", "sandbox_after_fix"):
                entry = iteration.get(key)
                if not isinstance(entry, dict) or not entry:
                    continue
                source = f"{log_path.parent.name}/{version}/{key}"
                record = _classify_sandbox_entry(source, entry)
                if record is not None:
                    evidence.executions.append(record)

    logger.info(
        "results_evidence(%s): %d execution(s), %d supporting, has_real_metrics=%s",
        evidence.run_dir,
        len(evidence.executions),
        len(evidence.supporting),
        evidence.has_real_metrics,
    )
    return evidence
