"""FAB-1: execution-artefact reconciliation must not be defeatable by log text.

Regression tests for the 2026-07-31 fabrication incident, in which run
``rc-ws3-h2-real4-20260731`` shipped a 27 KB paper of invented numbers from an
experiment whose only stage-12 run recorded ``status: failed, metrics: {}``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from researchclaw.pipeline.results_evidence import (
    ExecutionRecord,
    collect_results_evidence,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _run(run_dir: Path, name: str, **payload) -> None:
    _write(run_dir / "stage-12" / "runs" / name, payload)


def _refine(run_dir: Path, stage: str, iterations: list[dict]) -> None:
    _write(run_dir / stage / "refinement_log.json", {"iterations": iterations})


# ---------------------------------------------------------------------------
# The exact incident
# ---------------------------------------------------------------------------


def test_crashed_run_with_condition_progress_lines_is_not_evidence(tmp_path):
    """The defeated guard: stdout progress messages must not count.

    The real run printed ``Running condition: NoWidening`` and two other
    ``condition``-bearing lines before dying, which satisfied the old
    ``>= 3 x condition[=:]`` rule.
    """
    _run(
        tmp_path,
        "run-1.json",
        run_id="run-1",
        status="failed",
        metrics={},
        timed_out=False,
        stdout=(
            "METRIC_DEF: CRPS, Coverage90\n"
            "REGISTERED_CONDITIONS: NoWidening, DivergenceConditionedWidener\n"
            "Running condition: NoWidening\n"
            "condition=NoWidening seed=0\n"
            "condition=NoWidening seed=1\n"
        ),
        stderr="TypeError: unsupported operand type(s) for *: 'Timestamp' and 'float'",
    )
    ev = collect_results_evidence(tmp_path)
    assert ev.is_authoritative
    assert ev.has_real_metrics is False
    assert ev.finite_metric_values == ()
    assert ev.blocking_reasons()


def test_metrics_emitted_before_a_nonzero_exit_are_not_verified(tmp_path):
    """A returncode=1 sandbox emitted 34 metrics for one condition. Those are
    the numbers the paper's fabricated table was laundered through."""
    _run(tmp_path, "run-1.json", status="failed", metrics={}, timed_out=False)
    _refine(
        tmp_path,
        "stage-13",
        [
            {
                "version_dir": "experiment_v1/",
                "sandbox": {
                    "returncode": 1,
                    "timed_out": False,
                    "metrics": {
                        "NoWidening/0/CRPS": 707213.5866951895,
                        "NoWidening/CRPS": 707213.5866951895,
                        "NoWidening/0/Coverage90": 0.9200945626477541,
                    },
                },
            }
        ],
    )
    ev = collect_results_evidence(tmp_path)
    assert ev.has_real_metrics is False
    assert ev.verified_conditions == ()
    # The condition is *named* by a failed execution — that is exactly the
    # trap, so it must be reported as unverified rather than silently dropped.
    assert ev.unverified_conditions == ("NoWidening",)
    assert ev.orphan_metric_count == 3


# ---------------------------------------------------------------------------
# No false positives
# ---------------------------------------------------------------------------


def test_clean_exit_with_metrics_is_evidence(tmp_path):
    _run(
        tmp_path,
        "run-1.json",
        status="completed",
        metrics={"MethodA/0/CRPS": 12.5, "MethodA/CRPS": 12.5},
        timed_out=False,
    )
    ev = collect_results_evidence(tmp_path)
    assert ev.has_real_metrics is True
    assert ev.verified_conditions == ("MethodA",)
    assert ev.blocking_reasons() == []


