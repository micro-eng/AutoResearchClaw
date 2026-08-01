# pyright: reportPrivateUsage=false
"""Regression tests for the two structural defects in stage_impls/_execution.py.

BUG-ADOPT-01 — stage 13 adopted a refinement only when a sandbox run produced an
IMPROVING metric.  One unrelated crash zeroed the metric for every version, so
``experiment_final`` silently reverted to the original stage-10 code.  The
``elif validation.ok and best_version == "experiment/"`` fallback that was meant
to catch this sat in the ``orelse`` of ``if validation.ok and mode in
("sandbox", "docker")`` while itself requiring ``validation.ok`` — unreachable in
the modes that run code.

BUG-RUN-01 — stage 12 returned DONE/proceed unconditionally, so a ``run-1.json``
recording ``status: failed`` with empty metrics was wrapped in a ``decision.json``
saying ``status: done, decision: proceed, error: null``.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from researchclaw.pipeline.stage_impls import _execution
from researchclaw.pipeline.stage_impls._execution import (
    _condition_coverage,
    _condition_scored,
    _declared_conditions,
    _describe_plan_gap,
    _plan_vs_scored,
    _registry_stdout,
    _decide_refinement_adoption,
    _describe_condition_gap,
    _describe_metric_key_miss,
    _last_sandbox_record,
    _refinement_progress_key,
    _summarise_run_outcomes,
)


class TestRefinementProgressKey:
    def test_more_metric_keys_outranks_fewer(self) -> None:
        emitted = _refinement_progress_key(
            1, {"sandbox": {"returncode": 1, "metrics": {"a": 1.0, "b": 2.0}}}
        )
        crashed_early = _refinement_progress_key(
            2, {"sandbox": {"returncode": 1, "metrics": {}}}
        )
        assert emitted > crashed_early

    def test_clean_exit_outranks_metric_count(self) -> None:
        clean = _refinement_progress_key(1, {"sandbox": {"returncode": 0, "metrics": {}}})
        crashed = _refinement_progress_key(
            2, {"sandbox": {"returncode": 1, "metrics": {f"m{i}": 1.0 for i in range(50)}}}
        )
        assert clean > crashed

    def test_post_repair_run_is_the_measurement(self) -> None:
        """version_dir holds the repaired files, so the repaired run is the truth."""
        key = _refinement_progress_key(
            1,
            {
                "sandbox": {"returncode": 1, "metrics": {"a": 1.0}},
                "sandbox_after_fix": {"returncode": 0, "metrics": {"a": 1.0, "b": 2.0}},
            },
        )
        assert key == (1, 0, 2, 1, 1)

    def test_more_conditions_outrank_more_metric_keys(self) -> None:
        """A 1-of-5-condition run must not win on key volume alone."""
        one_condition = _refinement_progress_key(
            2,
            {
                "sandbox": {"returncode": 1, "metrics": {f"A/m{i}": 1.0 for i in range(34)}},
                "condition_coverage": {"scored_count": 1},
            },
        )
        five_conditions = _refinement_progress_key(
            1,
            {
                "sandbox": {"returncode": 1, "metrics": {f"c{i}/m{j}": 1.0 for i in range(5) for j in range(6)}},
                "condition_coverage": {"scored_count": 5},
            },
        )
        assert five_conditions > one_condition

    def test_no_sandbox_falls_back_to_latest_iteration(self) -> None:
        first = _refinement_progress_key(1, {})
        third = _refinement_progress_key(3, {})
        assert third > first

    def test_key_width_is_pinned(self) -> None:
        """Tripwire: the adoption log line unpacks this tuple positionally into
        a fixed set of %d placeholders. Widening the key without updating that
        format string raises TypeError only on the fallback path — a branch
        that fires rarely and in production. Widen this assertion and the
        `logger.warning` in `_execute_iterative_refine` together."""
        assert len(_refinement_progress_key(1, {})) == 5

    def test_timeout_penalised(self) -> None:
        timed_out = _refinement_progress_key(
            1, {"sandbox": {"returncode": 1, "metrics": {"a": 1.0}, "timed_out": True}}
        )
        finished = _refinement_progress_key(
            1, {"sandbox": {"returncode": 1, "metrics": {"a": 1.0}, "timed_out": False}}
        )
        assert finished > timed_out


class TestConditionCoverage:
    """BUG-COND-01: one surviving condition out of five used to read as full
    coverage, which is how a control's number reached a paper under the
    proposed method's name."""

    STDOUT = (
        "METRIC_DEF: CRPS, Coverage90\n"
        "REGISTERED_CONDITIONS: NoWidening, ShuffledDivergenceWidener, "
        "DivergenceConditionedWidener\n"
        "Running condition: NoWidening\n"
        "condition=NoWidening seed=0 CRPS: 1.5\n"
    )

    def test_partial_coverage_is_detected(self) -> None:
        cov = _condition_coverage(self.STDOUT, {"NoWidening/CRPS": 1.5, "CRPS": 1.5})
        assert cov["registered_count"] == 3
        assert cov["scored"] == ["NoWidening"]
        assert cov["complete"] is False
        assert "DivergenceConditionedWidener" in cov["unscored"]

    def test_full_coverage_is_complete(self) -> None:
        cov = _condition_coverage(
            self.STDOUT,
            {
                "NoWidening/CRPS": 1.0,
                "ShuffledDivergenceWidener/CRPS": 1.0,
                "DivergenceConditionedWidener/CRPS": 1.0,
            },
        )
        assert cov["complete"] is True
        assert cov["unscored"] == []
        assert _describe_condition_gap(cov) is None

    def test_unknown_registry_is_not_reported_as_full_coverage(self) -> None:
        cov = _condition_coverage("no registry line here", {"A/CRPS": 1.0})
        assert cov["complete"] is None

    def test_the_proposed_method_can_be_queried_by_name(self) -> None:
        """The question stage 17 needs to ask, not just 'how many scored'."""
        cov = _condition_coverage(self.STDOUT, {"NoWidening/CRPS": 1.5})
        assert _condition_scored(cov, "NoWidening") is True
        assert _condition_scored(cov, "DivergenceConditionedWidener") is False

    def test_membership_is_exact_never_a_substring(self) -> None:
        """A proposed method must not read as scored because an ablation of it
        shares a prefix."""
        cov = _condition_coverage(self.STDOUT, {"NoWidening/CRPS": 1.5})
        assert _condition_scored(cov, "NoWideningPlus") is False
        assert _condition_scored(cov, "Widening") is False
        assert _condition_scored(cov, "  nowidening  ") is True

    def test_ran_and_scored_are_distinct(self) -> None:
        """A condition prints its label before it crashes; that is not a score."""
        cov = _condition_coverage(self.STDOUT, {})
        assert "NoWidening" in cov["ran"]
        assert cov["scored"] == []

    def test_duplicate_registry_entries_are_collapsed(self) -> None:
        cov = _condition_coverage(
            "REGISTERED_CONDITIONS: A, A, B\n", {"A/CRPS": 1.0}
        )
        assert cov["registered_count"] == 2

    def test_registry_is_the_codes_not_the_plans(self) -> None:
        """`complete: True` means "every condition the CODE registered scored",
        never "the planned experiment ran". A condition the plan declares and
        the code never registers is invisible here — by design, not accident.
        Checking against exp_plan.yaml is a separate check and must not be
        inferred from this one."""
        cov = _condition_coverage(
            "REGISTERED_CONDITIONS: OnlyOne\n", {"OnlyOne/CRPS": 1.0}
        )
        assert cov["complete"] is True
        assert cov["registered"] == ["OnlyOne"]
        # A planned-but-never-registered condition leaves no trace.
        assert "PlannedButNeverRegistered" not in cov["registered"]
        assert _condition_scored(cov, "PlannedButNeverRegistered") is False

    def test_gap_message_names_the_missing_conditions(self) -> None:
        cov = _condition_coverage(self.STDOUT, {"NoWidening/CRPS": 1.5})
        gap = _describe_condition_gap(cov)
        assert gap is not None
        assert "1/3" in gap
        assert "DivergenceConditionedWidener" in gap


