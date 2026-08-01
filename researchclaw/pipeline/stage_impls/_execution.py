"""Stages 11-13: Resource planning, experiment execution, and iterative refinement."""

from __future__ import annotations

import json
import logging
import math
import re
import time as _time
from pathlib import Path
from typing import Any

from researchclaw.adapters import AdapterBundle
from researchclaw.config import RCConfig
from researchclaw.experiment.validator import (
    CodeValidation,
    format_issues_for_llm,
    validate_code,
)
from researchclaw.llm.client import LLMClient
from researchclaw.pipeline._domain import _detect_domain
from researchclaw.pipeline._helpers import (
    StageResult,
    _chat_with_prompt,
    _detect_runtime_issues,
    _ensure_sandbox_deps,
    _extract_code_block,
    _extract_multi_file_blocks,
    _get_evolution_overlay,
    _load_hardware_profile,
    _parse_metrics_from_stdout,
    _read_prior_artifact,
    _safe_filename,
    _safe_json_loads,
    _utcnow_iso,
    _write_stage_meta,
)
from researchclaw.pipeline.stages import Stage, StageStatus
from researchclaw.prompts import PromptManager

logger = logging.getLogger(__name__)

def _summarise_run_outcomes(runs_dir: Path) -> dict[str, Any]:
    """BUG-RUN-01: derive the honest stage-12 outcome from its own run payloads.

    Stage 12 used to return DONE/proceed unconditionally, so a ``run-1.json``
    carrying ``status: failed, metrics: {}`` was wrapped in a ``decision.json``
    saying ``status: done, decision: proceed, error: null``. The wrapper must
    reflect what it wraps.

    Only ``run-*.json`` files are inspected — ``results.json`` and the
    ``sandbox/`` working directory in the same folder are not run payloads.
    """
    summary: dict[str, Any] = {
        "runs": 0,
        "completed": 0,
        "partial": 0,
        "failed": 0,
        "simulated": 0,
        "other": 0,
        "with_metrics": 0,
        "degraded": False,
        "reason": None,
    }
    for run_file in sorted(runs_dir.glob("run-*.json")):
        payload = _safe_json_loads(run_file.read_text(encoding="utf-8"), {})
        if not isinstance(payload, dict):
            continue
        summary["runs"] += 1
        status = str(payload.get("status") or "other")
        if status in ("completed", "partial", "failed", "simulated"):
            summary[status] += 1
        else:
            summary["other"] += 1
        metrics = payload.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            metrics = payload.get("key_metrics")
        if isinstance(metrics, dict) and metrics:
            summary["with_metrics"] += 1

    if summary["runs"] == 0:
        summary["degraded"] = True
        summary["reason"] = "Stage 12 produced no run artifacts."
        return summary

    bad = summary["failed"] + summary["partial"]
    if bad:
        summary["degraded"] = True
        summary["reason"] = (
            f"{bad}/{summary['runs']} experiment run(s) did not complete "
            f"(failed={summary['failed']}, partial={summary['partial']}); "
            f"{summary['with_metrics']}/{summary['runs']} emitted metrics."
        )
    return summary


_REGISTERED_CONDITIONS_RE = re.compile(
    r"^REGISTERED_CONDITIONS:\s*(?P<names>.+)$", re.MULTILINE
)
_CONDITION_LABEL_RE = re.compile(r"\bcondition=(?P<name>[^\s,;]+)")


def _normalise_condition(name: str) -> str:
    """Canonical form for comparing condition names across artefacts."""
    return str(name).strip().strip("'\"").casefold()


def _condition_coverage(stdout: str, metrics: dict[str, Any]) -> dict[str, Any]:
    """BUG-COND-01: which registered conditions actually produced metrics.

    Stage 13's R7-3 hint asked only whether *any* ``condition=`` label appeared
    in stdout, so one surviving condition out of five read as full coverage.
    In ``rc-ws3-h2-real4-20260731`` five conditions were registered and only
    ``NoWidening`` — the no-widening **control** — ever scored; the paper then
    reported the control's number under the proposed method's name.

    ``registered`` comes from the ``REGISTERED_CONDITIONS:`` line the generated
    code already prints. ``scored`` comes from condition-prefixed metric keys
    (``NoWidening/CRPS``), i.e. conditions that produced a number, which is a
    stricter and more useful signal than ``ran`` (a ``condition=`` label, which
    a condition prints before it crashes).

    Reporting only — it never selects, filters or judges a condition. Callers
    ask membership via :func:`_condition_scored`, so "was the *proposed method*
    among the scored?" is answerable, not just "how many scored?".

    ``complete`` is ``None`` when no registry line was found: unknown coverage
    must not be reported as full coverage.

    **Scope limit — the CODE's registry, not the PLAN's.** ``registered`` is
    read from stdout, so it can only contain conditions the generated code got
    as far as registering. A condition the experiment *plan* declares and the
    code never mentions is invisible here, and ``complete: True`` therefore
    means "every condition the code registered scored" — never "the planned
    experiment ran". Comparing against ``exp_plan.yaml``'s declared set is a
    separate check that must not be inferred from this one. This is a
    refinement-loop diagnostic reporting what a run did; an integrity guard
    deciding whether a paper may be written should key on the plan, not on a
    stdout string.
    """
    registered: list[str] = []
    match = _REGISTERED_CONDITIONS_RE.search(stdout or "")
    if match:
        seen: set[str] = set()
        for raw in match.group("names").split(","):
            name = raw.strip().strip("'\"")
            if name and _normalise_condition(name) not in seen:
                seen.add(_normalise_condition(name))
                registered.append(name)

    scored: set[str] = set()
    for key in (metrics or {}):
        text = str(key)
        if "/" in text:
            scored.add(text.split("/", 1)[0])

    ran: set[str] = {
        m.group("name") for m in _CONDITION_LABEL_RE.finditer(stdout or "")
    }

    scored_norm = {_normalise_condition(c) for c in scored}
    unscored = [c for c in registered if _normalise_condition(c) not in scored_norm]
    return {
        "registered": registered,
        "scored": sorted(scored),
        "ran": sorted(ran),
        "unscored": unscored,
        "registered_count": len(registered),
        "scored_count": len(scored),
        "complete": (not unscored) if registered else None,
    }


def _condition_scored(coverage: dict[str, Any], name: str) -> bool:
    """Did *name* produce a metric? Exact name match, never a substring.

    ``"NoWidening"`` must not satisfy a query for ``"NoWideningPlus"``, and a
    proposed method must never be reported as scored because an ablation of it
    shares a prefix.
    """
    target = _normalise_condition(name)
    return any(
        _normalise_condition(c) == target for c in coverage.get("scored", ())
    )


_PLAN_CONDITION_SECTIONS = ("proposed_methods", "ablations", "baselines")


def _declared_conditions(exp_plan_text: str) -> list[dict[str, Any]]:
    """Conditions the experiment PLAN declares, with their code identifiers.

    Each entry carries the plan's prose ``name`` and its
    ``implementation_spec.class_name`` — **the class name is what the generated
    code registers, and the only field safe to match on.** The two differ
    routinely and non-systematically: run 4's plan pairs
    ``name: DivergenceConditionedWidening`` with
    ``class_name: DivergenceConditionedWidener``, and run 1's pairs
    ``name: NoWidening`` with ``class_name: FixedIntervalWidener``. Comparing
    prose names to the registry scores 0/8 on run 1 and would report every
    condition missing on a run where five were registered.
    """
    try:
        import yaml as _yaml
    except ImportError:  # pragma: no cover - pyyaml is a hard dependency
        return []
    try:
        plan = _yaml.safe_load(exp_plan_text or "") or {}
    except Exception:  # noqa: BLE001 - a malformed plan is not fatal here
        return []
    if not isinstance(plan, dict):
        return []

    declared: list[dict[str, Any]] = []
    for section in _PLAN_CONDITION_SECTIONS:
        entries = plan.get(section)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            # `baselines:` is routinely a list of BARE STRINGS
            # (`- UnconditionalQuantileAggregation`) while methods and
            # ablations are mappings. Skipping non-dicts drops exactly the
            # entries most at risk: run 4 declared three string baselines,
            # none were ever registered, and one of them is the fabricated
            # row in the paper.
            if isinstance(entry, str):
                declared.append(
                    {"section": section, "name": entry, "class_name": None}
                )
                continue
            if not isinstance(entry, dict):
                continue
            class_name = entry.get("class_name")
            if not isinstance(class_name, str):
                for sub in ("implementation_spec", "implementation", "spec"):
                    nested = entry.get(sub)
                    if isinstance(nested, dict) and isinstance(
                        nested.get("class_name"), str
                    ):
                        class_name = nested["class_name"]
                        break
            name = entry.get("name")
            declared.append(
                {
                    "section": section,
                    "name": name if isinstance(name, str) else None,
                    "class_name": class_name if isinstance(class_name, str) else None,
                }
            )
    return declared