def test_refinement_sandbox_returncode_zero_is_evidence(tmp_path):
    _run(tmp_path, "run-1.json", status="failed", metrics={}, timed_out=False)
    _refine(
        tmp_path,
        "stage-13",
        [
            {
                "version_dir": "experiment_v1/",
                "sandbox": {"returncode": 1, "timed_out": False, "metrics": {}},
                "sandbox_after_fix": {
                    "returncode": 0,
                    "timed_out": False,
                    "metrics": {"MethodA/CRPS": 11.2},
                },
            }
        ],
    )
    ev = collect_results_evidence(tmp_path)
    assert ev.has_real_metrics is True
    assert ev.verified_conditions == ("MethodA",)


def test_timeout_with_metrics_counts_as_degraded_evidence(tmp_path):
    """A timeout is a budget outcome, not a broken contract."""
    _run(
        tmp_path,
        "run-1.json",
        status="partial",
        metrics={"MethodA/CRPS": 9.0},
        timed_out=True,
    )
    ev = collect_results_evidence(tmp_path)
    assert ev.has_real_metrics is True
    assert [e.outcome for e in ev.executions] == ["degraded"]


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------


def test_no_execution_artifacts_is_not_authoritative(tmp_path):
    """Silence is not absence: with nothing to reconcile against, the module
    must not assert either way (theoretical domains record no runs)."""
    (tmp_path / "stage-14").mkdir(parents=True)
    ev = collect_results_evidence(tmp_path)
    assert ev.is_authoritative is False
    assert ev.blocking_reasons() == []


def test_simulated_status_is_never_evidence(tmp_path):
    _run(tmp_path, "run-1.json", status="simulated", metrics={"acc": 0.33})
    ev = collect_results_evidence(tmp_path)
    assert ev.has_real_metrics is False
    assert ev.executions[0].outcome == "simulated"


def test_clean_exit_with_empty_metrics_is_not_evidence(tmp_path):
    _run(tmp_path, "run-1.json", status="completed", metrics={}, timed_out=False)
    ev = collect_results_evidence(tmp_path)
    assert ev.has_real_metrics is False


def test_infrastructure_counters_are_not_results(tmp_path):
    _run(
        tmp_path,
        "run-1.json",
        status="completed",
        metrics={"elapsed_sec": 12.0, "SEED_COUNT": 3, "total_runs": 1},
        timed_out=False,
    )
    ev = collect_results_evidence(tmp_path)
    assert ev.has_real_metrics is False


def test_non_finite_and_boolean_values_are_not_results(tmp_path):
    _run(
        tmp_path,
        "run-1.json",
        status="completed",
        metrics={"MethodA/CRPS": float("nan"), "converged": True},
        timed_out=False,
    )
    ev = collect_results_evidence(tmp_path)
    assert ev.has_real_metrics is False


def test_infra_key_match_is_whole_token_not_substring(tmp_path):
    """``total_runs`` is infrastructure; ``total_runs_recovered`` is not."""
    _run(
        tmp_path,
        "run-1.json",
        status="completed",
        metrics={"MethodA/total_runs_recovered": 4.0},
        timed_out=False,
    )
    ev = collect_results_evidence(tmp_path)
    assert ev.has_real_metrics is True


def test_evidence_does_not_require_the_configured_metric_key(tmp_path):
    """A `metric_key` mismatch must never read as "no results".

    In `rc-ws3-h2-real4-20260731`, `config.experiment.metric_key` was
    `primary_metric` while the experiment emitted CRPS / Coverage90 / Width90 /
    PinballLoss.  `_find_metric` matches on `key in mk`, so no emitted key could
    ever match and even a perfectly clean run scores `metric_val = None`.
    This module must key on "any finite non-infra metric", never on the
    configured metric name, or that mismatch would masquerade as a crash.
    """
    _run(
        tmp_path,
        "run-1.json",
        status="completed",
        metrics={
            "NoWidening/0/CRPS": 707213.5866951895,
            "NoWidening/Coverage90": 0.9200945626477541,
            "NoWidening/PinballLoss": 64.46545339560637,
        },
        timed_out=False,
    )
    ev = collect_results_evidence(tmp_path)
    assert ev.has_real_metrics is True
    assert ev.verified_conditions == ("NoWidening",)
    assert len(ev.finite_metric_values) == 3