class TestRegistryStdout:
    """The metrics and the stdout of one iteration live on DIFFERENT records
    when a runtime repair fired: `sandbox_after_fix` is written without a
    `stdout` key. Following the metrics convention for stdout reads "" on
    exactly the repaired iterations that matter."""

    def test_prefers_the_record_that_has_the_registry(self) -> None:
        rec = {
            "sandbox": {"stdout": "REGISTERED_CONDITIONS: A, B\n", "metrics": {}},
            "sandbox_after_fix": {"metrics": {"A/CRPS": 1.0}},
        }
        assert "REGISTERED_CONDITIONS" in _registry_stdout(rec)

    def test_falls_back_to_any_non_empty_stdout(self) -> None:
        rec = {"sandbox": {"stdout": ""}, "sandbox_after_fix": {"stdout": "condition=A\n"}}
        assert _registry_stdout(rec) == "condition=A\n"

    def test_absent_stdout_is_empty_not_an_error(self) -> None:
        assert _registry_stdout({"sandbox_after_fix": {"metrics": {"A/x": 1.0}}}) == ""

    def test_a_repaired_iteration_still_finds_the_registry(self) -> None:
        """Regression: the real run's `sandbox_after_fix` has stdout_len=0 while
        carrying all 34 metric keys. Coverage must not read the empty one and
        report vacuous completeness."""
        rec = {
            "sandbox": {"stdout": "REGISTERED_CONDITIONS: A, B, C\n", "metrics": {}},
            "sandbox_after_fix": {"stdout": "", "metrics": {"A/CRPS": 1.0}},
            "runtime_repaired": True,
        }
        cov = _condition_coverage(_registry_stdout(rec), rec["sandbox_after_fix"]["metrics"])
        assert cov["registered_count"] == 3
        assert cov["complete"] is False