def _plan_vs_scored(
    declared: list[dict[str, Any]], coverage: dict[str, Any]
) -> dict[str, Any]:
    """BUG-COND-02: did the conditions the PLAN declares actually score?

    Registered-vs-scored cannot catch a condition the code never registered at
    all. In ``rc-ws3-h2-real-20260731`` the code never defined the proposed
    method across three attempts: five conditions registered, none of them the
    paper's subject. Registered-vs-scored reports "complete" there; only a
    plan-side comparison sees it.

    Matching is exact-normalised on ``class_name``. Two fail-closed rules keep
    a naming problem from being reported as a scientific one:

    * a declared entry with **no** ``class_name`` is ``unresolved``, never
      ``missing`` — it could not be matched, which is not evidence of absence;
    * if names are unmatched on **both** sides, ``correspondence`` is
      ``"unresolved"`` and the per-entry verdicts must not be read as
      missing-ness — the two namespaces simply do not line up.
    """
    scored_norm = {
        _normalise_condition(c) for c in coverage.get("scored", ()) or ()
    }
    registered_norm = {
        _normalise_condition(c) for c in coverage.get("registered", ()) or ()
    }

    entries: list[dict[str, Any]] = []
    matched_norm: set[str] = set()
    for item in declared:
        # A bare-string entry gives only a prose name; fall back to it so the
        # entry is classified at all, but remember that the match was weaker.
        identifier = item.get("class_name") or item.get("name")
        key = _normalise_condition(identifier) if identifier else ""
        if not key:
            verdict = "unresolved"
        elif key in scored_norm:
            verdict = "scored"
            matched_norm.add(key)
        elif key in registered_norm:
            verdict = "registered_not_scored"
            matched_norm.add(key)
        elif item.get("class_name"):
            verdict = "not_registered"
        else:
            # No declared class name and no name match: cannot yet distinguish
            # "absent" from "registered under a name we can't map".
            verdict = "unmatched"
        entries.append({**item, "verdict": verdict})

    registered_not_declared = sorted(
        c
        for c in coverage.get("registered", ()) or ()
        if _normalise_condition(c) not in matched_norm
    )
    # Scored metric prefixes are an independent namespace from the optional
    # REGISTERED_CONDITIONS line.  When experiments emit condition=/metric keys
    # but never print the registry line, registered_not_declared stays empty
    # even though the code clearly ran under names absent from the plan
    # (e.g. dense/sparse_* vs prose proposed_methods).  Count those too, or
    # FAB-2 mis-classifies the mismatch as proven absence (correspondence=ok)
    # and hard-blocks a legitimate draft.
    scored_not_declared = sorted(
        c
        for c in coverage.get("scored", ()) or ()
        if _normalise_condition(c) not in matched_norm
    )
    code_not_declared_norm: dict[str, str] = {}
    for c in registered_not_declared + scored_not_declared:
        code_not_declared_norm.setdefault(_normalise_condition(c), c)
    code_not_declared = sorted(code_not_declared_norm.values())
    # Resolve the tentative verdicts: when EVERY code condition mapped to
    # a declared entry, there is no unaccounted code condition an unmatched
    # declaration could correspond to, so it genuinely was never registered.
    # Otherwise the namespaces do not line up and no absence claim is safe.
    for entry in entries:
        if entry["verdict"] == "unmatched":
            entry["verdict"] = (
                "not_registered" if not code_not_declared else "unresolved"
            )

    unmatched_declared = [
        e for e in entries if e["verdict"] in ("not_registered", "unresolved")
    ]
    if not declared:
        correspondence = "no_plan"
    elif unmatched_declared and code_not_declared:
        correspondence = "unresolved"
    else:
        correspondence = "ok"

    proposed = [e for e in entries if e["section"] == "proposed_methods"]
    return {
        "declared_count": len(entries),
        "entries": entries,
        "correspondence": correspondence,
        "registered_not_declared": registered_not_declared,
        "scored": [e["class_name"] or e["name"] for e in entries if e["verdict"] == "scored"],
        "not_registered": [
            e["class_name"] or e["name"] for e in entries if e["verdict"] == "not_registered"
        ],
        "unresolved": [e["name"] for e in entries if e["verdict"] == "unresolved"],
        "proposed_methods": [e["class_name"] or e["name"] for e in proposed],
        "proposed_methods_scored": [
            e["class_name"] or e["name"] for e in proposed if e["verdict"] == "scored"
        ],
        "any_proposed_method_scored": any(e["verdict"] == "scored" for e in proposed),
    }


def _describe_plan_gap(plan_status: dict[str, Any]) -> str | None:
    """Human-readable plan-vs-scored finding, or ``None`` when there is none."""
    if plan_status.get("correspondence") == "no_plan":
        return None
    if plan_status.get("correspondence") == "unresolved":
        return (
            "Plan/code condition names do not correspond: the plan declares "
            f"{len(plan_status['not_registered']) + len(plan_status['unresolved'])} "
            "name(s) with no match in the code, and the code registered "
            f"{len(plan_status['registered_not_declared'])} name(s) absent from "
            "the plan. NO conclusion about missing conditions can be drawn — "
            "this is a naming-correspondence failure, not evidence that a "
            "condition was skipped."
        )
    if not plan_status.get("any_proposed_method_scored") and plan_status.get(
        "proposed_methods"
    ):
        return (
            "NO declared proposed method produced metrics "
            f"({', '.join(plan_status['proposed_methods'])}). Scored: "
            f"{', '.join(plan_status['scored']) or '(none)'}. A paper comparing "
            "the proposed method against a baseline cannot be supported."
        )
    if plan_status.get("not_registered"):
        return (
            "Declared but never registered by the code: "
            f"{', '.join(plan_status['not_registered'])}."
        )
    return None


def _describe_condition_gap(coverage: dict[str, Any]) -> str | None:
    """Human-readable gap line, or ``None`` when coverage is complete/unknown."""
    if not coverage.get("unscored"):
        return None
    return (
        f"{coverage['scored_count']}/{coverage['registered_count']} registered "
        f"condition(s) produced metrics. Scored: "
        f"{', '.join(coverage['scored']) or '(none)'}. "
        f"NO metrics from: {', '.join(coverage['unscored'])}. "
        f"A comparison across conditions cannot be supported by this run."
    )


def _last_sandbox_record(iter_record: dict[str, Any]) -> dict[str, Any]:
    """The sandbox run whose METRICS describe the files in the version dir.

    ``sandbox_after_fix`` when a runtime repair rewrote and re-ran the code,
    otherwise the first ``sandbox`` run.

    **Metrics only — do NOT read stdout from this.** ``sandbox_after_fix`` is
    written without a ``stdout`` key (see the re-run block in
    ``_execute_iterative_refine``), so on a repaired iteration it carries the
    metrics with a zero-length stdout. Anything parsing stdout must use
    :func:`_registry_stdout`, which prefers the surface that actually has it.
    Following this function's convention for stdout would silently read ""
    on exactly the repaired iterations that matter.
    """
    sandbox = iter_record.get("sandbox_after_fix")
    if not isinstance(sandbox, dict):
        sandbox = iter_record.get("sandbox")
    return sandbox if isinstance(sandbox, dict) else {}


def _registry_stdout(iter_record: dict[str, Any]) -> str:
    """Stdout for condition parsing — the surface that actually carries it.

    Prefers whichever run's stdout contains a ``REGISTERED_CONDITIONS:`` line,
    then any non-empty stdout, rather than assuming a fixed run. The metrics
    and the stdout of one iteration live on **different** records when a
    runtime repair fired.
    """
    candidates = [
        iter_record.get("sandbox"),
        iter_record.get("sandbox_after_fix"),
    ]
    texts = [
        c.get("stdout") or "" for c in candidates if isinstance(c, dict)
    ]
    for text in texts:
        if _REGISTERED_CONDITIONS_RE.search(text):
            return text
    return next((t for t in texts if t), "")


def _describe_metric_key_miss(
    metric_key: str, metrics: dict[str, Any]
) -> str | None:
    """BUG-METRIC-01: distinguish "emitted nothing" from "emitted, none matched".

    ``_find_metric`` returning ``None`` was indistinguishable from an experiment
    that produced no output at all, and the pipeline reported the second. In
    ``rc-ws3-h2-real4-20260731`` the configured ``metric_key`` was
    ``primary_metric`` while the code emitted ``CRPS``, ``Coverage90``,
    ``Width90``, ``PinballLoss``, ``success_rate`` and ``MedianCRPS`` — all five
    matching branches of ``_find_metric`` miss, so **no run of that experiment
    could ever have scored**, clean or crashed.

    Returns a diagnosis when *metrics* is non-empty, else ``None``.

    **Precondition: call only where ``_find_metric`` has already returned
    ``None``.** This does not re-run the matching logic — duplicating those five
    branches would let the diagnosis drift from the decision it explains — so
    called without that precondition it will describe a miss that did not occur.

    Deliberately does NOT pick a substitute metric: choosing between ``CRPS``
    and ``Coverage90`` (opposite directions) would be authoring the experiment,
    and a wrong choice silently optimises refinement against the wrong
    objective. Naming the metric is the run config's job.
    """
    if not metrics:
        return None
    names = sorted({str(k).rsplit("/", 1)[-1] for k in metrics})
    return (
        f"Experiment emitted {len(metrics)} metric key(s) but none yielded a "
        f"finite value for the configured metric_key {metric_key!r}. "
        f"Emitted names: {', '.join(names[:12])}"
        f"{' ...' if len(names) > 12 else ''}. "
        f"Refinement cannot score this experiment until metric_key names one of "
        f"them (or the code emits {metric_key!r})."
    )