def test_has_real_metrics_is_provenance_not_validity(tmp_path):
    """Pin the guarantee's boundary so it is never over-quoted.

    The 2026-07-31 baseline evaluator computed `crps = (upper - lower) / 2` —
    the interval half-width — with `predict()` returning feature columns and no
    model fitting anything.  Under `metric_key: CRPS` + `minimize`, the argmin
    of that objective is `lower == upper`: zero-width intervals, coverage 0.

    Such a run terminates cleanly and emits finite numbers, so it PASSES here,
    and that is correct: the numbers really were produced.  This module
    certifies provenance, never validity.  Deciding CRPS must be minimised
    subject to a coverage floor is authoring the experiment's evaluation, which
    belongs in the experiment plan, not in an integrity gate.

    If this test ever starts failing because someone taught the module to judge
    plausibility, that is a design change requiring a deliberate decision — not
    a bug fix.
    """
    _run(
        tmp_path,
        "run-1.json",
        status="completed",
        metrics={
            "Degenerate/CRPS": 0.0,  # zero-width intervals: the argmin
            "Degenerate/Width90": 0.0,
            "Degenerate/Coverage90": 0.0,  # ...and nothing is ever covered
        },
        timed_out=False,
    )
    ev = collect_results_evidence(tmp_path)
    assert ev.has_real_metrics is True
    assert ev.verified_conditions == ("Degenerate",)
    assert ev.blocking_reasons() == []


def test_unverified_conditions_cannot_see_conditions_that_never_ran(tmp_path):
    """Pin the field's semantics so it is not misread as "all unsupported".

    `unverified_conditions` can only name conditions that emitted at least one
    metric key. In the real run, 5 conditions were registered and only
    `NoWidening` ever emitted anything — so the field reports exactly
    `("NoWidening",)` while four declared wideners are invisible.

    Reading that as "one condition is questionable" is the mistake this test
    exists to prevent. Establishing the declared set needs the experiment
    plan, not the execution record.
    """
    _run(
        tmp_path,
        "run-1.json",
        status="failed",
        metrics={"NoWidening/CRPS": 707213.5866951895},
        timed_out=False,
        stdout=(
            "REGISTERED_CONDITIONS: NoWidening, ShuffledDivergenceWidener, "
            "DivergenceConditionedWidener, VolatilityConditionedWidener, "
            "NormalizedConformalWidener\n"
            "Running condition: NoWidening\n"
        ),
    )
    ev = collect_results_evidence(tmp_path)
    assert ev.has_real_metrics is False
    # Only the condition that emitted something is named...
    assert ev.unverified_conditions == ("NoWidening",)
    # ...and the four that never ran are absent, by design, not by accident.
    for never_ran in (
        "ShuffledDivergenceWidener",
        "DivergenceConditionedWidener",
        "VolatilityConditionedWidener",
        "NormalizedConformalWidener",
    ):
        assert never_ran not in ev.unverified_conditions
        assert never_ran not in ev.verified_conditions