class TestDeclaredConditions:
    PLAN = """
proposed_methods:
- implementation_spec:
    class_name: DivergenceConditionedWidener
  name: DivergenceConditionedWidening
ablations:
- implementation_spec:
    class_name: NoWidening
  name: NoWidening
baselines:
- Random Forest
- UnconditionalQuantileAggregation
"""

    def test_class_name_is_read_from_implementation_spec(self) -> None:
        """The plan's prose `name` and the code's `class_name` differ routinely
        and non-systematically (Widening/Widener; NoWidening/FixedIntervalWidener).
        Matching must use class_name — comparing prose names scores 0/8."""
        declared = _declared_conditions(self.PLAN)
        by_name = {d["name"]: d["class_name"] for d in declared}
        assert by_name["DivergenceConditionedWidening"] == "DivergenceConditionedWidener"

    def test_bare_string_baselines_are_not_dropped(self) -> None:
        """`baselines:` is a list of plain strings. Skipping non-dicts drops
        exactly the entries most at risk — the fabricated paper row was a
        declared, never-registered string baseline."""
        declared = _declared_conditions(self.PLAN)
        names = {d["name"] for d in declared}
        assert "UnconditionalQuantileAggregation" in names
        assert len(declared) == 4

    def test_malformed_plan_is_empty_not_an_exception(self) -> None:
        assert _declared_conditions("::: not yaml :::") == []
        assert _declared_conditions("") == []


