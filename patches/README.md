# AutoResearchClaw patches — 2026-07-31 ARCLAW burn

Six fixes for real defects found while driving WS3 hypothesis H2 to a paper on real NEM data.
**All are UNCOMMITTED** and exist only as these files plus dirty working trees. They are mirrored
to **both** hosts (prime-serve `~/code/AutoResearchClaw/patches/`, m5-infer1
`~/arc-deploy/AutoResearchClaw/patches/`) so no single machine is a point of failure.

Reapply with `git apply <file>` from the repo root. Base: `cursor/ollama-openfang-setup-dd8b`
@ `ba6352f`.

| Patch | Fixes | Verified |
|---|---|---|
| `experiment_diagnosis_dataset_guidance_2026-07-31.patch` | `experiment_diagnosis.py` hardcoded `dataset_unavailable` advice telling the repair LLM to *"use torchvision.datasets with root='/opt/datasets'"*. Turned every repair cycle into a `ModuleNotFoundError` loop. Now domain-neutral. | 36 lines; applied and live on prime-serve |
| `003-pkg-hint-respect-custom-prompts.patch` | `_code_generation.py:105-131` package hint was a **Python f-string, not an overridable prompt block** — on M5 hardware it promised torch and steered to an MPS training loop. Replaced with an overridable `pkg_hint_sandbox` block. | branch flip proven at unit level |
| `004-regen-prompt-keeps-dataset-guidance.patch` | Alignment-failure **regeneration** prompt drops `extra_guidance` (dataset path, columns, filters) while keeping `pkg_hint` — which then says *"see the dataset guidance block"* that is no longer present. Made both regen attempts near-worthless. **CUMULATIVE — contains 003's hunk too.** | `py_compile` + imports clean |
| `005-code-agent-prioritise-plan-before-truncate.patch` | `code_agent.py:543` `exp_plan[:4000]` on **alphabetically-sorted YAML**: `ablations` sorts first, `proposed_methods` second-to-last, so any plan >~4 KB **keeps the ablations and drops the declaration of the method they ablate**. Adds `_prioritise_plan()` hoisting method sections before truncation. | verified offline on the real 7,533-char plan: `proposed_methods` survives (3,771/4,000 chars); also rescues `UnconditionalQuantileAggregator`'s spec |
| `007-execution-adoption-and-honest-stage12.patch` | **Five structural defects in `stage_impls/_execution.py`.** (1) **Score-gated adoption discarded correct fixes.** Stage 13 adopted a refinement only via `metric_val is not None and _is_better(...)`; the `elif validation.ok and best_version == "experiment/"` fallback sat in the `orelse` of `if validation.ok and mode in ("sandbox","docker")` while itself requiring `validation.ok` — **unreachable in exactly the modes that run code**. One unrelated crash zeroed the metric for every version, so `experiment_final` silently reverted to the original stage-10 code with no log line. Adds `_refinement_progress_key()` (ranks a version by `exited_cleanly, conditions_scored, metric_keys, not_timed_out, iteration`) and `_decide_refinement_adoption()`, which adopts the best-progress version **only when no version produced a metric anywhere** — a real metric is never overridden — and **logs the adoption reason in all four outcomes** (`refinement_log.adoption_reason`). Also stops the loop re-refining the original while metric-blind: iterations build on the best-progress candidate (monotone, so a regression is not fed forward), recorded as `refined_from`. (2) **Stage 12 swallowed failure.** Adds `_summarise_run_outcomes()` over `run-*.json` terminal statuses, writes `stage-12/run_outcome.json`, escalates `proceed → degraded` with a populated `error`. Complements `006`'s metric-evidence check, which stays silent when a run crashes *after* emitting numbers. Deliberately still `DONE`: stage 12 is not in `NONCRITICAL_STAGES`, so `FAILED` would `break` the runner and destroy the stage-13/14 repair path. (3) **`metric_key` mismatch was indistinguishable from "no results".** `metric_key` was `primary_metric` while the code emitted `CRPS`/`Coverage90`/`Width90`/`PinballLoss`/`success_rate`/`MedianCRPS` — **all five matching branches of `_find_metric` miss, so no run of that experiment could ever have scored, clean or crashed** — the *upstream cause* of (1) having no score. Adds `_describe_metric_key_miss()`. It deliberately **does not nominate a substitute metric**: choosing between `CRPS` (minimize) and `Coverage90` (maximize) would be authoring the experiment. (4) **One surviving condition read as full coverage.** R7-3's hint tested `"condition=" in stdout`, so 1-of-5 conditions looked complete and nothing recorded *which* scored — and `_refinement_progress_key` ranked on metric-key volume, letting a 1-condition fragment outrank a complete run. Adds `_condition_coverage()` / `_condition_scored()` / `_describe_condition_gap()`, makes conditions outrank key count in the ranking, and hoists the adopted version's coverage to `refinement_log.condition_coverage`. Requested by `h2-pipeline` as the enabling data for stage 17's anti-fabrication guard, which currently fires only on *zero* metrics — one surviving ablation disarms it. Membership is **exact, never substring**, so an ablation sharing a prefix cannot report its proposed method as scored. (5) **Declared-vs-scored (BUG-COND-02).** Registered-vs-scored cannot see a condition the code never registered: run 1's proposed method was never defined at all, and run 4 declared three BASELINES that were never registered — one of which, `UnconditionalQuantileAggregation`, is the paper's fabricated row. Adds `_declared_conditions()` / `_plan_vs_scored()` / `_describe_plan_gap()` reading `exp_plan.yaml`, hoisted to `refinement_log.plan_condition_status` with `any_proposed_method_scored` as the guard's question. **Matching is exact on `implementation_spec.class_name`, not on the plan's prose `name`** — the plan declares both, and they differ non-systematically (`DivergenceConditionedWidening` vs `DivergenceConditionedWidener`; `NoWidening` vs `FixedIntervalWidener`), so comparing prose names scores 0/8 and no fuzzy matching is needed. Bare-string `baselines:` entries are parsed, not skipped. Fails closed: an unmatched declaration is `unresolved`, never `missing`, whenever any registered condition is itself unaccounted for. | **executed** against the real `artifacts/rc-ws3-h2-real4-20260731`. BEFORE is what the live run wrote (`best_version: "experiment/"`, `best_metric: null`, no adoption line; `decision.json` `status: done, decision: proceed, error: null` over a `run-1.json` reading `status: failed, metrics: {}`). AFTER, executing the shipped functions on those same artefacts: iter1 `(0,1,34,1,1)` beats iter2 `(0,0,0,1,2)` → adopts `experiment_v1/` (`progress_fallback_no_metric_anywhere`), and `experiment_v1/evaluation.py` **has `def compute_crps` where the shipped `experiment_final/` does not**; stage 12 → `decision: degraded`, `error: "1/1 experiment run(s) did not complete (failed=1, partial=0); 0/1 emitted metrics."`; all five `_find_metric` branches miss on the real 34-key dict while the same dict yields 5 matches for `CRPS`; condition coverage → 5 registered / 1 scored, with `_condition_scored(adopted, "DivergenceConditionedWidener")` **False** while the control `NoWidening` is **True** — the fact run 4's headline comparison lacked. Unreachable-branch absence re-checked by **AST, not indentation** (a standing test). 35 tests in `tests/test_rc_execution_adoption.py`. Plan-vs-scored replayed on BOTH runs: 8/8 declared conditions classified with **exact** matching and `correspondence: ok` — `UnconditionalQuantileAggregation` (the paper's fabricated baseline row) is caught as `not_registered` on run 4, and run 1's never-defined proposed method on run 1. 47 tests in `tests/test_rc_execution_adoption.py`. **All totals from a FROZEN snapshot** (`git archive HEAD` + `006` + `007`, no concurrent writer) — working-tree totals proved unreliable while several agents were editing the same tree: full suite **2863 passed / 50 skipped / 1 pre-existing unrelated failure**; `006`→`007` apply clean, **all seven touched files byte-identical** to the working tree. |
| `006-fab1-verifier-reconciles-against-execution-artefacts.patch` | **The fabrication chain.** Stage 17's guard accepted `>=3 x condition[=:]` in raw stdout as proof of real metrics (a crashed run's own progress lines); `_analysis.py` stamped `status: "completed"` on a refinement sandbox that exited `returncode: 1`; stage 20 then read that laundered summary and emitted `fabrication_suspected: false, has_real_data: true, verdict: Accept, 8/10` over an experiment recording `status: failed, metrics: {}`. Adds `researchclaw/pipeline/results_evidence.py` — reconciliation against `runs/*.json` and refinement `returncode`s only, never against derived summaries, paper text, or log strings — and wires it into stages 17, 20 and 14. Fabrication blocks bypass `graceful_degradation`. | **executed** against the real `artifacts/rc-ws3-h2-real4-20260731`: BEFORE (pristine `HEAD`) reproduces the shipped `fabrication_flags.json` exactly (35 "verified" values, `707213.5867`, `Accept`); AFTER blocks at stage 17 **and** stage 20 (`reject`, `1.0`, `FAILED`) even with a stub LLM insisting `8/Accept`. Positive control (same numbers, clean exits) still passes — no false positive. 32 new tests (FAB-1 + FAB-2); frozen-snapshot full suite 2870 pass / 1 pre-existing unrelated failure |