def _refinement_progress_key(
    iteration: int, iter_record: dict[str, Any]
) -> tuple[int, int, int, int, int]:
    """Rank a stage-13 refinement version by how far it actually got.

    Used only when NO version produces the primary metric, so ``_is_better``
    has nothing to compare. Ordered tuple, higher is better:

    ``(exited_cleanly, n_conditions_scored, n_metric_keys_emitted,
    did_not_time_out, iteration)``

    ``n_conditions_scored`` outranks ``n_metric_keys_emitted`` deliberately:
    key count is a proxy that a 1-of-5-condition run can win on volume alone
    (34 keys from one condition beat 30 keys from five), which would rank a
    fragment of an experiment above a complete one. Conditions are the unit the
    experiment is actually made of.

    ``iteration`` breaks ties so the latest validation-passing version wins in
    modes that never run a sandbox (where the first three terms are constant).
    The measurement is taken from the *last* sandbox run of the iteration —
    ``sandbox_after_fix`` when a runtime repair re-ran the code, because those
    are the files actually written to the version directory.

    **Scope boundary — progress, NOT quality.** This ranks how far a version got
    before stopping. It is not a claim that the adopted version is scientifically
    better, and ``adoption_reason: progress_fallback_no_metric_anywhere`` must
    never be read as one: it says only *no version produced the configured
    metric, and this one ran furthest*. Judging which version is actually better
    requires an objective, which is the run config's and the experiment plan's
    job — see ``_describe_metric_key_miss`` for why this module declines to pick
    one. A version that runs further while optimising a degenerate objective
    still ranks highest here, correctly: the alternative is discarding every
    refinement whenever the objective is unusable.
    """
    sandbox = _last_sandbox_record(iter_record)
    metrics = sandbox.get("metrics")
    n_metrics = len(metrics) if isinstance(metrics, dict) else 0
    coverage = iter_record.get("condition_coverage")
    n_conditions = (
        int(coverage.get("scored_count") or 0)
        if isinstance(coverage, dict)
        else 0
    )
    exited_cleanly = 1 if sandbox.get("returncode") == 0 else 0
    not_timed_out = 0 if sandbox.get("timed_out") else 1
    return (exited_cleanly, n_conditions, n_metrics, not_timed_out, iteration)


def _decide_refinement_adoption(
    *,
    best_version: str,
    best_metric: float | None,
    progress_version: str | None,
    progress_key: tuple[int, ...] | None,
) -> tuple[str, str]:
    """BUG-ADOPT-01: decide which stage-13 version becomes ``experiment_final``.

    Adoption used to be reachable only through an improving metric: the
    ``elif validation.ok and best_version == "experiment/"`` fallback sat in
    the ``orelse`` of ``if validation.ok and mode in ("sandbox", "docker")``
    while itself requiring ``validation.ok``, making it unreachable in exactly
    the modes that run code (AST-verified). One unrelated crash therefore
    zeroed the metric for every version and silently reverted ``experiment_final``
    to the original stage-10 code.

    Returns ``(adopted_version, reason)``. The caller logs the reason either
    way, so "the original was kept" is now a recorded decision, not silence.
    """
    if best_version != "experiment/":
        return best_version, "metric_improvement"
    if best_metric is not None:
        # A real metric exists and no refinement beat it — keeping the
        # original is a genuine comparison, not a discarded improvement.
        return best_version, "original_retained_no_metric_improvement"
    if progress_version is not None and progress_key is not None:
        return progress_version, "progress_fallback_no_metric_anywhere"
    return best_version, "original_retained_no_valid_candidate"


def _execute_resource_planning(
    stage_dir: Path,
    run_dir: Path,
    config: RCConfig,
    adapters: AdapterBundle,
    *,
    llm: LLMClient | None = None,
    prompts: PromptManager | None = None,
) -> StageResult:
    exp_plan = _read_prior_artifact(run_dir, "exp_plan.yaml") or ""
    schedule: dict[str, Any] | None = None
    if llm is not None:
        _pm = prompts or PromptManager()
        _overlay = _get_evolution_overlay(run_dir, "resource_planning")
        sp = _pm.for_stage("resource_planning", evolution_overlay=_overlay, exp_plan=exp_plan)
        resp = _chat_with_prompt(
            llm,
            sp.system,
            sp.user,
            json_mode=sp.json_mode,
            max_tokens=sp.max_tokens,
        )
        parsed = _safe_json_loads(resp.content, {})
        if isinstance(parsed, dict):
            schedule = parsed
    if schedule is None:
        schedule = {
            "tasks": [
                {
                    "id": "baseline",
                    "name": "Run baseline",
                    "depends_on": [],
                    "gpu_count": 1,
                    "estimated_minutes": 20,
                    "priority": "high",
                },
                {
                    "id": "proposed",
                    "name": "Run proposed method",
                    "depends_on": ["baseline"],
                    "gpu_count": 1,
                    "estimated_minutes": 30,
                    "priority": "high",
                },
            ],
            "total_gpu_budget": 1,
            "generated": _utcnow_iso(),
        }
    schedule.setdefault("generated", _utcnow_iso())
    (stage_dir / "schedule.json").write_text(
        json.dumps(schedule, indent=2), encoding="utf-8"
    )
    return StageResult(
        stage=Stage.RESOURCE_PLANNING,
        status=StageStatus.DONE,
        artifacts=("schedule.json",),
        evidence_refs=("stage-11/schedule.json",),
    )