class TestPlanVsScored:
    DECLARED = [
        {"section": "proposed_methods", "name": "DivW", "class_name": "DivergenceConditionedWidener"},
        {"section": "ablations", "name": "NoWidening", "class_name": "NoWidening"},
        {"section": "baselines", "name": "UnconditionalQuantileAggregation", "class_name": None},
    ]

    def test_never_registered_baseline_is_surfaced(self) -> None:
        """The fabrication hook: declared, never registered, never run — and a
        number for it appeared in the paper."""
        status = _plan_vs_scored(
            self.DECLARED,
            {
                "registered": ["NoWidening", "DivergenceConditionedWidener"],
                "scored": ["NoWidening"],
            },
        )
        assert "UnconditionalQuantileAggregation" in status["not_registered"]
        assert status["correspondence"] == "ok"

    def test_unscored_proposed_method_is_the_headline(self) -> None:
        status = _plan_vs_scored(
            self.DECLARED,
            {"registered": ["NoWidening", "DivergenceConditionedWidener"], "scored": ["NoWidening"]},
        )
        assert status["any_proposed_method_scored"] is False
        gap = _describe_plan_gap(status)
        assert gap is not None and "proposed method" in gap

    def test_scored_proposed_method_passes(self) -> None:
        status = _plan_vs_scored(
            self.DECLARED,
            {
                "registered": ["NoWidening", "DivergenceConditionedWidener", "UnconditionalQuantileAggregation"],
                "scored": ["NoWidening", "DivergenceConditionedWidener", "UnconditionalQuantileAggregation"],
            },
        )
        assert status["any_proposed_method_scored"] is True
        assert _describe_plan_gap(status) is None

    def test_name_mismatch_on_both_sides_is_unresolved_never_missing(self) -> None:
        """Fail closed: when the namespaces do not line up, an unmatched
        declaration is NOT evidence the condition was skipped. Reporting it as
        missing would block every run on a naming problem."""
        status = _plan_vs_scored(
            [{"section": "baselines", "name": "SomeBaseline", "class_name": None}],
            {"registered": ["TotallyDifferentName"], "scored": []},
        )
        assert status["correspondence"] == "unresolved"
        assert status["not_registered"] == []
        gap = _describe_plan_gap(status)
        assert gap is not None and "naming-correspondence failure" in gap

    def test_no_plan_yields_no_finding(self) -> None:
        status = _plan_vs_scored([], {"registered": ["A"], "scored": ["A"]})
        assert status["correspondence"] == "no_plan"
        assert _describe_plan_gap(status) is None


class TestAdoptionDecision:
    def test_metric_improvement_is_unchanged(self) -> None:
        assert _decide_refinement_adoption(
            best_version="experiment_v2/",
            best_metric=0.4,
            progress_version="experiment_v1/",
            progress_key=(0, 34, 1, 1),
        ) == ("experiment_v2/", "metric_improvement")

    def test_real_metric_is_never_overridden_by_progress(self) -> None:
        """A baseline metric no refinement beat is a genuine comparison."""
        assert _decide_refinement_adoption(
            best_version="experiment/",
            best_metric=0.4,
            progress_version="experiment_v1/",
            progress_key=(0, 34, 1, 1),
        ) == ("experiment/", "original_retained_no_metric_improvement")

    def test_no_metric_anywhere_adopts_best_progress(self) -> None:
        """The defect: every version crashed, so nothing was adopted at all."""
        assert _decide_refinement_adoption(
            best_version="experiment/",
            best_metric=None,
            progress_version="experiment_v1/",
            progress_key=(0, 34, 1, 1),
        ) == ("experiment_v1/", "progress_fallback_no_metric_anywhere")

    def test_no_valid_candidate_keeps_original_but_says_so(self) -> None:
        assert _decide_refinement_adoption(
            best_version="experiment/",
            best_metric=None,
            progress_version=None,
            progress_key=None,
        ) == ("experiment/", "original_retained_no_valid_candidate")


class TestNoUnreachableValidationBranch:
    def test_no_elif_requires_validation_ok_under_a_validation_ok_parent(self) -> None:
        """AST, not indentation — at this nesting depth the eye is unreliable."""
        tree = ast.parse(Path(_execution.__file__).read_text(encoding="utf-8"))
        offenders: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            if "validation.ok" not in ast.unparse(node.test):
                continue
            for alt in node.orelse:
                if isinstance(alt, ast.If) and "validation.ok" in ast.unparse(alt.test):
                    offenders.append((alt.lineno, ast.unparse(alt.test)))
        assert offenders == []