## Apply order

`004` supersedes `003` (cumulative). On a clean tree the minimal complete set is:

```sh
git apply patches/experiment_diagnosis_dataset_guidance_2026-07-31.patch
git apply patches/004-regen-prompt-keeps-dataset-guidance.patch
git apply patches/005-code-agent-prioritise-plan-before-truncate.patch
git apply patches/006-fab1-verifier-reconciles-against-execution-artefacts.patch
git apply patches/007-execution-adoption-and-honest-stage12.patch
```

Both are independent of `003`/`004`/`005` (disjoint files) and apply cleanly to a pristine `HEAD`
tree in any order relative to them.

### `006` and `007` are ATOMIC — apply BOTH or NEITHER

They are textually disjoint (no file is touched by both), so `git apply` never conflicts and either
order works. But they are **mutually dependent at runtime**, and applying one alone leaves a broken
tree:

| Applied alone | Breaks | Where |
|---|---|---|
| `007` only | `_execution.py`'s stage-12 block imports `researchclaw/pipeline/results_evidence.py`, which only `006` creates | stage 12 |
| `006` only | `_paper_writing.py`'s `_collect_plan_condition_status()` imports `_declared_conditions` / `_plan_vs_scored` / `_describe_plan_gap` from `_execution.py`, which only `007` adds | stage 17 |

