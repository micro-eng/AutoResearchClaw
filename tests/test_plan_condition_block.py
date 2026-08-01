"""FAB-2: PAPER_DRAFT must block when the paper's SUBJECT never ran.

FAB-1 asks "did ANY process emit a number".  That trigger is too narrow: a run
where 1 of N conditions scored passes it, and the paper may then tabulate all N.
That is the 2026-07-31 incident's own shape — 8 conditions declared in
``stage-09/exp_plan.yaml``, 5 registered, 1 scored, 5+ tabulated, with the
fabricated baseline row (``UnconditionalQuantileAggregation``) being a condition
the plan declared and the code never registered.

The block is FAIL-CLOSED: it fires only on *proven* absence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from researchclaw.pipeline.stage_impls._paper_writing import (
    _collect_plan_condition_status,
)


def _blocks(status: dict | None) -> bool:
    """The exact predicate stage 17 applies."""
    if status is None:
        return False
    return bool(
        status.get("correspondence") == "ok"
        and status.get("proposed_methods")
        and not status.get("any_proposed_method_scored")
    )


def _plan(tmp_path: Path, proposed: list[tuple[str, str]], ablations: list[tuple[str, str]]) -> None:
    d = tmp_path / "stage-09"
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "proposed_methods": [
            {"name": n, "implementation_spec": {"class_name": c}} for n, c in proposed
        ],
        "ablations": [
            {"name": n, "implementation_spec": {"class_name": c}} for n, c in ablations
        ],
        "baselines": ["UnconditionalQuantileAggregation"],
    }
    (d / "exp_plan.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")


def _refine(tmp_path: Path, stage: str, registered: list[str], metrics: dict) -> None:
    d = tmp_path / stage
    d.mkdir(parents=True, exist_ok=True)
    (d / "refinement_log.json").write_text(
        json.dumps({
            "iterations": [{
                "version_dir": "experiment_v1/",
                "sandbox": {
                    "returncode": 0,
                    "timed_out": False,
                    "metrics": metrics,
                    "stdout": "REGISTERED_CONDITIONS: " + ", ".join(registered),
                },
            }],
        }),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Fires on proven absence
# ---------------------------------------------------------------------------


def test_blocks_when_only_the_ablation_scored(tmp_path):
    """The residual FAB-1 leaves open: 1 of N scored, and it isn't the subject."""
    _plan(
        tmp_path,
        proposed=[("DivergenceConditionedWidening", "DivergenceConditionedWidener")],
        ablations=[("NoWidening", "NoWidening")],
    )
    _refine(
        tmp_path,
        "stage-13",
        registered=["NoWidening", "DivergenceConditionedWidener"],
        metrics={"NoWidening/CRPS": 139.48},
    )
    status = _collect_plan_condition_status(tmp_path)
    assert status["correspondence"] == "ok"
    assert status["any_proposed_method_scored"] is False
    assert _blocks(status) is True
    # A BARE-STRING baseline entry must still be classified. `baselines:` is a
    # list of plain strings, not mappings, and a dict-only parse silently drops
    # them — dropping exactly the entries most at risk. On the real run this is
    # the fabricated baseline row itself. Asserted here rather than only in the
    # reference-run test below, which skips whenever `artifacts/` is absent
    # (it is untracked, so it is absent in every clean checkout and in CI).
    assert "UnconditionalQuantileAggregation" in status["not_registered"]


# ---------------------------------------------------------------------------
# Fail-open: never block on UNKNOWN
# ---------------------------------------------------------------------------


def test_no_plan_never_blocks(tmp_path):
    """Absence of a plan is not evidence a condition was skipped."""
    _refine(tmp_path, "stage-13", registered=["NoWidening"], metrics={"NoWidening/CRPS": 1.0})
    assert _collect_plan_condition_status(tmp_path) is None
    assert _blocks(None) is False


def test_name_mismatch_is_unresolved_and_never_blocks(tmp_path):
    """A naming-correspondence failure must not be reported as a scientific one.

    Blocking here would halt every run with a name mismatch — the alarm fatigue
    that makes a guard get switched off.
    """
    _plan(
        tmp_path,
        proposed=[("DivergenceConditionedWidening", "ZzzDivergence")],
        ablations=[("NoWidening", "ZzzNoWidening")],
    )
    _refine(
        tmp_path,
        "stage-13",
        registered=["TotallyDifferentName", "AnotherOne"],
        metrics={"TotallyDifferentName/CRPS": 1.0},
    )
    status = _collect_plan_condition_status(tmp_path)
    assert status["correspondence"] == "unresolved"
    assert _blocks(status) is False


def test_scored_proposed_method_does_not_block(tmp_path):
    _plan(
        tmp_path,
        proposed=[("DivergenceConditionedWidening", "DivergenceConditionedWidener")],
        ablations=[("NoWidening", "NoWidening")],
    )
    _refine(
        tmp_path,
        "stage-13",
        registered=["NoWidening", "DivergenceConditionedWidener"],
        metrics={"DivergenceConditionedWidener/CRPS": 11.0, "NoWidening/CRPS": 13.0},
    )
    status = _collect_plan_condition_status(tmp_path)
    assert status["any_proposed_method_scored"] is True
    assert _blocks(status) is False