class TestMetricKeyMissDiagnosis:
    """BUG-METRIC-01: "emitted nothing" and "emitted, none matched" are
    different failures and used to be reported identically."""

    def test_no_metrics_is_not_a_key_mismatch(self) -> None:
        assert _describe_metric_key_miss("primary_metric", {}) is None

    def test_names_the_configured_key_and_the_emitted_ones(self) -> None:
        msg = _describe_metric_key_miss(
            "primary_metric",
            {"NoWidening/0/CRPS": 1.0, "NoWidening/CRPS": 1.0, "Coverage90": 0.9},
        )
        assert msg is not None
        assert "primary_metric" in msg
        assert "CRPS" in msg and "Coverage90" in msg

    def test_condition_prefixes_are_collapsed(self) -> None:
        msg = _describe_metric_key_miss(
            "primary_metric", {f"cond{i}/CRPS": 1.0 for i in range(5)}
        )
        assert msg is not None
        assert msg.count("CRPS") == 1

    def test_does_not_nominate_a_replacement_metric(self) -> None:
        """Picking between CRPS (minimize) and Coverage90 (maximize) would be
        authoring the experiment; a wrong pick optimises the wrong objective."""
        msg = _describe_metric_key_miss("primary_metric", {"CRPS": 1.0, "Coverage90": 0.9})
        assert msg is not None
        for word in ("use ", "using ", "switch to", "falling back", "substitut"):
            assert word not in msg.lower()


class TestLastSandboxRecord:
    def test_prefers_the_post_repair_run(self) -> None:
        rec = {"sandbox": {"returncode": 1}, "sandbox_after_fix": {"returncode": 0}}
        assert _last_sandbox_record(rec)["returncode"] == 0

    def test_falls_back_to_the_first_run(self) -> None:
        assert _last_sandbox_record({"sandbox": {"returncode": 1}})["returncode"] == 1

    def test_absent_sandbox_is_an_empty_mapping(self) -> None:
        assert _last_sandbox_record({}) == {}


class TestStageTwelveRunOutcome:
    def test_failed_run_with_no_metrics_is_degraded(self, tmp_path: Path) -> None:
        (tmp_path / "run-1.json").write_text(
            json.dumps({"status": "failed", "metrics": {}}), encoding="utf-8"
        )
        outcome = _summarise_run_outcomes(tmp_path)
        assert outcome["degraded"] is True
        assert outcome["failed"] == 1
        assert outcome["with_metrics"] == 0
        assert outcome["reason"]

    def test_failed_run_that_emitted_metrics_is_still_degraded(self, tmp_path: Path) -> None:
        """A crash after emitting numbers is still a crash."""
        (tmp_path / "run-1.json").write_text(
            json.dumps({"status": "failed", "metrics": {"a": 1.0}}), encoding="utf-8"
        )
        assert _summarise_run_outcomes(tmp_path)["degraded"] is True

    def test_completed_run_proceeds_cleanly(self, tmp_path: Path) -> None:
        (tmp_path / "run-1.json").write_text(
            json.dumps({"status": "completed", "metrics": {"a": 1.0}}), encoding="utf-8"
        )
        outcome = _summarise_run_outcomes(tmp_path)
        assert outcome["degraded"] is False
        assert outcome["reason"] is None

    def test_simulated_runs_are_not_degraded(self, tmp_path: Path) -> None:
        (tmp_path / "run-1.json").write_text(
            json.dumps({"status": "simulated", "key_metrics": {"a": 1.0}}), encoding="utf-8"
        )
        assert _summarise_run_outcomes(tmp_path)["degraded"] is False

    def test_timed_out_partial_run_is_degraded(self, tmp_path: Path) -> None:
        (tmp_path / "run-1.json").write_text(
            json.dumps({"status": "partial", "metrics": {"a": 1.0}}), encoding="utf-8"
        )
        assert _summarise_run_outcomes(tmp_path)["partial"] == 1
        assert _summarise_run_outcomes(tmp_path)["degraded"] is True

    def test_results_json_is_not_counted_as_a_run(self, tmp_path: Path) -> None:
        (tmp_path / "run-1.json").write_text(
            json.dumps({"status": "completed", "metrics": {"a": 1.0}}), encoding="utf-8"
        )
        (tmp_path / "results.json").write_text(
            json.dumps({"source": "stdout_parsed", "metrics": {}}), encoding="utf-8"
        )
        assert _summarise_run_outcomes(tmp_path)["runs"] == 1

    def test_missing_runs_dir_is_degraded_not_clean(self, tmp_path: Path) -> None:
        outcome = _summarise_run_outcomes(tmp_path / "absent")
        assert outcome["runs"] == 0
        assert outcome["degraded"] is True