**The `006`-only failure is deferred and therefore the more dangerous of the two.** The import sits
*inside* `_paper_writing._collect_plan_condition_status()` (function-local by design — it breaks a
module-level cycle), so `import researchclaw.pipeline.stage_impls._paper_writing` succeeds and the
tree looks healthy. Verified by **calling** the function on a pristine `HEAD` + `006` tree:

```
1. module import : OK  <-- tree looks healthy
2. signature     : (run_dir: 'Path') -> 'dict[str, Any] | None'
3. CALL RAISED   : ImportError: cannot import name '_condition_coverage' from ...._execution
                   -> fails LOUD and SAFE
```

A smoke test that only imports modules will not catch this — the call is the test.

> **This behaviour is only correct as of `006` ≥ 1693 lines.** An earlier `006` wrapped that import
> in `except ImportError: return None` — and `None` is the same value that means *"no plan, nothing
> to check"*, so a partially-applied tree made the anti-fabrication guard **silently disable
> itself**: no exception, no failed stage, paper drafted, one WARNING line as the only trace. If you
> are reading an older `006`, check for that handler before trusting a green run. The general rule
> it cost us: **a guard that cannot run must not return the same value as a guard that ran and found
> nothing.**

Verified in a frozen snapshot off pristine `HEAD`: `006` then `007` apply clean and reproduce the
working tree byte-for-byte across all eight touched files.

### File ownership across `006` / `007`

`_execution.py` was briefly co-edited. It now belongs entirely to `007`; `006` covers
`results_evidence.py`, `_analysis.py`, `_paper_writing.py`, `_review_publish.py`,
`tests/test_results_evidence.py` and `tests/test_plan_condition_block.py`. The dependency runs both
ways by design rather than by accident: `006` imports `007`'s plan-matching functions instead of
copying them, so the guard's verdict cannot drift from the field it reads. The two stage-12 checks
are likewise complementary, not duplicates: `006`'s fires on *no finite metric anywhere*, `007`'s on
*any run whose terminal status is `failed`/`partial`* — including the case `006` cannot see, a crash
that emitted numbers first.

## Why these are not committed

Founder standing rule: **commit only when asked.** The question has been put and is awaiting a
decision. Until then these files are the durable copy — a fix living only in a dirty working tree
exists on one host and dies at the next checkout.

## Not fixed — the remaining exposure

**Confabulation into unconstrained schema fields.** Stage 9 invented `datasets: "UCI Adult"` and
hardware `"NVIDIA RTX 6000 Ada"` (the host is an Apple M5 Max). Neither came from a prompt block
or a domain profile — the model simply filled in fields nobody pinned. **No prompt override
defends against this**, and none of these patches address it. Every plan/spec artefact must be
inspected for invented values, especially anything a paper might later cite as method, hardware,
or data provenance.

Full context: `../BURN_BRIEF.md`, `../BURN_LOG.md`, and the FY27 RDTI record at
`Project Hive 2.0/rdti/FY27_WS4_ws3_h2_two_ensemble_2026-07-31.md`.