def _execute_experiment_run(
    stage_dir: Path,
    run_dir: Path,
    config: RCConfig,
    adapters: AdapterBundle,
    *,
    llm: LLMClient | None = None,
    prompts: PromptManager | None = None,
) -> StageResult:
    from researchclaw.experiment.factory import create_sandbox
    from researchclaw.experiment.runner import ExperimentRunner

    schedule_text = _read_prior_artifact(run_dir, "schedule.json") or "{}"
    # Try multi-file experiment directory first, fall back to single file
    exp_dir_path = _read_prior_artifact(run_dir, "experiment/")
    code_text = ""
    if exp_dir_path and Path(exp_dir_path).is_dir():
        main_path = Path(exp_dir_path) / "main.py"
        if main_path.exists():
            try:
                code_text = main_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                code_text = ""
    if not code_text:
        code_text = _read_prior_artifact(run_dir, "experiment.py") or ""

    runs_dir = stage_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    mode = config.experiment.mode
    if mode in ("sandbox", "docker"):
        # P7: Auto-install missing dependencies before subprocess sandbox
        if mode == "sandbox":
            _all_code = code_text
            if exp_dir_path and Path(exp_dir_path).is_dir():
                for _pyf in Path(exp_dir_path).glob("*.py"):
                    try:
                        _all_code += "\n" + _pyf.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        pass
            _ensure_sandbox_deps(_all_code, config.experiment.sandbox.python_path)

        sandbox = create_sandbox(config.experiment, runs_dir / "sandbox")
        # Use run_project for multi-file, run for single-file
        if exp_dir_path and Path(exp_dir_path).is_dir():
            result = sandbox.run_project(
                Path(exp_dir_path), timeout_sec=config.experiment.time_budget_sec
            )
        else:
            result = sandbox.run(
                code_text, timeout_sec=config.experiment.time_budget_sec
            )
        # Try to read structured results.json from sandbox working dir
        structured_results: dict[str, Any] | None = None
        sandbox_project = runs_dir / "sandbox" / "_project"
        results_json_path = sandbox_project / "results.json"
        if results_json_path.exists():
            try:
                structured_results = json.loads(
                    results_json_path.read_text(encoding="utf-8")
                )
                # Copy results.json to runs dir for easy access
                (runs_dir / "results.json").write_text(
                    results_json_path.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            except (json.JSONDecodeError, OSError):
                structured_results = None

        # If sandbox metrics are empty, try to parse from stdout
        effective_metrics = result.metrics
        if not effective_metrics and result.stdout:
            effective_metrics = _parse_metrics_from_stdout(result.stdout)

        # Determine run status: completed / partial (timed out with data) / failed
        # R6-2: Detect stdout failure signals even when exit code is 0
        _stdout_has_failure = bool(
            result.stdout
            and not effective_metrics
            and any(
                sig in result.stdout
                for sig in ("FAIL:", "NaN/divergence", "Traceback (most recent")
            )
        )
        if result.returncode == 0 and not result.timed_out and not _stdout_has_failure:
            run_status = "completed"
        elif result.timed_out and effective_metrics:
            run_status = "partial"
            logger.warning(
                "Experiment timed out but captured %d partial metrics",
                len(effective_metrics),
            )
        else:
            run_status = "failed"
            if _stdout_has_failure:
                logger.warning(
                    "Experiment exited cleanly but stdout contains failure signals"
                )

        # P1: Warn if experiment completed suspiciously fast (trivially easy benchmark)
        if run_status == "completed" and result.elapsed_sec and result.elapsed_sec < 5.0:
            logger.warning(
                "Stage 12: Experiment completed in %.2fs — benchmark may be trivially easy. "
                "Consider increasing task difficulty.",
                result.elapsed_sec,
            )

        run_payload: dict[str, Any] = {
            "run_id": "run-1",
            "task_id": "sandbox-main",
            "status": run_status,
            "metrics": effective_metrics,
            "elapsed_sec": result.elapsed_sec,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
            "completed_at": _utcnow_iso(),
        }
        if structured_results is not None:
            run_payload["structured_results"] = structured_results
        # Auto-generate results.json from parsed metrics if sandbox didn't produce one
        if structured_results is None and effective_metrics:
            auto_results = {"source": "stdout_parsed", "metrics": effective_metrics}
            (runs_dir / "results.json").write_text(
                json.dumps(auto_results, indent=2), encoding="utf-8"
            )
            logger.info("Stage 12: Auto-generated results.json from stdout metrics (%d keys)", len(effective_metrics))
        (runs_dir / "run-1.json").write_text(
            json.dumps(run_payload, indent=2), encoding="utf-8"
        )

        # R11-6: Time budget adequacy check
        if result.timed_out or (result.elapsed_sec and result.elapsed_sec > config.experiment.time_budget_sec * 0.9):
            # Parse stdout to estimate how many conditions/seeds completed
            _stdout = result.stdout or ""
            _completed_conditions = set()
            _completed_seeds = 0
            for _line in _stdout.splitlines():
                if "condition=" in _line and "seed=" in _line:
                    _completed_seeds += 1
                    _cond_match = re.match(r".*condition=(\S+)", _line)
                    if _cond_match:
                        _completed_conditions.add(_cond_match.group(1))
            _time_budget_warning = {
                "timed_out": result.timed_out,
                "elapsed_sec": result.elapsed_sec,
                "budget_sec": config.experiment.time_budget_sec,
                "conditions_completed": sorted(_completed_conditions),
                "total_seed_runs": _completed_seeds,
                "warning": (
                    f"Experiment used {result.elapsed_sec:.0f}s of "
                    f"{config.experiment.time_budget_sec}s budget. "
                    f"Only {len(_completed_conditions)} conditions completed "
                    f"({_completed_seeds} seed-runs). Consider increasing "
                    f"time_budget_sec for more complete results."
                ),
            }
            logger.warning(
                "Stage 12: %s", _time_budget_warning["warning"]
            )
            (stage_dir / "time_budget_warning.json").write_text(
                json.dumps(_time_budget_warning, indent=2), encoding="utf-8"
            )

        # FIX-8: Validate seed count from structured results
        if structured_results and isinstance(structured_results, dict):
            _sr_conditions = structured_results.get("conditions", structured_results.get("per_condition", {}))
            if isinstance(_sr_conditions, dict):
                for _cname, _cdata in _sr_conditions.items():
                    if isinstance(_cdata, dict):
                        _seeds_run = _cdata.get("seeds_run", _cdata.get("n_seeds", 0))
                        if isinstance(_seeds_run, (int, float)) and 0 < _seeds_run < 3:
                            logger.warning(
                                "Stage 12: Condition '%s' ran only %d seed(s) — "
                                "minimum 3 required for statistical validity",
                                _cname, int(_seeds_run),
                            )

    elif mode == "simulated":
        schedule = _safe_json_loads(schedule_text, {})
        tasks = schedule.get("tasks", []) if isinstance(schedule, dict) else []
        if not isinstance(tasks, list):
            tasks = []
        for idx, task in enumerate(tasks or [{"id": "task-1", "name": "simulated"}]):
            task_id = (
                str(task.get("id", f"task-{idx + 1}"))
                if isinstance(task, dict)
                else f"task-{idx + 1}"
            )
            payload = {
                "run_id": f"run-{idx + 1}",
                "task_id": task_id,
                "status": "simulated",
                "key_metrics": {
                    config.experiment.metric_key: round(0.3 + idx * 0.03, 4),
                    "secondary_metric": round(0.6 - idx * 0.04, 4),
                },
                "notes": "Simulated run result",
                "completed_at": _utcnow_iso(),
            }
            run_id = str(payload["run_id"])
            (runs_dir / f"{_safe_filename(run_id)}.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
    else:
        runner = ExperimentRunner(config.experiment, runs_dir / "workspace")
        history = runner.run_loop(code_text, run_id=f"exp-{run_dir.name}", llm=llm)
        runner.save_history(stage_dir / "experiment_history.json")
        for item in history.results:
            payload = {
                "run_id": f"run-{item.iteration}",
                "task_id": item.run_id,
                "status": "completed" if item.error is None else "failed",
                "metrics": item.metrics,
                "primary_metric": item.primary_metric,
                "improved": item.improved,
                "kept": item.kept,
                "elapsed_sec": item.elapsed_sec,
                "error": item.error,
                "completed_at": _utcnow_iso(),
            }
            run_id = str(payload["run_id"])
            (runs_dir / f"{_safe_filename(run_id)}.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
    # FAB-1: Do not report `status: done, error: null` over runs that recorded
    # `failed` with empty metrics.  The stage still returns DONE so the Stage 13
    # refinement / repair loop can attempt a fix, but decision.json must carry
    # the truth — a downstream reader (human or stage) that sees error=null
    # reasonably concludes the experiment produced results.
    from researchclaw.pipeline.results_evidence import (
        collect_results_evidence as _collect_results_evidence,
    )
    _s12_evidence = _collect_results_evidence(run_dir)
    _s12_error: str | None = None
    _s12_decision = "proceed"
    if _s12_evidence.is_authoritative and not _s12_evidence.has_real_metrics:
        _s12_decision = "no_results"
        _s12_error = (
            "No run produced a finite metric: "
            + "; ".join(
                f"{e.source} {e.outcome} ({e.detail})"
                for e in _s12_evidence.executions
            )
        )
        logger.warning("Stage 12: %s", _s12_error)
        (stage_dir / "results_evidence.json").write_text(
            json.dumps(_s12_evidence.to_dict(), indent=2), encoding="utf-8"
        )

    # BUG-RUN-01: the metric-evidence check above stays silent when a run
    # crashes *after* emitting numbers — `status: failed` with a non-empty
    # `metrics` dict still reported `decision: proceed, error: null`. The
    # terminal status of each run payload is its own signal and must surface
    # too. Deliberately still StageStatus.DONE: Stage 12 is not in
    # NONCRITICAL_STAGES, so a FAILED result makes runner.py break out of the
    # pipeline and destroys the repair path (stage 13 refinement, then stage 14
    # diagnosis + repair) that can still recover a crashed run.
    _s12_outcome = _summarise_run_outcomes(runs_dir)
    (stage_dir / "run_outcome.json").write_text(
        json.dumps(_s12_outcome, indent=2), encoding="utf-8"
    )
    if _s12_outcome["degraded"]:
        logger.warning("Stage 12: %s", _s12_outcome["reason"])
        if _s12_decision == "proceed":
            _s12_decision = "degraded"
        _s12_error = "; ".join(
            part for part in (_s12_error, _s12_outcome["reason"]) if part
        )
    return StageResult(
        stage=Stage.EXPERIMENT_RUN,
        status=StageStatus.DONE,
        artifacts=("runs/", "run_outcome.json"),
        evidence_refs=("stage-12/runs/", "stage-12/run_outcome.json"),
        decision=_s12_decision,
        error=_s12_error,
    )


def _execute_iterative_refine(
    stage_dir: Path,
    run_dir: Path,
    config: RCConfig,
    adapters: AdapterBundle,
    *,
    llm: LLMClient | None = None,
    prompts: PromptManager | None = None,
) -> StageResult:
    from researchclaw.experiment.factory import create_sandbox
    from researchclaw.experiment.validator import format_issues_for_llm, validate_code

    def _to_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            f = float(value)
            # BUG-EX-01: NaN/Inf block all future improvement detection
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        except (TypeError, ValueError):
            return None

    # R10-Fix3: Skip iterative refinement in simulated mode (no real execution)
    if config.experiment.mode == "simulated":
        logger.info(
            "Stage 13: Skipping iterative refinement in simulated mode "
            "(no real code execution available)"
        )
        import shutil

        final_dir = stage_dir / "experiment_final"
        # Copy latest experiment code as final (directory or single file)
        copied = False
        for stage_num in (12, 10):
            src_dir = run_dir / f"stage-{stage_num:02d}" / "experiment"
            if src_dir.is_dir():
                if final_dir.exists():
                    shutil.rmtree(final_dir)
                shutil.copytree(src_dir, final_dir)
                copied = True
                break
            # Also check for single experiment.py
            src_file = run_dir / f"stage-{stage_num:02d}" / "experiment.py"
            if src_file.is_file():
                (stage_dir / "experiment_final.py").write_text(
                    src_file.read_text(encoding="utf-8"), encoding="utf-8"
                )
                copied = True
                break

        log: dict[str, Any] = {
            "generated": _utcnow_iso(),
            "mode": "simulated",
            "skipped": True,
            "skip_reason": "Iterative refinement not meaningful in simulated mode",
            "metric_key": config.experiment.metric_key,
        }
        (stage_dir / "refinement_log.json").write_text(
            json.dumps(log, indent=2), encoding="utf-8"
        )
        return StageResult(
            stage=Stage.ITERATIVE_REFINE,
            status=StageStatus.DONE,
            artifacts=("refinement_log.json",),
            evidence_refs=(),
        )

    metric_key = config.experiment.metric_key
    metric_direction = config.experiment.metric_direction

    # P9: Detect metric direction mismatch between config and experiment code.
    # The code-gen stage instructs experiments to print a line like:
    #   METRIC_DEF: primary_metric | direction=higher | desc=...
    # Log a warning if mismatch is detected, but trust the config value
    # (BUG-06 fix: no longer auto-override, since Stage 9 and 12 now
    # explicitly enforce config.metric_direction in prompts).
    _runs_dir_detect = _read_prior_artifact(run_dir, "runs/")
    if _runs_dir_detect and Path(_runs_dir_detect).is_dir():
        import re as _re_detect

        for _rf in sorted(Path(_runs_dir_detect).glob("*.json"))[:5]:
            try:
                _rp = _safe_json_loads(_rf.read_text(encoding="utf-8"), {})
                _stdout = _rp.get("stdout", "") if isinstance(_rp, dict) else ""
                _match = _re_detect.search(
                    r"METRIC_DEF:.*direction\s*=\s*(higher|lower)", _stdout
                )
                if _match:
                    _detected = _match.group(1)
                    _detected_dir = "maximize" if _detected == "higher" else "minimize"
                    if _detected_dir != metric_direction:
                        logger.warning(
                            "P9: Metric direction mismatch — config says '%s' but "
                            "experiment code declares 'direction=%s'. "
                            "Keeping config value '%s'. Code will be "
                            "corrected in next refinement cycle.",
                            metric_direction,
                            _detected,
                            metric_direction,
                        )
                    break
            except OSError:
                pass

    maximize = metric_direction == "maximize"

    def _is_better(candidate: float | None, current: float | None) -> bool:
        if candidate is None:
            return False
        if current is None:
            return True
        return candidate > current if maximize else candidate < current

    def _find_metric(metrics: dict[str, object], key: str) -> float | None:
        """R13-4: Find metric value with fuzzy key matching.

        Tries exact match first, then looks for aggregate keys that contain
        the metric name (e.g. 'primary_metric_mean' when key='primary_metric').
        """
        # Exact match
        val = _to_float(metrics.get(key))
        if val is not None:
            return val
        # Try aggregate/mean keys containing the metric name
        # Prefer keys ending with the metric name or containing '_mean'
        candidates: list[tuple[str, float]] = []
        for mk, mv in metrics.items():
            fv = _to_float(mv)
            if fv is None:
                continue
            if mk == key or mk.endswith(f"/{key}"):
                return fv  # Exact match via condition prefix
            if key in mk and ("mean" in mk or "avg" in mk):
                candidates.append((mk, fv))
            elif mk.endswith(f"_{key}") or mk.endswith(f"/{key}_mean"):
                candidates.append((mk, fv))
        if candidates:
            # Take the aggregate mean if available, otherwise first match
            for ck, cv in candidates:
                if "mean" in ck:
                    return cv
            return candidates[0][1]
        # Last resort: if there's an "overall" or root-level aggregate
        for mk, mv in metrics.items():
            fv = _to_float(mv)
            if fv is not None and key in mk and "/" not in mk and "seed" not in mk:
                return fv
        return None

    requested_iterations = int(getattr(config.experiment, "max_iterations", 10) or 10)
    max_iterations = max(1, min(requested_iterations, 10))

    # BUG-57: Wall-clock time cap for the entire refinement stage.
    # Default: 3× the per-iteration time budget (e.g., 2400s → 7200s = 2h).
    import time as _time_bug57
    _refine_start_time = _time_bug57.monotonic()
    _per_iter_budget = int(getattr(config.experiment, "time_budget_sec", 2400) or 2400)
    _max_refine_wall_sec = int(
        getattr(config.experiment, "max_refine_duration_sec", 0) or 0
    ) or int(_per_iter_budget * 1.5)

    # --- Collect baseline metrics from prior runs ---
    runs_dir_path: Path | None = None
    runs_dir_text = _read_prior_artifact(run_dir, "runs/")
    if runs_dir_text:
        runs_dir_path = Path(runs_dir_text)

    run_summaries: list[str] = []
    baseline_metric: float | None = None
    if runs_dir_path is not None:
        for run_file in sorted(runs_dir_path.glob("*.json"))[:40]:
            payload = _safe_json_loads(run_file.read_text(encoding="utf-8"), {})
            if not isinstance(payload, dict):
                continue
            # R5-5: Truncate stdout/stderr for context efficiency
            summary = dict(payload)
            if "stdout" in summary and isinstance(summary["stdout"], str):
                lines = summary["stdout"].splitlines()
                if len(lines) > 30:
                    summary["stdout"] = (
                        f"[...truncated {len(lines) - 30} lines...]\n"
                        + "\n".join(lines[-30:])
                    )
                if len(summary["stdout"]) > 2000:
                    summary["stdout"] = summary["stdout"][-2000:]
            if "stderr" in summary and isinstance(summary["stderr"], str):
                lines = summary["stderr"].splitlines()
                if len(lines) > 50:
                    summary["stderr"] = "\n".join(lines[-50:])
                if len(summary["stderr"]) > 2000:
                    summary["stderr"] = summary["stderr"][-2000:]
            run_summaries.append(json.dumps(summary, ensure_ascii=False))
            metrics = payload.get("metrics")
            if not isinstance(metrics, dict):
                metrics = (
                    payload.get("key_metrics")
                    if isinstance(payload.get("key_metrics"), dict)
                    else {}
                )
            metric_val = (
                _find_metric(metrics, metric_key)
                if isinstance(metrics, dict)
                else None
            )
            if metric_val is None:
                metric_val = _to_float(payload.get("primary_metric"))
            if _is_better(metric_val, baseline_metric):
                baseline_metric = metric_val

    # --- Read experiment project (multi-file or single-file) ---
    # BUG-58: When PIVOT rolls back to Stage 13, prefer the best refined code
    # from a previous cycle (stage-13_vX/experiment_final/) over the original
    # unrefined code (stage-12/experiment/ or stage-10/experiment/).
    # Enhanced: try ALL versioned directories (latest first) with fallback chain.
    exp_dir_text: str | None = None
    _prev_refine_dirs = sorted(
        run_dir.glob("stage-13_v*/experiment_final"),
        key=lambda p: p.parent.name,
        reverse=True,  # latest version first
    )
    # BUG-58 fix: Find the best version across ALL cycles (not just latest)
    _best_prev_metric: float | None = None
    _best_prev_dir: Path | None = None
    for _prd in _prev_refine_dirs:
        if not _prd.is_dir():
            continue
        _prd_log = _prd.parent / "refinement_log.json"
        if _prd_log.is_file():
            _prd_data = _safe_json_loads(
                _prd_log.read_text(encoding="utf-8"), {}
            )
            _prd_metric = _prd_data.get("best_metric") if isinstance(_prd_data, dict) else None
            if isinstance(_prd_metric, (int, float)) and _is_better(_prd_metric, _best_prev_metric):
                _best_prev_metric = _prd_metric
                _best_prev_dir = _prd
        elif _best_prev_dir is None:
            # No log but directory exists — use as fallback
            _best_prev_dir = _prd
    if _best_prev_dir is not None:
        exp_dir_text = str(_best_prev_dir)
        logger.info(
            "BUG-58: Recovered best refined code from PIVOT cycle: %s (metric=%s)",
            _best_prev_dir.parent.name,
            f"{_best_prev_metric:.4f}" if _best_prev_metric is not None else "N/A",
        )
    if not exp_dir_text:
        exp_dir_text = _read_prior_artifact(run_dir, "experiment/")
    best_files: dict[str, str] = {}
    if exp_dir_text and Path(exp_dir_text).is_dir():
        # BUG-EX-02: Load ALL text files (not just .py) — requirements.txt,
        # setup.py, config files are needed for Docker sandbox phases.
        for src_file in sorted(Path(exp_dir_text).iterdir()):
            if src_file.is_file() and src_file.suffix in (
                ".py", ".txt", ".yaml", ".yml", ".json", ".cfg", ".ini", ".sh",
            ):
                try:
                    best_files[src_file.name] = src_file.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    pass  # skip binary files
    if not best_files:
        # Backward compat: single experiment.py
        original_code = _read_prior_artifact(run_dir, "experiment.py") or ""
        if original_code:
            best_files = {"main.py": original_code}

    # --- Detect if prior experiment timed out ---
    prior_timed_out = False
    prior_time_budget = config.experiment.time_budget_sec
    if runs_dir_path is not None:
        for run_file in sorted(runs_dir_path.glob("*.json"))[:5]:
            try:
                payload = _safe_json_loads(run_file.read_text(encoding="utf-8"), {})
                if isinstance(payload, dict) and payload.get("timed_out"):
                    prior_timed_out = True
                    break
            except OSError:
                pass

    best_metric = baseline_metric
    best_version = "experiment/"
    # BUG-58: Recover best_metric from best previous PIVOT cycle
    if _best_prev_metric is not None and _is_better(_best_prev_metric, best_metric):
        best_metric = _best_prev_metric
        logger.info(
            "BUG-58: Recovered best_metric=%.4f from previous PIVOT",
            best_metric,
        )
    no_improve_streak = 0
    consecutive_no_metrics = 0

    # BUG-ADOPT-01: best validation-passing version by raw progress, tracked
    # independently of the metric so a crash that zeroes the metric for every
    # version cannot silently revert experiment_final to the original code.
    progress_files: dict[str, str] | None = None
    progress_version: str | None = None
    progress_key: tuple[int, int, int, int] | None = None

    log: dict[str, Any] = {
        "generated": _utcnow_iso(),
        "mode": config.experiment.mode,
        "metric_key": metric_key,
        "metric_direction": metric_direction,
        "max_iterations_requested": requested_iterations,
        "max_iterations_executed": max_iterations,
        "baseline_metric": baseline_metric,
        "project_files": list(best_files.keys()),
        "iterations": [],
        "converged": False,
        "stop_reason": "max_iterations_reached",
    }

    # --- Helper: write files to a directory ---
    def _write_project(target_dir: Path, project_files: dict[str, str]) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        for fname, code in project_files.items():
            (target_dir / fname).write_text(code, encoding="utf-8")

    # --- Helper: format all files for LLM context ---
    def _files_to_context(project_files: dict[str, str]) -> str:
        parts = []
        for fname, code in sorted(project_files.items()):
            parts.append(f"```filename:{fname}\n{code}\n```")
        return "\n\n".join(parts)

    def _write_refinement_log() -> None:
        (stage_dir / "refinement_log.json").write_text(
            json.dumps(log, indent=2), encoding="utf-8"
        )

    def _pause_refinement(
        *,
        reason: str,
        stop_reason: str,
        iteration: int | None = None,
    ) -> StageResult:
        log.update(
            {
                "paused": True,
                "converged": False,
                "stop_reason": stop_reason,
                "pause_reason": reason,
                "best_metric": best_metric,
                "best_version": best_version,
                "iterations_completed": len(log["iterations"]),
            }
        )
        if iteration is not None:
            log["pause_iteration"] = iteration
        _write_refinement_log()
        artifacts = ("refinement_log.json",)
        return StageResult(
            stage=Stage.ITERATIVE_REFINE,
            status=StageStatus.PAUSED,
            artifacts=artifacts,
            error=reason,
            decision="resume",
            evidence_refs=tuple(f"stage-13/{a}" for a in artifacts),
        )

    if llm is None:
        logger.info("Stage 13: LLM unavailable, saving original experiment as final")
        final_dir = stage_dir / "experiment_final"
        _write_project(final_dir, best_files)
        # Backward compat
        if "main.py" in best_files:
            (stage_dir / "experiment_final.py").write_text(
                best_files["main.py"], encoding="utf-8"
            )
        log.update(
            {
                "converged": True,
                "stop_reason": "llm_unavailable",
                "best_metric": best_metric,
                "best_version": "experiment_final/",
                "iterations": [
                    {
                        "iteration": 0,
                        "version_dir": "experiment_final/",
                        "source": "fallback_original",
                        "metric": best_metric,
                    }
                ],
            }
        )
        _write_refinement_log()
        artifacts = ("refinement_log.json", "experiment_final/")
        return StageResult(
            stage=Stage.ITERATIVE_REFINE,
            status=StageStatus.DONE,
            artifacts=artifacts,
            evidence_refs=tuple(f"stage-13/{a}" for a in artifacts),
        )

    _pm = prompts or PromptManager()
    timeout_refine_attempts = 0

    # R7-3: Read experiment plan to detect condition coverage gaps
    _exp_plan_text = _read_prior_artifact(run_dir, "exp_plan.yaml") or ""
    _condition_coverage_hint = ""
    if _exp_plan_text and run_summaries:
        # Check if stdout contains condition labels
        _all_stdout = " ".join(run_summaries)
        _has_condition_labels = bool(_CONDITION_LABEL_RE.search(_all_stdout))
        # BUG-COND-01: the original test was `"condition=" in _all_stdout`, so a
        # SINGLE surviving condition out of five read as full coverage and the
        # hint fell silent on exactly the runs that most need it. Reuse the
        # prior-run metrics to ask which registered conditions actually scored.
        _prior_metrics: dict[str, Any] = {}
        if runs_dir_path is not None:
            for _rf in sorted(runs_dir_path.glob("run-*.json")):
                _rp = _safe_json_loads(_rf.read_text(encoding="utf-8"), {})
                if isinstance(_rp, dict) and isinstance(_rp.get("metrics"), dict):
                    _prior_metrics.update(_rp["metrics"])
        _prior_coverage = _condition_coverage(_all_stdout, _prior_metrics)
        _prior_gap = _describe_condition_gap(_prior_coverage)
        if _prior_gap and _exp_plan_text.strip():
            _condition_coverage_hint = (
                "\nCONDITION COVERAGE GAP DETECTED:\n"
                f"{_prior_gap}\n"
                "You MUST:\n"
                "1. Run ALL conditions/treatments from the experiment plan independently\n"
                "2. Label each metric output: `condition=<name> {metric_key}: <value>`\n"
                "3. Print a SUMMARY line comparing all conditions after completion\n"
                "4. Ensure a condition that fails does not silently skip the rest — "
                "report it and continue to the remaining conditions\n"
                "This is the MOST IMPORTANT improvement — metrics from a subset of "
                "conditions cannot support any comparative conclusions.\n\n"
            )
            logger.warning("Stage 13: %s", _prior_gap)
        elif not _has_condition_labels and _exp_plan_text.strip():
            _condition_coverage_hint = (
                "\nCONDITION COVERAGE GAP DETECTED:\n"
                "The experiment plan specifies multiple conditions/treatments, "
                "but the output contains NO condition labels (no 'condition=...' in stdout).\n"
                "You MUST:\n"
                "1. Run ALL conditions/treatments from the experiment plan independently\n"
                "2. Label each metric output: `condition=<name> {metric_key}: <value>`\n"
                "3. Print a SUMMARY line comparing all conditions after completion\n"
                "This is the MOST IMPORTANT improvement — a single unlabeled metric stream "
                "cannot support any comparative conclusions.\n\n"
            )
            logger.info(
                "Stage 13: condition coverage gap detected, injecting multi-condition hint"
            )

    # P1: Track metrics history for saturation detection
    _metrics_history: list[float | None] = [baseline_metric]

    for iteration in range(1, max_iterations + 1):
        # BUG-57: Check wall-clock time before starting a new iteration
        _elapsed = _time_bug57.monotonic() - _refine_start_time
        if _elapsed > _max_refine_wall_sec:
            logger.warning(
                "Stage 13: Wall-clock time cap reached (%.0fs > %ds). "
                "Stopping refinement after %d iterations.",
                _elapsed, _max_refine_wall_sec, iteration - 1,
            )
            log["stop_reason"] = "wall_clock_time_cap"
            break
        logger.info("Stage 13: refinement iteration %d/%d (%.0fs elapsed, cap %ds)",
                    iteration, max_iterations, _elapsed, _max_refine_wall_sec)

        # P1: Detect metric saturation and inject difficulty upgrade hint
        _saturation_hint = ""
        _valid_metrics = [m for m in _metrics_history if m is not None]
        if len(_valid_metrics) >= 2:
            _last_two = _valid_metrics[-2:]
            _saturated = False
            # Use relative change rate instead of hard-coded thresholds
            _change_rate = abs(_last_two[-1] - _last_two[-2]) / max(abs(_last_two[-2]), 1e-8)
            if metric_direction == "minimize":
                _saturated = all(m <= 0.001 for m in _last_two) or (
                    _change_rate < 0.001 and _last_two[-1] < 0.01
                )
            else:
                _saturated = all(m >= 0.999 for m in _last_two) or (
                    _change_rate < 0.001 and _last_two[-1] > 0.99
                )
            if _saturated:
                _saturation_hint = (
                    "\n\nWARNING — BENCHMARK SATURATION DETECTED:\n"
                    "All methods achieve near-perfect scores, making the task too easy "
                    "to discriminate between methods.\n"
                    "YOU MUST increase benchmark difficulty in this iteration:\n"
                    "1. Increase the number of actions/decisions from 8 to at least 20\n"
                    "2. Increase the horizon from 12-18 to at least 50-100 steps\n"
                    "3. Increase noise level to at least 0.3-0.5\n"
                    "4. Add partial observability (agent cannot see full state)\n"
                    "5. Add delayed rewards (reward only at episode end)\n"
                    "6. Ensure random search achieves < 50% success rate\n"
                    "Without this change, the experiment produces meaningless results.\n"
                )
                logger.warning("Stage 13: metric saturation detected, injecting difficulty upgrade hint")

        # BUG-ADOPT-01: while no version has produced a metric, `best_files` is
        # pinned to the original code, so every iteration re-refines the
        # original and improvements never compound (this is why successive
        # codegen attempts look byte-identical). Refine from the best progress
        # candidate instead; the ranking is monotone, so a regressing iteration
        # is not fed forward. Once a metric exists, `best_files` governs again
        # and behaviour is unchanged.
        refine_source_files = best_files
        refine_source_version = best_version
        if best_metric is None and progress_files is not None:
            refine_source_files = progress_files
            refine_source_version = progress_version or best_version

        files_context = _files_to_context(refine_source_files)
        # BUG-10 fix: anchor refinement to original experiment plan
        _exp_plan_anchor = ""
        if _exp_plan_text.strip():
            _exp_plan_anchor = (
                "Original experiment plan (exp_plan.yaml):\n"
                "```yaml\n" + _exp_plan_text[:4000] + "\n```\n"
                "You MUST preserve ALL condition names from this plan.\n\n"
            )
        ip = _pm.sub_prompt(
            "iterative_improve",
            metric_key=metric_key,
            metric_direction=metric_direction,
            files_context=files_context,
            run_summaries=chr(10).join(run_summaries[:20]),
            condition_coverage_hint=_condition_coverage_hint,
            topic=config.research.topic,
            exp_plan_anchor=_exp_plan_anchor,
        )

        # --- Timeout-aware prompt injection ---
        user_prompt = ip.user + _saturation_hint
        if prior_timed_out and baseline_metric is None:
            timeout_refine_attempts += 1
            timeout_hint = (
                f"\n\nCRITICAL: The experiment TIMED OUT after {prior_time_budget}s "
                f"with NO results. You MUST drastically reduce the experiment scale:\n"
                f"- Reduce total runs to ≤50\n"
                f"- Reduce steps per run to ≤2000\n"
                f"- Remove conditions that are not essential\n"
                f"- Add time.time() checks to stop gracefully before timeout\n"
                f"- Print intermediate metrics frequently so partial data is captured\n"
                f"- Time budget is {prior_time_budget}s — design for ≤{int(prior_time_budget * 0.7)}s\n"
            )
            user_prompt = user_prompt + timeout_hint
            logger.warning(
                "Stage 13: injecting timeout-aware prompt (attempt %d)",
                timeout_refine_attempts,
            )

        try:
            response = _chat_with_prompt(
                llm,
                ip.system,
                user_prompt,
                max_tokens=ip.max_tokens or 8192,
            )
        except RuntimeError as exc:
            if "ACP prompt timed out after" in str(exc):
                logger.warning(
                    "Stage 13: ACP prompt timed out during iteration %d; pausing for resume",
                    iteration,
                )
                return _pause_refinement(
                    reason=str(exc),
                    stop_reason="acp_prompt_timeout",
                    iteration=iteration,
                )
            raise
        extracted_files = _extract_multi_file_blocks(response.content)
        # If LLM returns only single block, treat as main.py update
        if not extracted_files:
            single_code = _extract_code_block(response.content)
            if single_code.strip():
                extracted_files = {"main.py": single_code}
        # R8-2: Merge with the refinement source to preserve supporting modules
        # (e.g., graphs.py, game.py) that the LLM didn't rewrite
        candidate_files = dict(refine_source_files)
        if extracted_files:
            candidate_files.update(extracted_files)
        # If LLM returned nothing at all, candidate_files == refine_source_files

        # BUG-R6-02: Preserve entry point when LLM strips main() function.
        # The LLM often returns only class/function improvements without the
        # main() entry point, causing the script to exit with no output.
        _new_main = candidate_files.get("main.py", "")
        _old_main = refine_source_files.get("main.py", "")
        if (
            _new_main
            and _old_main
            and "if __name__" not in _new_main
            and "if __name__" in _old_main
        ):
            # Extract the entry-point block from original main.py
            _ep_idx = _old_main.rfind("\ndef main(")
            if _ep_idx == -1:
                _ep_idx = _old_main.rfind("\nif __name__")
            if _ep_idx != -1:
                _entry_block = _old_main[_ep_idx:]
                candidate_files["main.py"] = _new_main.rstrip() + "\n\n" + _entry_block
                logger.info(
                    "Stage 13 iter %d: restored entry point stripped by LLM "
                    "(%d chars appended from original main.py)",
                    iteration,
                    len(_entry_block),
                )

        # Validate main.py
        main_code = candidate_files.get("main.py", "")
        validation = validate_code(main_code)
        issue_text = ""
        repaired = False

        if not validation.ok:
            issue_text = format_issues_for_llm(validation)
            logger.info(
                "Stage 13 iteration %d validation failed: %s",
                iteration,
                validation.summary(),
            )
            irp = _pm.sub_prompt(
                "iterative_repair",
                issue_text=issue_text,
                all_files_ctx=_files_to_context(candidate_files),
            )
            try:
                repair_response = _chat_with_prompt(llm, irp.system, irp.user)
            except RuntimeError as exc:
                if "ACP prompt timed out after" in str(exc):
                    logger.warning(
                        "Stage 13: ACP repair prompt timed out during iteration %d; pausing for resume",
                        iteration,
                    )
                    return _pause_refinement(
                        reason=str(exc),
                        stop_reason="acp_prompt_timeout",
                        iteration=iteration,
                    )
                raise
            candidate_files["main.py"] = _extract_code_block(repair_response.content)
            validation = validate_code(candidate_files["main.py"])
            repaired = True

        # Save version directory
        version_dir = stage_dir / f"experiment_v{iteration}"
        _write_project(version_dir, candidate_files)

        iter_record: dict[str, Any] = {
            "iteration": iteration,
            "version_dir": f"experiment_v{iteration}/",
            "files": list(candidate_files.keys()),
            "validation_ok": validation.ok,
            "validation_summary": validation.summary(),
            "repaired": repaired,
            "metric": None,
            "improved": False,
            "refined_from": refine_source_version,
        }
        if issue_text:
            iter_record["validation_issues"] = issue_text

        metric_val = None  # R6-3: initialize before conditional block
        if validation.ok and config.experiment.mode in ("sandbox", "docker"):
            # P7: Ensure deps for refined code (subprocess sandbox only)
            if config.experiment.mode == "sandbox":
                _refine_code = "\n".join(candidate_files.values())
                _ensure_sandbox_deps(_refine_code, config.experiment.sandbox.python_path)

            sandbox = create_sandbox(
                config.experiment,
                stage_dir / f"refine_sandbox_v{iteration}",
            )
            rerun = sandbox.run_project(
                version_dir,
                timeout_sec=config.experiment.time_budget_sec,
            )
            metric_val = _find_metric(rerun.metrics, metric_key)
            # R19-1: Store stdout (capped) so PAIRED lines survive for Stage 14
            _stdout_cap = rerun.stdout[:50000] if rerun.stdout else ""
            iter_record["sandbox"] = {
                "returncode": rerun.returncode,
                "metrics": rerun.metrics,
                "elapsed_sec": rerun.elapsed_sec,
                "timed_out": rerun.timed_out,
                "stderr": rerun.stderr[:2000] if rerun.stderr else "",
                "stdout": _stdout_cap,
            }
            iter_record["metric"] = metric_val

            # BUG-110: Parse ABLATION_CHECK lines from stdout
            if rerun.stdout:
                import re as _re_ablation
                _ablation_checks = _re_ablation.findall(
                    r"ABLATION_CHECK:\s*(\S+)\s+vs\s+(\S+)\s+outputs_differ=(True|False)",
                    rerun.stdout,
                )
                if _ablation_checks:
                    _identical_pairs = [
                        (c1, c2) for c1, c2, diff in _ablation_checks if diff == "False"
                    ]
                    iter_record["ablation_checks"] = [
                        {"cond1": c1, "cond2": c2, "differ": diff == "True"}
                        for c1, c2, diff in _ablation_checks
                    ]
                    if _identical_pairs:
                        _pairs_str = ", ".join(f"{c1} vs {c2}" for c1, c2 in _identical_pairs)
                        logger.warning(
                            "BUG-110: Identical ablation outputs detected: %s. "
                            "Ablation conditions may not be wired correctly.",
                            _pairs_str,
                        )
                        iter_record["ablation_identical"] = True

            # --- Track timeout in refine sandbox ---
            if rerun.timed_out:
                prior_timed_out = True
                timeout_refine_attempts += 1
                logger.warning(
                    "Stage 13 iteration %d: sandbox timed out after %.1fs",
                    iteration,
                    rerun.elapsed_sec,
                )
                # If still no metrics after timeout, use partial stdout metrics
                if not rerun.metrics and rerun.stdout:
                    from researchclaw.experiment.sandbox import parse_metrics as _parse_sb_metrics
                    partial = _parse_sb_metrics(rerun.stdout)
                    if partial:
                        iter_record["sandbox"]["metrics"] = partial
                        metric_val = _find_metric(partial, metric_key)
                        iter_record["metric"] = metric_val
                        logger.info(
                            "Stage 13 iteration %d: recovered %d partial metrics from timeout stdout",
                            iteration,
                            len(partial),
                        )

            # --- Detect runtime issues (NaN/Inf, stderr warnings) ---
            runtime_issues = _detect_runtime_issues(rerun)
            if runtime_issues:
                iter_record["runtime_issues"] = runtime_issues
                logger.info(
                    "Stage 13 iteration %d: runtime issues detected: %s",
                    iteration,
                    runtime_issues[:200],
                )
                # Attempt LLM repair with runtime context
                rrp = _pm.sub_prompt(
                    "iterative_repair",
                    issue_text=runtime_issues,
                    all_files_ctx=_files_to_context(candidate_files),
                )
                try:
                    repair_resp = _chat_with_prompt(llm, rrp.system, rrp.user)
                except RuntimeError as exc:
                    if "ACP prompt timed out after" in str(exc):
                        logger.warning(
                            "Stage 13: ACP runtime-repair prompt timed out during iteration %d; pausing for resume",
                            iteration,
                        )
                        return _pause_refinement(
                            reason=str(exc),
                            stop_reason="acp_prompt_timeout",
                            iteration=iteration,
                        )
                    raise
                repaired_files = _extract_multi_file_blocks(repair_resp.content)
                if not repaired_files:
                    single = _extract_code_block(repair_resp.content)
                    if single.strip():
                        repaired_files = dict(candidate_files)
                        repaired_files["main.py"] = single
                if repaired_files:
                    # BUG-106 fix: merge instead of replace to preserve
                    # supporting modules (trainers.py, utils.py, etc.)
                    merged = dict(candidate_files)
                    merged.update(repaired_files)
                    candidate_files = merged
                    _write_project(version_dir, candidate_files)
                    # Re-run after runtime fix
                    sandbox2 = create_sandbox(
                        config.experiment,
                        stage_dir / f"refine_sandbox_v{iteration}_fix",
                    )
                    rerun2 = sandbox2.run_project(
                        version_dir,
                        timeout_sec=config.experiment.time_budget_sec,
                    )
                    metric_val = _find_metric(rerun2.metrics, metric_key)
                    iter_record["sandbox_after_fix"] = {
                        "returncode": rerun2.returncode,
                        "metrics": rerun2.metrics,
                        "elapsed_sec": rerun2.elapsed_sec,
                        "timed_out": rerun2.timed_out,
                    }
                    iter_record["metric"] = metric_val
                    iter_record["runtime_repaired"] = True

            if metric_val is not None:
                consecutive_no_metrics = 0
                # R6-1: Only count toward no_improve_streak when we have real metrics
                if _is_better(metric_val, best_metric):
                    best_metric = metric_val
                    best_files = dict(candidate_files)
                    best_version = f"experiment_v{iteration}/"
                    iter_record["improved"] = True
                    no_improve_streak = 0
                else:
                    no_improve_streak += 1
            else:
                consecutive_no_metrics += 1
                # BUG-METRIC-01: "no metric" and "no results" are different
                # failures and used to be reported identically.
                _miss = _describe_metric_key_miss(
                    metric_key, _last_sandbox_record(iter_record).get("metrics") or {}
                )
                if _miss:
                    iter_record["metric_key_mismatch"] = _miss
                    logger.warning("Stage 13 iteration %d: %s", iteration, _miss)

        # BUG-COND-01: record which registered conditions actually scored,
        # before the progress ranking reads it. Computed even when a metric
        # exists — a run that scores on one of five conditions is exactly the
        # shape that produced a fabricated comparison in run 4.
        # NB: stdout and metrics come from DIFFERENT records on a repaired
        # iteration — `sandbox_after_fix` carries the metrics with no stdout.
        _coverage = _condition_coverage(
            _registry_stdout(iter_record),
            _last_sandbox_record(iter_record).get("metrics") or {},
        )
        if _coverage["registered_count"] or _coverage["scored_count"]:
            iter_record["condition_coverage"] = _coverage
            _gap = _describe_condition_gap(_coverage)
            if _gap:
                logger.warning("Stage 13 iteration %d: %s", iteration, _gap)

        # BUG-ADOPT-01: rank this version by raw progress, whether or not it
        # produced the primary metric. This replaces the
        # `elif validation.ok and best_version == "experiment/"` fallback that
        # used to sit here: it was the orelse of
        # `if validation.ok and mode in ("sandbox", "docker")` while itself
        # requiring validation.ok, so in the modes that actually run code it
        # was unreachable (AST-verified). The adoption decision now happens
        # after the loop, in _decide_refinement_adoption, and is logged.
        if validation.ok:
            _iter_progress = _refinement_progress_key(iteration, iter_record)
            iter_record["progress_key"] = list(_iter_progress)
            if progress_key is None or _iter_progress > progress_key:
                progress_key = _iter_progress
                progress_files = dict(candidate_files)
                progress_version = f"experiment_v{iteration}/"

        # P1: Track metric for saturation detection
        _metrics_history.append(metric_val)

        log["iterations"].append(iter_record)

        if consecutive_no_metrics >= 3:
            log["stop_reason"] = "consecutive_no_metrics"
            logger.warning("Stage 13: Aborting after %d consecutive iterations without metrics", consecutive_no_metrics)
            break

        if no_improve_streak >= 2:
            log["converged"] = True
            log["stop_reason"] = "no_improvement_for_2_iterations"
            logger.info(
                "Stage 13 converged after %d iterations (no improvement streak=%d)",
                iteration,
                no_improve_streak,
            )
            break

    # BUG-ADOPT-01: decide — and RECORD — which version becomes the final one.
    # Previously this was implicit: whatever `best_files` happened to hold,
    # with no log line when that was the unmodified original.
    _adopted_version, _adoption_reason = _decide_refinement_adoption(
        best_version=best_version,
        best_metric=best_metric,
        progress_version=progress_version,
        progress_key=progress_key,
    )
    if _adopted_version != best_version and progress_files is not None:
        best_files = dict(progress_files)
        best_version = _adopted_version
        logger.warning(
            "Stage 13: no version produced metric '%s'; adopting %s on progress "
            "(exited_cleanly=%d, conditions_scored=%d, metric_keys=%d, "
            "not_timed_out=%d, iteration=%d) "
            "rather than reverting experiment_final to the original code.",
            metric_key,
            best_version,
            *(progress_key or (0, 0, 0, 0, 0)),
        )
    elif _adoption_reason == "original_retained_no_valid_candidate":
        logger.warning(
            "Stage 13: no refinement candidate passed validation — "
            "experiment_final is the ORIGINAL experiment code."
        )
    logger.info(
        "Stage 13 adoption: version=%s reason=%s best_metric=%s",
        best_version,
        _adoption_reason,
        best_metric,
    )
    log["adoption_reason"] = _adoption_reason
    log["adoption_progress_key"] = list(progress_key) if progress_key else None
    log["progress_version"] = progress_version
    # BUG-METRIC-01: surface the mismatch at the top of the log, not only
    # buried per-iteration — a `best_metric: null` with metrics on disk means
    # "unscorable config", not "the experiment produced nothing".
    _mismatches = [
        entry["metric_key_mismatch"]
        for entry in log["iterations"]
        if isinstance(entry, dict) and entry.get("metric_key_mismatch")
    ]
    # BUG-COND-01: hoist the coverage of the ADOPTED version, so a consumer can
    # ask "was the proposed method among the scored?" without walking
    # iterations. Stage 17's anti-fabrication guard is the intended reader: it
    # currently fires only on ZERO metrics, so one surviving ablation disarms
    # it and the writing stage is free to report a control's number under the
    # proposed method's name. This is the fact that guard needs.
    _adopted_entry = next(
        (
            entry
            for entry in reversed(log["iterations"])
            if isinstance(entry, dict)
            and entry.get("version_dir") == best_version
        ),
        None,
    )
    _adopted_coverage = (
        _adopted_entry.get("condition_coverage")
        if isinstance(_adopted_entry, dict)
        else None
    )
    if isinstance(_adopted_coverage, dict):
        log["condition_coverage"] = _adopted_coverage
        _gap = _describe_condition_gap(_adopted_coverage)
        if _gap:
            log["condition_coverage_gap"] = _gap
            logger.warning("Stage 13: adopted version %s — %s", best_version, _gap)

        # BUG-COND-02: registered-vs-scored cannot see a condition the code
        # never registered. In run 1 the proposed method was never defined at
        # all; in run 4 all three declared BASELINES went unregistered — and
        # the fabricated baseline row in the paper is one of them. The gap
        # between what the plan promises and what the code registers is where
        # fabrication has a declared hook, so it needs its own field.
        _plan_status = _plan_vs_scored(
            _declared_conditions(_exp_plan_text), _adopted_coverage
        )
        if _plan_status["declared_count"]:
            log["plan_condition_status"] = _plan_status
            _plan_gap = _describe_plan_gap(_plan_status)
            if _plan_gap:
                log["plan_condition_gap"] = _plan_gap
                logger.warning("Stage 13: %s", _plan_gap)

    if _mismatches:
        log["metric_key_mismatch"] = _mismatches[-1]
        logger.warning(
            "Stage 13: metric_key %r matched nothing in %d/%d iteration(s) — "
            "the adoption score was unavailable by configuration, not by failure.",
            metric_key,
            len(_mismatches),
            len(log["iterations"]),
        )

    # Write final experiment directory
    final_dir = stage_dir / "experiment_final"
    _write_project(final_dir, best_files)
    # Backward compat: also write experiment_final.py (copy of main.py)
    if "main.py" in best_files:
        (stage_dir / "experiment_final.py").write_text(
            best_files["main.py"], encoding="utf-8"
        )

    log["best_metric"] = best_metric
    log["best_version"] = best_version
    log["final_version"] = "experiment_final/"
    # BUG-110: Aggregate ablation check results across iterations
    _all_ablation_identical = any(
        iter_rec.get("ablation_identical", False)
        for iter_rec in log.get("iterations", [])
        if isinstance(iter_rec, dict)
    )
    if _all_ablation_identical:
        log["ablation_identical_warning"] = True
    _write_refinement_log()

    artifacts = ["refinement_log.json", "experiment_final/"]
    artifacts.extend(
        entry["version_dir"]
        for entry in log["iterations"]
        if isinstance(entry, dict) and isinstance(entry.get("version_dir"), str)
    )
    return StageResult(
        stage=Stage.ITERATIVE_REFINE,
        status=StageStatus.DONE,
        artifacts=tuple(artifacts),
        evidence_refs=tuple(f"stage-13/{a}" for a in artifacts),
    )