# ---------------------------------------------------------------------------
# The rollback-archive trap
# ---------------------------------------------------------------------------


def test_reads_the_authoritative_refinement_log_not_the_lexicographic_last(tmp_path):
    """On rollback the COMPLETED cycle is archived to `stage-13_vN` and the new
    cycle takes the bare name, so `stage-13` is newest.

    `sorted(glob("stage-13*"))[-1]` returns `stage-13_v2` — lexicographically
    last, chronologically middle.

    NOTE this fixture is CONSTRUCTED, not a replay. On the real
    `rc-ws3-h2-real4-20260731` the block decision is *invariant* across all
    three cycles (`correspondence: ok`, `any_proposed_method_scored: False` in
    each); only the reported verdict for `UnconditionalQuantileAggregation`
    varies — `not_registered` in the authoritative cycle vs
    `registered_not_scored` in `stage-13_v2`, which registered a 6th condition.
    So on that run the log choice governs the honesty of the message, not the
    correctness of the block.

    This test pins the stronger property anyway: a run *can* be built where the
    archived cycle scored the proposed method and the current one did not, and
    there the wrong log fails to block a paper whose subject never ran in the
    cycle it is written from. Reading the authoritative log is correct in both
    regimes; a union is correct in neither.
    """
    _plan(
        tmp_path,
        proposed=[("DivergenceConditionedWidening", "DivergenceConditionedWidener")],
        ablations=[("NoWidening", "NoWidening")],
    )
    # current cycle (bare name, newest): proposed method did NOT score
    _refine(
        tmp_path,
        "stage-13",
        registered=["NoWidening", "DivergenceConditionedWidener"],
        metrics={"NoWidening/CRPS": 139.48},
    )
    # archived cycles: one of them DID score the proposed method
    _refine(
        tmp_path,
        "stage-13_v2",
        registered=["NoWidening", "DivergenceConditionedWidener"],
        metrics={"DivergenceConditionedWidener/CRPS": 11.0},
    )
    _refine(
        tmp_path,
        "stage-13_v1",
        registered=["NoWidening"],
        metrics={},
    )
    status = _collect_plan_condition_status(tmp_path)
    # Must reflect the CURRENT cycle only — a union would fail open here.
    assert status["any_proposed_method_scored"] is False
    assert _blocks(status) is True


# ---------------------------------------------------------------------------
# The real artefact
# ---------------------------------------------------------------------------

_REAL_RUN = (
    Path(__file__).resolve().parents[1] / "artifacts" / "rc-ws3-h2-real4-20260731"
)


@pytest.mark.skipif(
    not (_REAL_RUN / "stage-09" / "exp_plan.yaml").is_file(),
    reason="reference run not present in this checkout",
)
def test_real_run_blocks_and_names_the_fabricated_baseline():
    status = _collect_plan_condition_status(_REAL_RUN)
    assert status["correspondence"] == "ok"
    assert status["declared_count"] == 8
    assert status["any_proposed_method_scored"] is False
    assert _blocks(status) is True
    # The paper's fabricated baseline row was a condition the plan declared and
    # the code never registered.
    assert "UnconditionalQuantileAggregation" in status["not_registered"]


def test_scored_without_registry_line_is_unresolved_not_proven_absence():
    """Metric-key prefixes alone must count as the code namespace.

    When experiments print ``condition=dense/...`` metrics but never emit a
    ``REGISTERED_CONDITIONS:`` line, ``registered`` is empty.  FAB-2 must then
    treat prose plan names vs ``dense``/``sparse_*`` scored prefixes as a
    naming mismatch (correspondence=unresolved), not as proven absence
    (correspondence=ok + any_proposed_method_scored=False) which hard-blocks
    PAPER_DRAFT — the failure mode of rc-20260801-082705-3677fb.
    """
    from researchclaw.pipeline.stage_impls._execution import (
        _condition_coverage,
        _declared_conditions,
        _plan_vs_scored,
    )

    plan = """
proposed_methods:
  - Sparse-max attention via Gumbel-Softmax
  - Dynamic blockwise routing
baselines:
  - Full Fine-Tuning
"""
    metrics = {
        "dense/primary_metric": 245.0,
        "sparse_10/primary_metric": 256.0,
        "sparse_25/primary_metric": 256.0,
    }
    stdout = (
        "condition=dense seed=0 primary_metric: 245.0\n"
        "condition=sparse_10 seed=0 primary_metric: 256.0\n"
    )
    coverage = _condition_coverage(stdout, metrics)
    assert coverage["scored"]  # prefixes present
    assert coverage["registered"] == []  # no REGISTERED_CONDITIONS line
    status = _plan_vs_scored(_declared_conditions(plan), coverage)
    assert status["correspondence"] == "unresolved"
    # Must NOT look like proven absence of the proposed method
    assert not (
        status["correspondence"] == "ok" and not status["any_proposed_method_scored"]
    )