def test_partial_condition_coverage_passes_the_gate(tmp_path):
    """Pins that THIS module does not judge coverage — FAB-2 does.

    `results_evidence` blocks only when *nothing* ran. A run where 1 of N conditions
    scored passes, and a paper may then tabulate all N. That is the 2026-07-31
    incident's own shape, one level up:

        planned 8 (stage-09/exp_plan.yaml)
          -> registered 5 (stage-12 stdout)
            -> scored 1 (NoWidening)
              -> tabulated 5+ in the paper

    Closing it needs the DECLARED set, which lives in the experiment plan, not
    in the execution record — so it is a separate check with a separate input,
    not something this module can infer. Match it on
    `implementation_spec.class_name`, which is exactly what the code registers
    (5/5 exact on this run); do NOT try to normalise the human-readable `name`
    field, which is unbridgeable — the same logical condition `NoWidening` maps
    to `NoWidening`, `FixedIntervalWidener` and `FixedWidthPredictor` across
    three runs of the same experiment.

    This module must keep passing such a run: its question is provenance.
    The coverage question is answered one layer up, by the FAB-2 block in
    `_paper_writing.py` (`tests/test_plan_condition_block.py`), which reads the
    DECLARED set from `stage-09/exp_plan.yaml` and refuses to draft when no
    proposed method scored. Keep the separation: if this test ever fails,
    coverage logic has leaked into the provenance module.
    """
    _run(
        tmp_path,
        "run-1.json",
        status="completed",
        metrics={"NoWidening/CRPS": 139.48, "NoWidening/Coverage90": 0.92},
        timed_out=False,
    )
    ev = collect_results_evidence(tmp_path)
    assert ev.has_real_metrics is True  # one condition really did score
    assert ev.verified_conditions == ("NoWidening",)
    assert ev.blocking_reasons() == []  # ...and nothing stops a 5-row table


def test_missing_returncode_is_unknown_not_success(tmp_path):
    _refine(
        tmp_path,
        "stage-13",
        [
            {
                "version_dir": "experiment_v1/",
                "sandbox": {"metrics": {"MethodA/CRPS": 3.0}},
            }
        ],
    )
    ev = collect_results_evidence(tmp_path)
    assert ev.executions[0].outcome == "unknown"
    assert ev.has_real_metrics is False


def test_unreadable_artifacts_are_skipped(tmp_path):
    runs = tmp_path / "stage-12" / "runs"
    runs.mkdir(parents=True)
    (runs / "run-1.json").write_text("{not json", encoding="utf-8")
    _run(tmp_path, "run-2.json", status="completed", metrics={"M/CRPS": 1.0})
    ev = collect_results_evidence(tmp_path)
    assert ev.has_real_metrics is True
    assert len(ev.executions) == 1


def test_results_json_is_not_treated_as_a_run(tmp_path):
    runs = tmp_path / "stage-12" / "runs"
    runs.mkdir(parents=True)
    (runs / "results.json").write_text(
        json.dumps({"metrics": {"M/CRPS": 1.0}}), encoding="utf-8"
    )
    ev = collect_results_evidence(tmp_path)
    assert ev.is_authoritative is False


def test_to_dict_is_json_serialisable(tmp_path):
    _run(tmp_path, "run-1.json", status="failed", metrics={}, timed_out=False)
    payload = collect_results_evidence(tmp_path).to_dict()
    json.dumps(payload)
    assert payload["has_real_metrics"] is False
    assert payload["executions_examined"] == 1


@pytest.mark.parametrize(
    "outcome,values,expected",
    [
        ("success", (1.0,), True),
        ("degraded", (1.0,), True),
        ("success", (), False),
        ("failed", (1.0,), False),
        ("simulated", (1.0,), False),
        ("unknown", (1.0,), False),
    ],
)
def test_is_evidence_matrix(outcome, values, expected):
    rec = ExecutionRecord(
        source="s", kind="run", outcome=outcome, detail="", metric_values=values
    )
    assert rec.is_evidence is expected


# ---------------------------------------------------------------------------
# The real artefact, when it is present
# ---------------------------------------------------------------------------

_REAL_RUN = (
    Path(__file__).resolve().parents[1] / "artifacts" / "rc-ws3-h2-real4-20260731"
)


@pytest.mark.skipif(
    not (_REAL_RUN / "stage-12" / "runs" / "run-1.json").is_file(),
    reason="fabricated reference run not present in this checkout",
)
def test_real_fabricated_run_is_blocked():
    ev = collect_results_evidence(_REAL_RUN)
    assert ev.is_authoritative is True
    assert ev.has_real_metrics is False
    assert ev.verified_conditions == ()
    assert "NoWidening" in ev.unverified_conditions
    assert ev.orphan_metric_count > 0
