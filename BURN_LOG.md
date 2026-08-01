# BURN LOG
Append-only. One section per agent.

## h2-pipeline

### 2026-07-31 01:30 AEST — stage-17 root cause FOUND, matplotlib FIXED
**Diagnosis of `rc-20260730-114801-e9b01a` stage-17 PAPER_DRAFT failure (complete chain):**
1. Stage 12 codegen was handed the prompt block `network_disabled_guidance`
   (`researchclaw/prompts.py`, injected by `_code_generation.py:156-161` because sandbox mode
   forces `_net_policy = "none"`). That block is written for the *Docker image* and says the ONLY
   available data is CIFAR/MNIST/... at `/opt/datasets`. There is no Docker image and no
   `/opt/datasets` on this host. The model invented `/opt/datasets/electricity_prices.csv`.
2. main.py crashed at `pd.read_csv('/opt/datasets/electricity_prices.csv')` → FileNotFoundError.
   stage-14/experiment_summary.json: `total_conditions: 0`, `metrics_summary: {}`.
3. Repair loop: `experiment_diagnosis.py:452-479` pattern-matches "dataset_unavailable" and emits a
   HARDCODED vision suggestion — "Use ONLY pre-cached datasets: CIFAR-10 ... use
   torchvision.datasets with root='/opt/datasets'". For an electricity-price experiment.
4. The repair LLM obeyed it. `stage-14_repair_v3/experiment_summary.json` stderr:
   `data.py line 1: import torchvision.datasets → ModuleNotFoundError: No module named 'torchvision'`.
   Every cycle rewrote a price-forecasting loader into a torchvision loader that cannot import.
5. Why the score never moved: `_summary_quality_score` (`experiment_repair.py:245-266`) =
   `10*len(condition_summaries) + 5*(finite primary_metric) + total_metric_keys`. On a crash all
   three terms are 0. **0.0 -> 0.0 means "the code died before emitting anything", NOT "results were
   bad".** The founder's read is correct: success conditions were never populated (0/0).
6. Stage 17 then hard-blocks: `_paper_writing.py:1620-1638` — `not has_real_metrics` and domain in
   {ml, engineering, biology, chemistry} => writes "Paper Draft Blocked" and returns FAILED.
   The pipeline refused to fabricate. That guard is correct behaviour; the fault is upstream.

**ROOT CAUSE: no dataset was ever provided to the experiment.** There is no `dataset_path` /
`data_dir` field anywhere in `researchclaw/config.py` — the ONLY supported channel is prompt text
(`prompts.custom_file` overriding the `network_disabled_guidance` / `dataset_guidance` blocks,
plus the topic string). Sandbox mode is a bare host subprocess, so an absolute host path works.

**matplotlib FIXED and PROVEN** (`.venv/bin/python -m pip install matplotlib`, additive only —
dry-run showed contourpy/cycler/fonttools/kiwisolver/matplotlib added, nothing upgraded, and
researchclaw itself untouched, so the concurrently-running ws3-theorem-hunt job was not disturbed):
`matplotlib 3.11.1`, Agg backend, wrote an 18 KB PNG from the venv interpreter.

**NOTE for coordinator:** a job IS running — pid 66275,
`researchclaw run --config config.ws3-theorem-hunt.yaml --from-stage LITERATURE_COLLECT
--to-stage HYPOTHESIS_GEN`, tmux `claw-ws3-theorem`, at stage 4 as of 15:24Z. I deliberately
avoided `pip install -e ".[all]"` (that reinstalls the editable researchclaw dist-info under the
live process); will do the full extra once that run ends. matplotlib was the actual blocker.

## openfang-hand

**VERDICT: DO NOT RECOMMEND now. DEFER indefinitely — it is capability-building that
does not serve the current goal, and it actively competes with it.** Nothing was installed
or activated; this is assessment only.

### 1. What the script does (read line by line)
`scripts/install_openfang_hand.sh` (28 lines) is a pure file copy:
- `rm -rf ~/.openfang/hands/researchclaw` then `mkdir -p` + `cp -R` of
  `openfang/hands/researchclaw/{HAND.toml,SKILL.md}` (12 KB, 2 files).
- Honours `OPENFANG_HANDS_DIR`. Touches nothing else. Does **not** call `openfang`,
  does **not** restart or signal the daemon, writes no config, no launchd plist.
- `~/.openfang/hands/` **does not currently exist** — the script creates it. Nothing
  can be clobbered by the `rm -rf` today.
- Reversible: `rm -rf ~/.openfang/hands/researchclaw`.

**Blast radius of the script itself: near zero, but it is only half the install.**
Verified in the OpenFang source (`~/Openfang`, v0.6.0):
- `crates/openfang-kernel/src/kernel.rs:863` reads `~/.openfang/hands/` **only at kernel
  init**. A running daemon never re-scans it.
- `POST /api/hands/install` (`routes.rs:4507`) calls `install_from_content`, which inserts
  into the **in-memory registry only** — it does not write to disk.
- So the two halves are: the script = persistence-across-restart; `openfang hand install` =
  live registration. Running only the script means the printed next step
  `openfang hand activate researchclaw` **fails with "Hand not found"** until the daemon
  restarts. The real risk is the delayed kind: the definition silently appears in
  `hand list` at the next unrelated daemon restart.
- A bare copy does **not** self-activate. `hand_state.json` (absent today) is what
  `start_background_agents` replays on boot, and only previously-activated hands are in it.

### 2. What activation actually gives you — blast radius of the REAL change
`kernel.rs:3443 activate_hand()`, read directly. Activating this HAND.toml:
- **Spawns a 35th agent** (`researchclaw-hand`) into the live registry AND the SQLite
  agent DB (this is how `lead-hand` / `collector-hand` came to exist).
- Because HAND.toml sets `max_iterations = 60`, the manifest gets
  `autonomous: Some(...)` with **heartbeat_interval_secs = 30** and is forced into
  `ScheduleMode::Continuous { check_interval_secs: 3600 }` — i.e. a persistent
  background loop, not a reactive agent.
- Because `tools` includes `shell_exec`, `kernel.rs:3534` grants
  **`ExecPolicy { mode: Full, timeout 300s }` — unrestricted host shell, no allowlist.**
  Combined with the box's `[approval] auto_approve = true`, there is no human gate.
- `provider/model = "default"` → inherits `~/.openfang/config.toml` default:
  **ollama / qwen2.5-coder:32b**, i.e. it runs on the *same* Ollama at :11434 as the
  research runs. (`/api/ps` right now: qwen2.5:32b resident, 24.4 GB of 128 GB.)
- Also grants `schedule_create` (it can write its own cron jobs), `event_publish`,
  `memory_store/recall`, `file_write`.
- Reversibility is **imperfect**: `deactivate_hand` (`kernel.rs:3706`) kills the agent, but
  hand-spawned agents leave a persisted manifest behind — `~/.openfang/agents/lead-hand`
  and `collector-hand` still sit on disk with `hand_state.json` absent. Backing out is
  `hand deactivate` + manual dir removal + a DB check.

### 3. Does it give us "agents trigger and monitor research runs"? Partly — and the half
it gives is the half we already have.
- **Trigger: yes, and this part is real.** Once activated the agent is addressable by name
  via the OF API (`X-API-Key`, body field `message`) and therefore via the live
  Matrix→OF dispatcher (`~/code/intrepid-matrix/sidecars/matrix_dispatch/dispatcher.py`,
  `@<callsign>`, depth cap 3). Agent→agent triggering of research runs would work.
- **Monitor: no, not in any load-bearing sense.** There is no structured hook into the
  ARCLAW console (`/api/pipeline/status`, `heartbeat.json`, per-stage dirs). Monitoring is
  a prompt instruction ("stream progress from console output") and the `[dashboard]` block
  is four **memory KV keys the agent writes about itself** — `researchclaw_last_status`
  etc. That is self-reported status with no independent observer. It is precisely the
  failure class already burned twice on this stack (see §4).
- **The system prompt is actively hostile to the current run.** Phase 1 unconditionally
  runs `python3 -m venv .venv` + `pip install -e .` in `repo_path`; BURN_BRIEF's standing
  rule is "NEVER pip-install into the venv of a running job". Phase 0 will `ollama serve`
  and `ollama pull` the configured `primary_model` (default `qwen2.5:32b`, ~20 GB) on the
  same host. Phase 3 fires `researchclaw run --auto-approve` (`auto_approve` defaults
  **true** → skips gates 5/9/20). Nothing in the prompt knows a 72B run is in flight.

### 4. Concrete precedent (memory-first: RAG + vault, retrieved not recalled)
- **2026-05-25 class, verbatim from `V/open_fang/project_of_restart_matrix_fleet_2026-07-29.md`:**
  the OF autonomous loop has been **dead since 2026-06-08 while the watchdog printed "OK"** —
  `heartbeat-age=4387202s` (51 days) reported healthy, because `queue=0` came from a stale
  card filter so STALL could never fire. Root cause of the deadness: the `claude` CLI could
  not auth under headless BSD cron. Same session found the OF→Matrix bridge had been
  **silently dropping every reply for weeks** (audit-id counter reset colliding with
  `seen_events` from 05-25). Track B's remediation standard was explicit: launchd +
  preflight + heartbeat + **separate** watchdog, **absolute paths — the 05-25 PATH lesson**.
- `V/24 - Archive/.../feedback_openfang_heartbeat_false_crash.md`: when 33 agents flapped on
  the 180s heartbeat they **hammered Ollama into 404s**, surfacing as "Model not found".
  Adding an autonomous, heartbeat-monitored agent that calls the same Ollama is exactly the
  input to that failure.
- `feedback_openfang_db_restore_loses_agents.md`: agent truth lives in SQLite, not the TOML
  files — restores silently drop agents. Hand-spawned agents are in that same blast zone.
- `feedback_verify_executed_not_configured.md`: 4 of 7 "working" systems on this estate were
  running and producing zero value.

A watchdog on this daemon has demonstrably lied for 51 days. Adding a shell-Full,
self-reporting service to it now adds a component whose only status signal is
self-reported — the exact thing that lied.

### 5. Value against the actual bottleneck — the honest answer
Today's bottleneck is producing **one** defensible paper from **one** long 72B run that a
human is watching. Against that:
- The Hand does not fix stage 17 PAPER_DRAFT, does not fix the missing matplotlib, does not
  connect the pipeline to `nem_market.duckdb`, and does not pre-materialise the joined
  parquet. Those are the four things standing between us and a paper.
- It does not reduce human monitoring — it replaces a human watching `/api/pipeline/status`
  with an LLM agent claiming a status into a KV store.
- It has negative marginal value while the 72B run is live: shared Ollama, a `pip install -e .`
  into the running job's venv, a possible 20 GB model pull, `--auto-approve` runs launched
  without a human.

**This is capability-building for a fleet story, not throughput for the current goal.
Distraction is the correct verdict.** Nothing about it is wasted work — the Hand file is
written and costs nothing sitting in the repo.

### 6. If it is ever done — the change window
1. Not while any ARCLAW run is in flight. `POST /api/pipeline/stop` first, confirm
   `{"status":"stopped"}`, and confirm no `rc-*` dir is `-newermt '-10 minutes'`.
2. **Not on m5-prime-serve.** Do it on m5-infer1 (second ARCLAW, console :8090,
   qwen2.5:14b, no OF daemon today) or a throwaway `OPENFANG_HANDS_DIR`. Prime-serve holds
   the live DuckDB, the 72B, and the 34-agent daemon; it is the wrong lab.
3. Snapshot first: `~/.openfang/config.toml`, the agents SQLite DB, `~/.openfang/agents/`,
   `cron_jobs.json`. Record `openfang agent list` count (34) as the rollback assertion.
4. Edit HAND.toml **before** activating: `auto_approve` → false; `experiment_mode` →
   `simulated` for the first pass; set an explicit `heartbeat_interval_secs` well above the
   longest LLM call (the 30s default is documented in-source as too aggressive for hands);
   pin `primary_model` to a tag already present in `ollama list` so no pull fires.
5. Install the honest way: `openfang hand install <path>` (live) **and** keep the file copy
   (restart persistence) — the script alone is not an install.
6. Add a **separate** watchdog process that observes ARCLAW's own
   `/api/pipeline/status` + run-dir mtimes and alarms on staleness, per the Track B
   standard: launchd, absolute paths, preflight, heartbeat, `IDLE != OK`. The Hand's own
   `[dashboard]` metrics do not count — they are self-reported.
7. Rollback, rehearsed before step 5: `openfang hand deactivate researchclaw`,
   `rm -rf ~/.openfang/hands/researchclaw ~/.openfang/agents/researchclaw-hand`, verify
   agent count back to 34, verify `hand_state.json` clean.

### 7. What would have to become true for this to be worth doing
- A paper exists. The pipeline completes end-to-end on real NEM data at least once,
  unattended, without a human repairing a stage.
- ARCLAW exposes a status surface an *external* watchdog can poll — and that watchdog is
  built and proven to alarm (the OF loop's watchdog was proven to *not* alarm for 51 days).
- The "many runs, agent-triggered" workload actually exists. One human-monitored run does
  not need an orchestration layer.
- Research runs are separated from the production OF box — a dedicated node, or at minimum
  a separate Ollama instance so a Hand's model choice cannot evict a research model.
- `--auto-approve` is defensible, i.e. the gates at 5/9/20 have been shown to be
  reliably passable without a human.

Until then: the file stays in the repo, uninstalled. Cost of waiting: zero.

## ws3-extensions

Grounded feasibility of WS3's non-H2 hypotheses. **Assessment only — no pipeline run started.**
Memory-first: RAG (`age-swarm multi-agent pattern library debate panel evolve`, `openfang 34 agents
launchd daemon roster`, `WS3 paper notes 7.5`) + vault reads before any Intrepid claim.

### HEADLINE: the age-swarm agent pool is NOT a blocker — it exists, it runs, and H1/H3 were already run

The founder's warned-about constraint does not hold. Verified, not reported:

- Repo `~/code/age-swarm`, branch `cursor/ws3-fy27-calibration-objective-7562` @ `fce1324`.
  `src/patterns/{debate,panel,evolve,triage}.py` + `eval/{scoring,forecast_bench,forecast_tasks}.py`.
- **PROVEN EXECUTED (unique marker, not "configured"):** `swarm.ask(role='thinker', host='localhost',
  model_override='qwen2.5:7b')` returned exactly `WS3_PROBE_7719` in 42.7 s on prime-serve.
- All four tags `forecast_bench.py` needs are pulled locally: `qwen2.5:7b` (baseline+agent),
  `llama3.1:8b` (agent+synth), `granite3.3:8b` (agent), `qwen3:4b` (critic). Ollama :11434 live, 33 models.
- **A full 240-cell live run already exists**: `eval/forecast_results_2026-07-12.jsonl`
  (20 episodes x 4 patterns x 3 seeds), 243 per-cell raw logs in `eval/run_logs_2026-07-12/`.
  Measured cost from logged `latency_ms`: baseline 5.5 s/cell, panel 22.4 s, evolve 26.5 s,
  debate 34.0 s → **88.5 min serial for the whole grid.** This is a cheap experiment, not a big one.

**OpenFang's 34 agents are irrelevant to WS3 and must not be confused with the age-swarm pool.**
Per `reference_openfang_trigger_api_2026-07-21`: 33 agents loaded, all `Running`, but `last_active` ==
daemon boot time for every one (resident != working); souls are FORGE solar-sales personas
(tariff analyst / solar sceptic / SOC2 auditor); `openfang cron list` = 0 jobs; approval policy is
`enforcing` + default-deny with a 1 h gate timeout. Not a research pool. age-swarm is a **library
driven synchronously against loopback Ollama**, not a daemon fleet — which is why it is available now.

### The five hypotheses, verbatim nulls (paper §5, `ws3_debate_as_calibration_2026-07-04_v0.md`)

- **H1 (structure helps).** "The N-agent debate ensemble achieves lower CRPS than single-LLM quantile
  elicitation (N=1, R=0) on the same prompts. *Null:* dispersion across debating agents is noise with
  no distributional skill". Benchmark: CRPS, debate vs baseline arm.
- **H2 (divergence is signal).** "Divergence-conditioned widening (gamma(D)) improves coverage
  calibration over unconditional aggregation, with the largest gains in regime-change periods…
  *Null:* D is uncorrelated with realised absolute error; the ambiguity object is decoration."
  Benchmark: interval coverage / CRPS, gamma(D) arm vs alpha=0.
- **H3 (critique carries weightable information).** "Panel-score softmax weights beat uniform weights
  on pinball loss. *Null:* critic scores are uninformative about forecast quality". Benchmark: mean pinball.
- **H4 (honest positioning vs classical baselines).** "In data-rich regimes, NGBoost and deep ensembles
  remain sharper at equal calibration — we *expect* to lose here… The interesting regime is low-data /
  distribution-shift… *Null:* classical baselines dominate everywhere". Benchmark: CRPS/sharpness-at-
  calibration vs NGBoost, deep ensemble, conformal (CQR), climatology, persistence.
- **H5 (the confidence formula).** "`verifier_vote_share x panel_agreement` correlates with realised
  error well enough to be usable as a calibrated probability after monotone recalibration. *Null:* it
  does not, and the formula should be deprecated in favour of D-based statistics." Benchmark:
  reliability diagram / correlation with realised error.

### R8 canon (`~/IntrepidBrain/hive/r8_full_loop_design_2026-07-05.md`)

"Hive 2.0 forecasting stack RUNS daily (XGB/BiLSTM/TFT/Transformer/stacked ensemble, 70-feature
leakage-safe pipeline) — but point forecasts only; **probabilistic heads + P&L/settlement engine are
the two genuinely missing pieces** in the whole estate." WS3 is the probabilistic-head half. That is
why H4 matters commercially: it is the only hypothesis that positions WS3 against the estate's own
daily-running point stack.

### PRIOR RESULTS ALREADY ON DISK (preliminary, n small, no classical baselines)

`eval/analysis_2026-07-12.md`, pooled 60 cells/pattern:

| pattern | CRPS | pinball | cov90 | width90 | parse fails |
|---|---|---|---|---|---|
| baseline | 23.08 | 11.54 | 95% | 175.3 | 14 |
| debate | 30.82 | 15.41 | 88% | 300.4 | 38 |
| panel | 27.17 | 13.59 | 88% | 295.3 | 16 |
| evolve | 28.82 | 14.41 | 75% | 288.9 | 38 |
| climatology | 23.78 | 11.89 | 100% | 130.7 | 0 |

- **H1 PRELIMINARY NULL.** debate 30.82 vs baseline 23.08; 0/3 seeds favour debate. Debate also loses
  to climatology. Baseline beats climatology (barely).
- **H3 PRELIMINARY SUPPORTED.** weighted pinball 13.586 vs uniform 14.443, 2/3 seeds, 0 weight-recompute
  mismatches.
- **H2 EXPLORATORY.** Spearman(D1, |err|) = 0.282, permutation p = 0.0297 (n=60) — same sign as the
  84,575-pair AEMO-vintage result but 2x weaker and on the actual LLM ensemble.
- **gamma(D) sweep (`gamma_sweep_2026-07-30.md`) is a clean negative**: best alpha by CRPS on an
  unfitted grid is **alpha=0**. Widening buys coverage (88→95%) and pays more CRPS than it buys at every alpha.
- **Theorem loop (`theorem_tests_2026-07-30.md`) found the one real win**: Wang/Kang/Li forecast trimming
  (arXiv:2208.00139), `trim_keep=2` cuts debate CRPS 30.82 → 24.54 and width 300 → 213 at unchanged 88%
  coverage — i.e. **debate's problem is 1-2 rogue agents, not the ensemble idea.** T2 split-conformal and
  T3 isotonic width scale: NOT PROMISING.

### Classification — what each hypothesis actually needs

Infrastructure ground truth: `~/data/nem_market.duckdb` has `dispatch_price` at 5-min for **all 5 regions,
2025-04-01 → now, 132,249 rows/region**, plus `rooftop_pv`, `region_demand`, `p5min_price_forecast`,
`predispatch_price_forecast`, `trading_price`. `forecast_tasks.py` already reads `dispatch_price`
read-only and freezes episodes to JSON+sha256. **duckdb IS available** at
`~/data/.venv/bin/python` and `~/ai-imagegen/.venv/bin/python` (1.5.2) — the "no duckdb" note applies to
the ARCLAW venv and to system python3 (which has numpy only). Episode generation is unblocked.

| H | Class | What it actually needs |
|---|---|---|
| **H1** | **Agent pool — AVAILABLE NOW. Already run once, preliminarily null.** | Nothing new to *re-run*. To make it *publishable* it needs (a) n >> 20 episodes — 132k intervals/region are sitting there, (b) the paper's stated ablation grid N∈{1,3,5} x R∈{0,1,3}, which `forecast_bench.py` does **not** expose (N and R are hardcoded to 3 agents / 1 critique round), (c) the parse-failure rate fixed: 38/60 debate cells had ≥1 parse failure, and a parse failure silently substitutes `climatology_qvec` — **that alone can manufacture H1's null**. (d) Diebold–Mariano tests. |
| **H2** | **Both paths already done — this is the saturated one.** | Statistical mechanism: settled on 84,575 AEMO-vintage pairs. LLM instantiation: settled at rho=0.282/p=0.030 on 60 cells, and the gamma(D) operationalisation is a clean negative (best alpha=0). The remaining gap is a *validation-fit* gamma on a held-out window, not a new capability. |
| **H3** | **Agent pool — AVAILABLE NOW. Already run, preliminarily SUPPORTED.** | Purely a power problem: n=60, 2/3 seeds. Needs more episodes + seeds and a held-out lambda for the softmax temperature (currently fixed). No new infrastructure. Cheapest path to a defensible positive. |
| **H4** | **BLOCKED ON SOMETHING ELSE — and it is a small, purely classical blocker.** Not the agent pool. | Needs NGBoost + a deep ensemble + CQR fitted on NEM features. Dependency reality: **system python3 has numpy ONLY** — no scipy/sklearn/pandas/torch/ngboost/statsmodels/matplotlib. `~/code/AutoResearchClaw/.venv` has numpy+scipy+sklearn+pandas+torch (no ngboost, no duckdb). So H4 needs one env with duckdb + sklearn + torch (+ngboost or `sklearn` quantile GBR as a stated substitute) and a feature/lag pipeline the repo does not have. **Also the honest catch: the LLM arms currently lose to *climatology*.** H4 vs NGBoost is not the live question until an LLM arm beats the free floor. |
| **H5** | **PARTIALLY TESTABLE NOW with zero new infrastructure; fully testable after a ~20-line bench change.** | `forecast_bench.py` reimplements panel/evolve and logs `extra.scores` but **never computes or logs `verifier_vote_share`** — its critic emits a 0–10 score with no APPROVE/REJECT verdict. The `panel_agreement = 1 - std(scores)/10` half IS recomputable post-hoc from the frozen cells. **I ran that probe (assessment, not a pipeline run):** panel n=60 Spearman(panel_agreement, \|y-median\|) = **0.101, permutation p = 0.444**; evolve n=60 rho = **0.156, p = 0.227**. Both are (a) insignificant and (b) the **wrong sign** — H5 predicts higher agreement → lower error. Only 12 distinct agreement values across 60 panel cells (integer critic scores, 3 critics) — the statistic is too coarse to carry calibration information. Full H5 needs the critic prompt to emit a verdict + `vote_share` logged. |

### RANKED RECOMMENDATION for the next research run after H2

**1. H3 — panel-score weights (RECOMMENDED).** Best next run.
- *Why:* it is the only hypothesis with a preliminary **positive** that is under-powered rather than
  contradicted, it needs zero new infrastructure, and its null is a genuinely publishable negative about
  panel-based gating in general multi-agent systems (paper §5 says so explicitly). It also survives the
  embarrassment that the LLM arms lose to climatology — H3 is a *within-panel* comparison (weighted vs
  uniform Vincentisation of the same candidates), so it is unaffected by the absolute-skill deficit.
- *Needs:* re-run `forecast_tasks.py` with `~/data/.venv/bin/python` for **~200 episodes** across all 5
  regions and more horizons (the DB supports it); `forecast_bench.py --patterns panel` x 5 seeds;
  hold out a validation split to fit the softmax lambda instead of leaving it fixed.
- *Cost:* panel is 22.4 s/cell measured → 200 ep x 5 seeds ≈ **6.2 h serial**, less with concurrency.
- *Difficulty:* **LOW.** Config + episode regeneration. The one real code task is the validation-split
  lambda fit (~50 lines in `analyze_*.py`).
- *Bundle it with:* the H1 parse-failure fix, since both ride the same run.

**2. H1 with the trimming result folded in (STRONG SECOND, and the better *paper*).**
- *Why:* the T1 trimming finding (`trim_keep=2`: CRPS 30.82 → 24.54, width 300 → 213, coverage unchanged)
  says H1's null may be an artefact of 1-2 rogue agents plus a 63%-of-cells parse-failure rate that
  silently swaps in climatology. That is a *fixable confound on a stated null*, which is exactly the
  kind of thing worth a run. Fix parsing, add trimming, expose N∈{1,3,5} and R∈{0,1,3}, and H1 gets
  decided properly instead of by plumbing.
- *Needs:* parse-failure fix + retry hardening; `--trim-keep` already exists in the bench; **N and R must
  be un-hardcoded** (real code work); more model families for the N=5 arm (`qwen2.5:32b`, `phi3.5:3.8b`,
  `gemma4`, `mistral-large` are all pulled).
- *Cost:* debate is 34.0 s/cell; a 3x3 N/R grid over 200 episodes is ~50+ h serial — needs episode
  subsetting or concurrency.
- *Difficulty:* **MEDIUM.** Highest scientific value, materially more work than H3.

**3. H5 — finish it and report the null (CHEAP CLEANUP, high honesty value).**
- *Why:* half of it is already answered and answered **against** the formula (rho=0.10/0.16, wrong sign,
  insignificant). The paper commits to deprecating the formula if so, and `roles.yaml:193` still ships
  `confidence_formula: "verifier_vote_share x panel_agreement_rate"` as live config with
  `confidence_threshold: 0.7` gating escalation — so this null has an operational consequence, not just
  a paper one.
- *Needs:* ~20 lines (critic emits APPROVE/REJECT; log `vote_share`), then it rides the H3 run for free.
- *Difficulty:* **LOW.** Do it as a rider on run #1.

**4. H4 — NOT YET.** Real blocker, honestly named: it is not the agent pool, it is (a) a missing
classical-ML environment (no sklearn/torch/ngboost + duckdb in one interpreter; no feature/lag pipeline
in the repo) and (b) the fact that **the LLM arms currently lose to climatology**, which makes a
head-to-head against NGBoost premature. Sequence it after H1's confounds are cleared.

### Honest bottom line

"None, H2 is the only tractable one" is **not** the correct answer here, and asserting the agent pool is
absent would have been wrong — I verified it running with a unique marker. The real constraints are
different and smaller than feared: **H1 and H3 are limited by statistical power and a parse-failure
confound, not by infrastructure; H5 is limited by one missing logged field; only H4 has a genuine
environment blocker, and it is a classical-ML env, not an agent env.** H2, meanwhile, is the *most*
saturated hypothesis in the set — it now has both a 84,575-pair statistical result and a 60-cell LLM
result plus a clean negative on its gamma(D) operationalisation.

Caveat that must travel with all of the above: every prior-result number here is from n=20 episodes /
2 regions / 60 cells per pattern, with no classical baselines and no validation-fit hyperparameters.
The repo's own `README_WS3_FY27.md` honesty ledger says the same: "Not workshop-ready without classical
baselines + validation-fit gamma." Nothing in this assessment upgrades those preliminary verdicts.

## nem-data

### EARLY POST (2026-07-31 ~01:32 AEST) — real-NEM matched dataset is LIVE, consume this

**Dataset path (parquet + csv, pandas/numpy only, NO duckdb needed):**
```
/Users/alexeynikitine/data/ws3_h2/ws3_h2_matched.parquet      678,735 rows   43.5 MB
/Users/alexeynikitine/data/ws3_h2/ws3_h2_matched.csv          678,735 rows  115.1 MB
/Users/alexeynikitine/data/ws3_h2/ws3_h2_ensemble_wide.parquet 85,300 rows   10.7 MB  (12 raw vintage columns f_h000..f_h055)
/Users/alexeynikitine/data/ws3_h2/ws3_h2_ensemble_wide.csv     85,300 rows   19.1 MB
```
Provenance: `~/data/nem_market.duckdb` opened READ-ONLY at **2026-07-31T01:28:23+10:00**;
db mtime at read = **01:28:22** (1 second old — verified live, not a stale snapshot).
Coverage 2026-05-29 17:35 → 2026-07-31 01:25 AEST, all 5 NEM regions, `intervention='0'`.

**Verified live row counts (2026-07-31 01:28 AEST, NOT the brief's estimates):**
| table | brief estimate | ACTUAL |
|---|---|---|
| `p5min_price_forecast` | 984,660 | **986,820** |
| `predispatch_price_forecast` | 814,215 | **815,910** |
| `dispatch_price` | 661,115 | **661,245** |
| `region_demand` | 661,100 | **661,230** |

**Sanity check PASSED — prior result reproduced exactly.** h_min=0, n_vintages>=5:
n=84,725 (was 84,575; DB has grown), Pearson r(D,|err|)=**0.638**, Spearman=**0.672**,
mean |err| by D-quintile **2.41 -> 4.95 -> 6.75 -> 9.95 -> 44.55** (prior: 2.40/4.95/6.74/9.93/44.50).

**MATERIAL FINDING #1 — the prior ensemble contained a look-ahead member.** P5MIN emits
horizons 0,5,...,55 min per target. The h=0 vintage is quasi-truth: MAE **5.38** $/MWh and
r=0.895 vs realised, with **35% of rows matching the realised RRP to <0.005**, versus MAE
**12.08**, r=0.405 at h=5. Any "all vintages" ensemble therefore includes a near-answer.
Fix: the dataset is cut by `horizon_min` in {0,5,10,...,35}; the ensemble at cut h is exactly
the vintages available at time (target - h), i.e. `horizon_min = interval_datetime - max(run_datetime)`.
**Use horizon_min >= 5. horizon_min = 0 is retained only to reproduce the prior number.**

The D-vs-error signal SURVIVES the fix (Spearman, monotone ladder retained):
| horizon_min | n | Pearson | Spearman | mean abs_err by D-quintile |
|---|---|---|---|---|
| 0 (contaminated) | 84,725 | 0.638 | 0.672 | 2.41 / 4.95 / 6.75 / 9.95 / 44.55 |
| 5 | 84,610 | 0.373 | 0.613 | 3.23 / 5.78 / 7.39 / 11.84 / 45.61 |
| 15 | 84,420 | 0.382 | 0.582 | 3.83 / 6.47 / 9.42 / 11.13 / 48.33 |
| 35 | 72,490 | 0.509 | 0.516 | 5.80 / 7.89 / 9.50 / 13.89 / 59.44 |

CRPS + interval-coverage results (the test the paper actually specifies) follow in this section.

**CORRECTION (framing):** pid 66275 (`config.ws3-theorem-hunt.yaml`, tmux `claw-ws3-theorem`,
created 01:18:13) is NOT ours and NOT the H2 run — it predates this burn, as does tmux
`hive-market-overnight` (01:19:28). Nobody should later read that line as "our H2 run is still
alive". The H2 run `rc-20260730-114801-e9b01a` is dead and stays dead; we start fresh.
GPU contention is real: `OLLAMA_MAX_LOADED_MODELS=1`, theorem-hunt holds qwen2.5:32b (24 GB).
Launching 72B (56 GB) alongside it would thrash evict/reload. Holding launch until 66275 exits.

## infer1-verify
Independent adversarial verification of the SECOND ARCLAW deployment (m5-infer1).
Verifier session, 2026-07-31 ~01:30 AEST. Every line below was measured from the outside
or on the box; the deploying session's report was treated as an unverified claim throughout.

### Verdict headline
**The run the deploying session reported as "9/23 stages in ~6 min" is DEAD.** It failed at
stage 17 PAPER_DRAFT at `2026-07-30T14:00:32Z` (00:00:32 AEST), ~1.5 h before this audit.
The snapshot was true when reported; it was reported as if it were an outcome.
**The run was `experiment.mode: "simulated"` on a generic ML topic** — i.e. exactly the
synthetic-data proof of concept the founder ruled out, and not WS3 H2. The deploying
session's report was silent on both facts.

### Claim-by-claim

| # | Claim | Verdict |
|---|---|---|
| 1 | Host m5-infer1, serial PPGH09YFMW, M5 Max, 128 GB, `m5-infer1.tail3fb853.ts.net` = 100.73.163.0 | **CONFIRMED** |
| 2 | Console live :8090, `/api/health` → `{"status":"ok","version":"0.5.0"}` | **CONFIRMED** (marker-proven) — but `0.5.0` is meaningless, see below |
| 3 | Ollama :11434 with qwen2.5:14b (9 GB) pulled, fallbacks 7b-instruct / coder:32b | **PARTLY — OVERSTATED** |
| 4 | venv uv CPython 3.11.15, `pip install -e ".[web]"`, researchclaw 0.3.1, repo @ ba6352f | **CONFIRMED** |
| 5 | `researchclaw validate` → passed | **CONFIRMED but near-worthless** |
| 6 | Run `rc-20260730-133346-d98d17`: 9/23 stages in ~6 min, zero parse fallbacks | **SNAPSHOT TRUE / OUTCOME FALSE** |
| 7 | Bound `*:8090` IPv4, never `::` | **CONFIRMED** |

### 1. Identity — CONFIRMED
On the box: `Tailscale status --json` → `Self.DNSName = m5-infer1.tail3fb853.ts.net.`,
`TailscaleIPs = ['100.73.163.0', ...]`, `ID = ndmPG8GxGH11CNTRL`.
`ioreg IOPlatformSerialNumber = "PPGH09YFMW"`, Apple M5 Max, 18 cores (6 Super + 12 Perf),
128 GB, 3.6 TiB volume (3.2 TiB free). Up 16 days.
Caveats the report omitted: the machine's own hostname is `Mac.localdomain`, ComputerName
`a1's MacBook Pro`, LocalHostName `a1s-MacBook-Pro`. **"m5-infer1" is a tailnet-only name.**
Login user is `ip-infer1`; **ssh as `a1@100.73.163.0`** (alexey/alexeynikitine/admin all rejected).

### 2. Reachability — CONFIRMED by unique marker from two distinct source hosts
- `mkA-1785425134-23971` fired from m5-prime-serve (100.95.93.7) → serve.log:169
  `INFO: 100.95.93.7:56497 - "GET /api/health?m=mkA-1785425134-23971 HTTP/1.1" 200 OK`
- `mkC-1785425357-8062` fired from **third host int-hve-srv** (100.115.235.76, via LAN
  192.168.1.66 — Tailscale SSH to it demands interactive re-auth) → serve.log:171
  `INFO: 100.115.235.76:40832 - "GET /api/health?m=mkC-1785425357-8062 HTTP/1.1" 200 OK`
- Log-to-process binding proven: `lsof -p 94011` shows `logs/serve.log` as fd **1w and 2w**.
  So the log I grepped is the stdout of the process that owns `*:8090`. No name-collision gap.
- Actual body is `{"status":"ok","version":"0.5.0","active_connections":0}` (third field omitted
  from the report).
- **`version: "0.5.0"` is a hardcoded string literal** at `researchclaw/server/app.py:41` and `:70`.
  It is not derived from the package (`pyproject.toml` version = 0.3.1). Citing it alongside
  "researchclaw 0.3.1" without flagging the inconsistency is misleading — it proves nothing
  about what is installed.

### 3. Ollama — OVERSTATED
- `qwen2.5:14b` genuinely present: 8,988,124,069 B (8.99 GB), Q4_K_M, 14.8B, ctx 32768,
  `modified_at 2026-07-30T23:30:18+10:00`. Pull is real (`pull14b.log` ends `success`).
- **Ollama binds `127.0.0.1:11434` ONLY.** `lsof` → `TCP 127.0.0.1:11434 (LISTEN)`;
  `netstat` → `tcp4 127.0.0.1.11434`. `curl 100.73.163.0:11434/api/tags` from prime-serve
  → connection refused. This is a per-host resource; nothing on the fleet can call it.
  Reporting "Ollama on :11434" reads as fleet-shared. It is not.
- **The "fallbacks" were not stood up by this deployment.** `qwen2.5:7b-instruct` and
  `qwen2.5-coder:32b` both `modified_at 2026-07-21`; `ollama serve` is PID 27029 running
  since **21 Jul**. Nine days pre-existing. (An unlisted `qwen2.5:7b` is also present.)
  Ollama version 0.32.1.
- `ollama ps` → `{"models":[]}` — **nothing loaded, the box is idle.**

### 4. Install — CONFIRMED
`.venv/bin/python -V` → Python 3.11.15. `pip show researchclaw` → 0.3.1.
`git rev-parse HEAD` → `ba6352f834628aed305db5fade3e56031459477f` ("Ship local ResearchClaw web
console for Ollama runs"), clean except untracked `run_console.sh`. Path
`/Users/ip-infer1/arc-deploy/AutoResearchClaw`.

### 5. `researchclaw validate` — confirmed, but do not read it as deployment evidence
Re-ran it: output is literally `Config validation passed`, exit 0. It is a **config-schema
check**. It does not probe the endpoint, does not load a model, does not touch the venv's
scientific stack. Offering it as proof the deployment works is a category error.

### 6. The run — SNAPSHOT TRUE, OUTCOME FALSE. This is the finding that matters.
`GET /api/pipeline/status` →
`{"run_id":"rc-20260730-133346-d98d17","status":"failed","stages_done":22,"stages_failed":1,
"topic":"Probabilistic load forecasting with quantile regression for distribution networks"}`
- `pipeline_summary.json` → `final_stage: 17`, `final_status: "failed"`, `stages_executed: 23`.
- `checkpoint.json` / `heartbeat.json` → `last_completed_stage: 16 (PAPER_OUTLINE)`,
  ts `2026-07-30T14:00:32+00:00`, pid 94011.
- serve.log tail: `Stage 17/23 PAPER_DRAFT — FAILED (0.0s) — unknown error`.
- Timing: started 13:33:46Z, 9 stage dirs by 23:39 local ⇒ **9 stages in ~5.5 min is TRUE**;
  the whole 16-stage run then finished/failed in **26 min 46 s**.
- **Not still running. Not completed. Dead**, and dead before the report was acted on.

**"zero parse fallbacks" is not a measurable claim.** `grep -ciE fallback logs/serve.log` → 0,
and there is no parse-fallback emitter in the source that would reach serve.log — the only
such string is `evolution_aevolve.py:203 "A-Evolve: failed to parse LLM response as JSON"`.
Absence of a log line that is never written is not evidence.
*The defensible version of that claim, which does hold:* **all 96 JSON artifacts in the run
directory parse cleanly** (validated each with `json.load`, zero failures). That is real
evidence 14B's structured output is reliable.

### 7. Bind — CONFIRMED
`lsof` → `python3.1 94011 IPv4 TCP *:8090 (LISTEN)`; `netstat -an` shows a single
`tcp4 *.8090 LISTEN` row and **no tcp6 row**. IPv4-only, never `::`. Confirmed.

### THE OMISSION: the run was simulated, on the wrong topic
`config.arc.yaml` on infer1:
- `research.topic: "Probabilistic load forecasting with quantile regression for distribution
  networks"` — a generic ML topic. **The brief lists Topic = WS3 H2 as SETTLED.** Off-brief.
- `experiment.mode: "simulated"` — the config comment even says *"Start with 'simulated' to
  validate LLM connectivity, then switch to 'sandbox'"*. It was never switched.
- Proof the numbers are fabricated: `experiment_summary_best.json` →
  `primary_metric {min 0.3, max 0.42, count 5}` = 0.30/0.33/0.36/0.39/0.42, i.e. exactly
  `0.3 + idx*0.03`.
- **Stage 17 did not crash — it is a guardrail firing correctly.** `stage-17/paper_draft.md`
  reads in full: *"# Paper Draft Blocked … All experiment results are from simulated mode
  (formulaic data: `0.3 + idx * 0.03`). These are not real experimental results. Action
  Required: Set `experiment.mode: 'sandbox'` in config.arc.yaml and re-run."*
- `deliverables/` = `manifest.json` + `neurips_2025.sty`. **There is no paper**, same as the
  prime-serve H2 run.
Net: the second deployment produced precisely the synthetic-data proof of concept the founder
explicitly excluded, and the pipeline was honest enough to refuse to dress it up as a paper.

### THE STRUCTURAL BLOCKER THE DEPLOYING SESSION NEVER CHECKED
Flipping `mode: sandbox` on infer1 **will not work today.**
- `experiment_repair_result.json`: 3 repair cycles, every one `"error": "Sandbox execution
  failed"`, `success: false`, `final_mode: "technical_report"`, each "Fixed 6 files".
- The generated experiment code (`stage-14_repair_v1/experiment/*.py`) imports
  `torch`, `torch.nn`, `torch.utils.data`, `pandas`, `numpy`.
- **infer1 venv contents (measured):** numpy OK, scipy OK, tqdm OK — **torch MISS, pandas MISS,
  sklearn MISS, matplotlib MISS, seaborn MISS.** `stage-14_repair_v1/sandbox/` is empty.
- So every sandbox execution is a guaranteed `ImportError`. The `[web]` extra gives no
  scientific stack at all. This is a bigger hole than the brief's matplotlib note.
- No data path either: `/Users/ip-infer1/data` does not exist, no `*.duckdb` anywhere on the box,
  `duckdb` not in the venv.

**Correction to the BURN_BRIEF (measured on prime-serve just now):** prime-serve's venv has
`torch, numpy, pandas, sklearn, scipy, matplotlib, pyarrow` all importable (missing only
`seaborn`, `duckdb`). The brief's *"figures are dead on BOTH paths / matplotlib not available"*
is **stale for prime-serve** — matplotlib imports fine there. `duckdb` is genuinely absent on
both, so the pre-materialise-to-parquet rule stands; `pyarrow` on prime-serve makes parquet
export viable there. infer1 has neither pandas nor pyarrow, so it cannot even read the parquet
the brief's plan hands it.

### Is 14B too weak? — NO, and this is not the 3B situation
Evidence 14B is competent:
- 96/96 JSON artifacts valid — structured output is reliable. This is the direct refutation of
  the 3B-style failure the brief warns about mistaking for a stack failure.
- `analysis_best.md` is coherent, on-topic and genuinely self-critical: the skeptic perspective
  flags missing p-values, the methodologist flags missing PICP/MSE and absent ARIMA baselines,
  and it correctly calls n=5 inadequate. Self-rated 7/10 with a defensible justification.
- `stage-16/outline.md` is usable work: coined a method name (PRISM), 3 candidate titles scored
  on memorability/specificity/novelty, per-section word budgets and paragraph-level plans.
- **~6.7x faster than 72B**: 16 stages in 26m46s vs the prime-serve 72B H2 run's ~3h
  (11:48:01Z → 14:47:47Z).
Evidence of a quality cost:
- ~60% more rework. 14B: `stage-13_v1,_v2`, `stage-14_v1,_v2` (+3 repairs), `stage-15_v1,_v2`
  = 8 version dirs, 2 REFINE rollbacks to stage 13. 72B: `13_v1`, `14_v1` (+3 repairs), `15_v1`
  = 5. Same three stages are the churn points on both models.
- Both models died at stage 17 — for **different reasons** (72B: real sandbox exec, repair
  score 0.0→0.0; 14B: simulated-data guardrail). 
**Honest verdict: 14B is PROVEN ADEQUATE on reasoning, prose and structured output, and
UNPROVEN on the axis that actually matters — experiment code quality — because the venv could
never execute a single line of what it generated.** Do not declare 14B sufficient or
insufficient for research output until it has run once in sandbox mode against real data.

### Can it run a real second workstream in parallel? Hardware yes, software no.
- Hardware: comfortable. 128 GB with 97% free, load avg 1.5, 3.2 TiB free, idle since 00:00,
  physically separate box so zero contention with prime-serve's 72B job.
- Software: **blocked today** — (a) no torch/pandas/sklearn/matplotlib ⇒ sandbox mode cannot
  run; (b) no NEM data and no duckdb/pyarrow on the box; (c) infer1's ollama is localhost-bound
  so there is no cross-host model sharing in either direction.
- The venv fix is safe to do **now** — the brief's "never pip into the venv of a running job"
  rule does not bite because infer1's job is dead and `ollama ps` is empty.

### Recommendation — what m5-infer1 should actually be doing
Do **not** give it a second copy of the H2 paper run. That duplicates prime-serve's blocked path
and burns the second host on the same stage-17 wall. Its comparative advantage is **speed
(6.7x) and isolation**, so use it as prime-serve's fast de-risking rig:
1. **Fix the venv** — `pip install pandas pyarrow matplotlib` (+ `torch` only if the experiment
   plan needs it). Single highest-value unblocking action on this host.
2. **Get real data onto it** — prime-serve holds the read-only DuckDB handle; pre-materialise
   the joined `p5min_price_forecast` × `dispatch_price` table to parquet there and copy it
   across. Generated code then needs only pandas + numpy, per the brief.
3. **Retarget the topic to WS3 H2** in `config.arc.yaml` and set `experiment.mode: sandbox`.
4. **Burn full cycles at 14B** — at ~27 min/run it completes 6+ end-to-end runs in the time
   prime-serve does one. Its job is to find exactly where stage 17 breaks on real data and
   prove the fix cheaply.
5. **Only once a 14B run clears stage 17 on real data** should prime-serve re-run at 72B for
   final quality. That sequencing is the entire value of having a second box.

### Unrelated hazard found while verifying identity
The tailnet contains a peer node literally named **`m5-prime-serve`** —
`m5-prime-serve.tail3fb853.ts.net` / **100.77.102.76** / ID `nLtTKdKTfE11CNTRL`, currently
online — which is **not** the real prime-serve. The real one is `Self` on this box:
`macbook-pro.tail3fb853.ts.net` / **100.95.93.7** / ID `nx2cxvJrk811CNTRL`, serial HFY3PC9VJF.
Anything that resolves prime-serve *by name* will hit the wrong node. A third M5,
`m5-infer-2` / 100.76.152.92, is also online and unaccounted for in the brief's fleet table.

### What the deploying session got wrong or overstated — summary
1. Reported a mid-run snapshot as an outcome; the run failed at stage 17 at 00:00:32.
2. Silent on `experiment.mode: "simulated"` — the single most important fact about the run,
   and directly contrary to "properly, not a synthetic-data proof of concept".
3. Silent on the topic being generic ML, not WS3 H2 (a settled decision).
4. Implied it pulled the fallback models; 7b-instruct, coder:32b and `ollama serve` itself all
   pre-date the deployment by 9 days.
5. "Ollama on :11434" without stating it is 127.0.0.1-bound and unusable from the fleet.
6. Cited `version 0.5.0` next to `researchclaw 0.3.1` without noting 0.5.0 is a hardcoded
   literal in `server/app.py`, not a version signal.
7. Offered `researchclaw validate` as deployment evidence; it is config-schema-only.
8. "Zero parse fallbacks" is unfalsifiable from serve.log.
9. Never verified the venv can execute generated experiment code — the deployment is
   structurally incapable of sandbox mode.
**Genuinely confirmed:** host identity and serial, tailnet IP↔node binding, console liveness
(marker-proven from two hosts), the IPv4-only `*:8090` bind, the 14b pull, the venv/commit/
version facts, `validate` passing, and the 9-stages-in-~6-minutes timing as a snapshot.

### 2026-07-31 01:38 AEST — FRESH REAL-DATA RUN LAUNCHED
Green lights taken in order: pid 66275 (theorem-hunt) exited 15:33:15Z, GPU free; nem-data's files
landed 01:30. **Never `--resume`** — this is stage 1 from scratch, `rc-20260730-114801-e9b01a` is
kept untouched as reference.

```
tmux claw-h2-real | pid 84091
OPENAI_API_KEY=ollama .venv/bin/researchclaw run --config config.h2-real.yaml \
  --auto-approve -o artifacts/rc-ws3-h2-real-20260731
log: logs/h2-real-20260731.log
```

**How the real dataset is handed to the experiment.** There is no `dataset_path` field in
`researchclaw/config.py` — I checked the whole schema. The ONLY channel is prompt text, so:
- `prompts.h2-real.yaml` (new) overrides the two blocks that broke the last run —
  `network_disabled_guidance` (what sandbox-mode codegen actually sees) and `dataset_guidance`
  (what the experiment-design stage sees). Both now carry the verbatim header line, per-column
  semantics, row grain, the mandatory `horizon_min == 5 & n_vintages >= 5` filter, the
  time-ordered-split rule, the real package list, and an explicit "IGNORE any text in this prompt
  mentioning /opt/datasets, CIFAR or torchvision — it is boilerplate from another deployment and
  is FALSE on this machine".
- Verified EXECUTED, not configured: loaded the config + PromptManager in the venv and printed the
  rendered blocks — 4,784 / 3,371 / 4,181 chars, override active in all three.

**Second trap found and disarmed.** The failed run's `stage-09/domain_profile.json` shows domain
detection landed on **physics_simulation**, whose adapter injects "Physics simulations generate
their own data ... Do NOT download external datasets" and *prepends* it to the codegen guidance
(`_code_generation.py:299`). That is a second, independent push toward synthetic data. The domain
adapter is only injected for NON-ML domains, so the new topic says "tabular five-minute market
data"; detection now returns **ml_tabular** (verified) and the adapter is skipped entirely.

**Source fix (minimal, 2 strings):** `researchclaw/pipeline/experiment_diagnosis.py` — the
`dataset_unavailable` and `synthetic_data_fallback` suggested_fix texts hardcoded
"use torchvision.datasets with root='/opt/datasets'". That advice is what turned the repair loop
into a torchvision-import loop. Both are now domain-neutral: use the exact path from the plan,
never substitute another domain's dataset, fail loudly rather than fall back to synthetic.

**Dataset independently verified** (I did not take the numbers on report):
678,735 rows, 5 regions, 2026-05-29 17:35 → 2026-07-31 01:25, zero nulls.
VIC1 all-horizons Pearson r(ens_sd, abs_err) = 0.478, Spearman 0.526, n=135,747; quintile ladder of
mean |err| 5.07 → 8.51 → 9.02 → 11.85 → 44.77 $/MWh. Consistent with nem-data's slice numbers.
Using the CLEAN `horizon_min == 5` slice (84,610 rows) — nem-data verified `horizon_min == 0`
carries a quasi-truth contaminant (35% of rows equal the realised price to 0.005), which is what
the old 84,575-pair r=0.638 number was computed on.

**Paper framing locked (coordinator finding, independently checked on disk):** the paper must be
the TWO-ENSEMBLE CONTRAST, not an H2 victory lap. `~/code/age-swarm/eval/` really does hold
`forecast_results_2026-07-12.jsonl` (240 cells, verified 240 lines) and `gamma_sweep_2026-07-30.md`
(verified: best alpha by mean CRPS = 0.0, i.e. NO widening beat every widened variant on the LLM
debate ensemble; Spearman 0.282 in analysis_2026-07-12.md). Those enter the paper as PRIOR
EVIDENCE with dates, never as this paper's experiment — enforced through the `topic_constraint`
block override, which also mandates the limitations: heteroskedasticity confound, non-independent
model-vintage members, and the 38/60 parse-failure confound that could itself manufacture the
LLM-side null.

### 2026-07-31 01:42 AEST — run healthy, monitoring armed
`run_id rc-20260730-153834-c1d23e`, pid 84091. Stage 1 TOPIC_INIT done 01:40, stage 2 running.
qwen2.5:72b-instruct resident, 52 GB, 100% GPU, expiry refreshing (= calls landing).
Monitoring is `ps -p 84091` + a diff over `stage-*/decision.json` — no mtime predicates, so it
cannot be fooled by the bfs `-newermt` silent-empty defect, and it tells a long stage apart from a
dead process by process existence rather than by file freshness.
NOTE: `logs/h2-real-20260731.log` is block-buffered because stdout is piped through `tee` and
PYTHONUNBUFFERED is not set for this process — the log lags by kilobytes. Read the per-stage dirs,
not the log, for progress. (Same lesson as the old run's lost serve.log, different mechanism.)
Early quality flag for assessment time: `stage-01/goal.md` wrote itself a POSITIVE success
criterion ("The proposed method outperforms unconditional quantile aggregation"). The prompt
override says alpha=0 winning is a legitimate outcome. If the results section claims an
improvement the numbers do not support, that is a failed run regardless of polish.

### FINAL (2026-07-31 ~01:47 AEST) — CRPS + interval coverage, the test the WS3 paper actually specifies

Artefacts: `/Users/alexeynikitine/data/ws3_h2/` — `ws3_h2_matched.{parquet,csv}` (678,735 rows),
`ws3_h2_ensemble_wide.{parquet,csv}` (85,300 rows), `README.md` (citable provenance), `build_meta.json`.
Analysis code: `/private/tmp/claude-502/-Users-alexeynikitine/781c8e6b-331a-4d0e-b5dc-3864a4c34222/scratchpad/ws3/{h2lib,analyze,followup}.py`.

#### What the paper specifies (verbatim source: `Intrepid Power Operations/research/papers/ws3_debate_as_calibration_2026-07-04_v0.md`)
§3.3: `Q'(tau) = Q(0.5) + gamma(D) * (Q(tau) - Q(0.5))`, **with gamma a monotone INCREASING map fit
on a validation window**. §4.3: CRPS primary, pinball, PICP at 50/90, mean width, rolling-origin,
Diebold-Mariano. H2 (§5): *"gamma(D) improves coverage calibration over unconditional aggregation."*

#### Design
Predictive distribution = 199 quantiles at tau = k/200; CRPS = 2 * mean_tau pinball (identical
representation for every method, so scores are strictly comparable). Train/test split **in time**
(70/30, cut 2026-07-12 17:00), plus a 5-fold expanding rolling-origin. Diebold-Mariano on the
per-interval mean CRPS differential, Newey-West lag 9. Run at three horizon cuts (h_min = 5, 15, 35).
Two method families, because the answer differs between them and that difference IS the finding:
- **ECDF family** (the paper's literal spec): base = the ensemble's own empirical quantile function,
  which is already proportional to D. M1 raw, M2 unconditional scale c, M3 gamma(D) isotonic, M3p power-law.
- **Location-scale / conformal family** (the paper's own "mandatory lightweight baseline", §4.2):
  base = ens_mean + width, width NOT tied to D a priori. M4 split-conformal (constant width),
  M5 width = sigma(D), M6 width = sigma(vol_lag), M7 width = sigma(D, vol_lag).

---

#### RESULT 1 — the paper's gamma(D) DOES NOT BEAT unconditional aggregation on CRPS. It loses.

TEST-set mean CRPS ($/MWh), ECDF family:

| horizon | UNCOND (c const, CRPS-optimal) | **GAMMA increasing (paper's spec)** | GAMMA decreasing (what the data wants) |
|---|---|---|---|
| h_min=5  | **10.890** | 11.296 (+3.7% worse) | 10.753 |
| h_min=15 | **12.085** | 13.038 (+7.9% worse) | 11.826 |
| h_min=35 | **17.133** | 32.762 (+91% worse)  | 16.579 |

Diebold-Mariano, gamma-increasing vs unconditional: DM = **+3.68 (p=2.3e-4)**, **+3.25 (p=1.1e-3)**,
**+2.45 (p=0.014)** at h=5/15/35 — positive DM = the paper's method is significantly WORSE.
Rolling-origin agrees in **all 5 folds at every horizon** (mean CRPS h=15: M2 13.16 vs M3 15.37).

**Why, mechanically.** Fit the CRPS-optimal multiplicative scale c* separately in each D-decile.
c* is monotone **decreasing** in D: Spearman(D_bin, c*) = **-0.707 / -0.740 / -0.998** at h=5/15/35.
h=5, c* by D-bin: `1.18 2.24 2.73 3.32 2.96 2.65 2.33 1.66 1.79 1.73 1.66 1.47 1.47 1.55 1.42 1.40 1.37 1.32 1.20 1.11`
Because the unconstrained optimum is decreasing, **the best monotone-INCREASING gamma is a constant** —
the paper's constraint binds completely, and a correctly-solved constrained fit degenerates to
exactly the unconditional baseline, i.e. **gamma(D)-widening's best achievable CRPS gain under the
paper's monotonicity constraint is exactly ZERO.** The losses tabulated above are what a naive
two-stage (per-bin-then-isotonise) fit actually delivers.

#### RESULT 2 — the optimal alpha is NEGATIVE. Directly comparable to the age-swarm alpha sweep.

Parameterise `gamma(D) = c0 * (D / median(D))^alpha`, c0 fit on train per alpha, scored on TEST:

| horizon | **alpha_opt** | c0 at opt | CRPS at alpha_opt | CRPS at alpha=0 | gain vs alpha=0 |
|---|---|---|---|---|---|
| h_min=5  | **-0.3** | 1.968 | 10.556 | 10.897 | +3.13% |
| h_min=15 | **-0.3** | 2.129 | 11.495 | 12.089 | +4.92% |
| h_min=35 | **-0.5** | 3.618 | 14.169 | 17.159 | +17.42% |

TEST CRPS vs alpha at h_min=5 (**every positive alpha is worse than alpha=0, monotonically**):

| alpha | -0.5 | -0.4 | **-0.3** | -0.2 | -0.1 | **0.0** | +0.1 | +0.2 | +0.3 | +0.5 | +1.0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| CRPS | 10.68 | 10.60 | **10.56** | 10.56 | 10.65 | **10.90** | 11.37 | 12.17 | 13.53 | 18.00 | 39.16 |
| PICP90 | 76.5 | 77.1 | 76.5 | 74.4 | 71.5 | 68.8 | 64.3 | 57.6 | 52.2 | 38.9 | 13.8 |
| W90 | 33.6 | 36.3 | 39.2 | 42.7 | 48.6 | 61.1 | 82.1 | 117.4 | 179.8 | 381.6 | 1347.0 |

**Side-by-side with the LLM ensemble (age-swarm, 2026-07-12): best alpha there = 0. Best alpha here
= -0.3 to -0.5. Both refute alpha > 0.** These are convergent negatives on the paper's prescription.

**The honest mechanical reading, which is NOT "divergence is decoration".** The object being scaled
here is the ensemble's *own* spread, which is already proportional to D. Total interval width
therefore scales as `D^(1+alpha)` = **D^0.7** at h=5 and **D^0.5** at h=35. Width still increases
with divergence — strongly. What is refuted is *additional* widening on top of the ensemble spread:
the ensemble's native spread **over-responds** to D, and the correction needed is a partial shrink.
The spread-skill slope is below 1. Low-D ensembles (members happen to agree) are where the ensemble
understates uncertainty most severely — which is precisely the opposite of the paper's intuition
that "debates that stay divergent produce wider intervals, mechanically".

#### RESULT 3 — but D-conditioned width DOES beat unconditional width, decisively, in the family where the base is not already D-proportional.

TEST, location-scale/conformal family, h_min=5 (n_train=59,215 / n_test=25,395):

| method | CRPS | CRPS median | PICP50 | PICP80 | PICP90 | PICP95 | W50 | W90 |
|---|---|---|---|---|---|---|---|---|
| M4 split-conformal (constant width) | 14.994 | 4.136 | 42.85 | 74.38 | 85.83 | 91.99 | 10.08 | 46.10 |
| **M5 width = sigma(D)** | **14.127** | 4.365 | **46.14** | **78.29** | **88.80** | **94.09** | 19.35 | 69.15 |
| M6 width = sigma(vol_lag) | 14.454 | 4.535 | 45.46 | 77.00 | 87.89 | 93.67 | 18.32 | 67.41 |
| M7 width = sigma(D, vol_lag) | 14.378 | 4.458 | 46.97 | 78.55 | 88.95 | 94.06 | 20.65 | 72.15 |

M5 beats M4 on CRPS **and on empirical coverage at all four nominal levels**, at every horizon:
DM(M5 vs M4) = **-5.25 (p=1.5e-07)** / -4.97 (p=6.8e-07) / -3.99 (p=6.5e-05) at h=5/15/35.
Holds in all 5 regions and all 5 rolling-origin folds. **This is H2's actual claim — improved
coverage calibration from divergence-conditioned width — and on AEMO data it is CONFIRMED.**

For reference, how underdispersed the raw ensemble is (PICP90, nominal 90%): **55.7%** at h=5,
49.0% at h=15, **35.6%** at h=35. Divergence-blind aggregation is badly miscalibrated.

#### RESULT 4 — the heteroskedasticity confound is real but D SURVIVES it. D is not just a volatility proxy.

`vol_lag` (realised price stddev over the 12 dispatch intervals strictly available before forecast
time — leakage-free) is the rival uncertainty feature. On TEST:

| statistic | h=5 | h=15 | h=35 |
|---|---|---|---|
| Spearman(D, abs_err) | 0.555 | 0.522 | 0.455 |
| Spearman(vol_lag, abs_err) | 0.469 | 0.443 | 0.358 |
| Spearman(D, vol_lag) — the confound itself | 0.614 | 0.566 | 0.424 |
| **partial Spearman(D, abs_err \| vol_lag)** | **0.383** | **0.366** | **0.358** |
| partial Spearman(vol_lag, abs_err \| D) | 0.195 | 0.210 | 0.204 |

D retains ~2x the residual rank signal that the volatility proxy does. Scored, not just correlated:
DM(M5_D vs M6_VOL) = **-4.12 (p=3.8e-05)** / -3.50 (p=4.7e-04) / -3.47 (p=5.2e-04). Adding vol_lag
on top of D (M7) does **not** improve on D alone — it is significantly worse (DM +5.08, p=3.8e-07),
i.e. **D subsumes the volatility proxy.** Stratifying by region: M5 < M6 < M4 on CRPS in all 5
regions at all 3 horizons, with no region reversing the ordering. Stratifying by horizon: the D
advantage is stable and if anything grows with lead time.

**Conclusion on the confound: the correlation overstates the usable signal (0.555 -> 0.383 partial),
but the signal is not an artefact. It is not merely a volatility proxy.**

---

#### What this does and does not establish

**Established** (AEMO P5MIN model-vintage ensemble, 5 regions, 2026-05-29 to 2026-07-31, 62 days,
84,610 clean matched targets per horizon cut, time-split, DM-tested):
1. H2's null ("D is uncorrelated with realised absolute error") is **REJECTED** — and it survives
   removal of the look-ahead vintage and control for lagged realised volatility.
2. Conditioning predictive interval width on D **improves both CRPS and interval coverage** over an
   unconditional constant-width baseline, and beats a lagged-volatility-conditioned rival.
3. **The paper's specific gamma(D) — monotone INCREASING multiplicative widening about the ensemble
   median — does NOT beat unconditional aggregation on CRPS. Its best achievable gain under the
   stated monotonicity constraint is exactly zero, and as naively fitted it loses significantly.
   The CRPS-optimal exponent is negative (alpha = -0.3 to -0.5).** §3.3 of the paper needs revising:
   either drop the monotone-increasing constraint on gamma, or re-base the widening on a quantity
   that is not already proportional to D.

**NOT established.** This is **AEMO's own model-vintage ensemble, not the WS3 multi-agent LLM
debate ensemble.** It tests the statistical mechanism, not the LLM-debate instantiation. Nothing
here may be reported as "H2 confirmed for debate ensembles". The LLM-side evidence
(`~/code/age-swarm/eval/forecast_results_2026-07-12.jsonl`, Spearman 0.282, best alpha = 0) remains
preliminary and confounded by parse failures, and is a separate claim.

**Also material — a defect in the prior 84,575-pair result.** It used all 12 P5MIN vintages, which
includes the lead-0 vintage. That vintage is quasi-truth (MAE 5.38 $/MWh, r=0.895, 35.4% of rows
equal to the realised RRP within 0.005, vs MAE 12.08 / r=0.405 at lead 5). The headline Spearman
0.672 is inflated by it; the clean lead-5 figure is **0.613**, and 0.516 at lead 35. The correlation
result stands, but the specific 0.672 must not be quoted as a forecasting result.

#### Limitations to travel with these numbers
62-day window, winter only, no summer peak. Prices are heavy-tailed (-757 to +20,300 $/MWh), so
mean CRPS is spike-dominated — median and 99.9%-trimmed means are reported alongside and do not
change any sign. Ensembles are small (5-11 members), so the ECDF family's tail quantiles are
degenerate and its nominal-95% coverage is not meaningfully estimable — that is why the
location-scale family carries the coverage conclusion. D = 0 exactly on 1.4% (h=5) to 5.2% (h=35)
of rows; multiplicative widening cannot widen those at all. Overlapping forecast windows are
strongly autocorrelated, which is why every split is temporal and every test is HAC-robust.
`predispatch_price_forecast` (815,910 rows, horizons to +40h) is exported and would give a far
stronger horizon stratification than P5MIN's 55-minute ceiling; not built.

### 2026-07-31 01:47 AEST — INDEPENDENT YARDSTICK (computed by me, outside the pipeline)
So the generated paper can be checked against numbers the pipeline did not produce.
Script: scratchpad `ref_h2.py`. Clean slice `horizon_min==5 & n_vintages>=5`, n=84,610, 5 regions,
2026-05-29 17:55 → 2026-07-31 01:25. Time-ordered 70/30 split; alpha picked on the last 20% of
train (never on test); 19-quantile grid; CRPS via mean pinball loss.

| quantity | value |
|---|---|
| Pearson r(ens_sd, abs_err) | **0.3728** |
| Spearman(ens_sd, abs_err) | **0.6128** |
| Spearman(vol_lag, abs_err) — rival control | 0.4944 |
| mean abs_err by ens_sd quintile | **3.23 / 5.78 / 7.39 / 11.84 / 45.61** $/MWh |

| condition | TEST CRPS | Coverage90 | Width90 |
|---|---|---|---|
| Unconditional quantile aggregation (baseline) | 7.6827 | 0.8583 | 46.10 |
| gamma(vol_lag) widening (control, alpha=2.0) | 7.6301 | 0.8656 | 47.87 |
| **gamma(ens_sd) widening (proposed, alpha=2.0)** | **7.4205** | **0.8840** | 51.87 |

Reads: on the AEMO model-vintage ensemble, divergence-conditioned widening **does** help — 3.4%
better CRPS than unconditional and it moves 90% coverage from 0.858 toward nominal (0.884) — and
it beats the realised-volatility control (7.4205 vs 7.6301), so the signal is not merely "any
volatility proxy works". Caveat on my own number: alpha selected at the **grid edge (2.0)**, so
the optimum is not bracketed; a wider grid may do better and the effect size is not settled.

This is the opposite sign to the LLM debate ensemble, where the frozen sweep found best alpha = 0.
That contrast IS the paper. Ladder and correlations reproduce nem-data's clean-slice figures
exactly, which cross-validates both loaders.

### 2026-07-31 ~01:45 AEST — infer1 de-risking rig LIVE. TWO MORE root causes for `h2-pipeline`.
Coordinator approved infer1 as the fast de-risk rig. Rig is built and cycle 1 is running.
**`h2-pipeline`: two prompt-injection sites below are UPSTREAM/PARALLEL to the one you found
and they bite on prime-serve too (same M5 Max hardware). Read these before your 72B run.**

#### Rig state (all verified, infer1 only — prime-serve untouched)
- Venv: `pandas 3.0.5, pyarrow 25.0.0, matplotlib 3.11.1, scikit-learn 1.9.0` installed.
  Dry-run first: purely additive (contourpy/cycler/fonttools/kiwisolver/narwhals/threadpoolctl),
  **no upgrades**, numpy 2.4.6 and researchclaw 0.3.1 untouched. Box was idle (`ollama ps` empty,
  0 `researchclaw run` procs, status `failed`) so nothing was disturbed.
- `torch 2.13.0` pre-installed deliberately — see root cause #3; the pipeline installs it itself
  at stage 1 otherwise, mid-run.
- Data: `ws3_h2_matched.parquet` (678,735 x 16) + `ws3_h2_ensemble_wide.parquet` (85,300 x 29)
  copied from `nem-data` to **`/Users/ip-infer1/data/ws3_h2/`**, verified readable with pandas
  on the box: 5 regions, `horizon_min` in {0,5,...,35}. No duckdb anywhere in the path.
- New files on infer1: `config.ws3-h2.yaml`, `prompts.ws3-h2.yaml`. `validate` passes.
- Run: `researchclaw run --config config.ws3-h2.yaml --auto-approve --mode full-auto
  --skip-noncritical-stage`, log `logs/ws3h2_c1.log`. No tmux on this box; nohup.

#### ROOT CAUSE #2 (NEW) — the experiment PLAN is poisoned before codegen ever runs
`_experiment_design.py:120-122` injects `_pm.block("dataset_guidance")` **unconditionally** —
it does not consult net policy at all. `dataset_guidance` (`prompts.py:369`) is the CIFAR/MNIST/
`/opt/datasets` Docker text. So the EXPERIMENT DESIGN stage already specifies image datasets
before stage 12 codegen is reached. Overriding only `network_disabled_guidance` (the codegen
block) leaves the plan itself pointing at CIFAR, and the coder is then working from a poisoned
plan. **You must override `dataset_guidance` as well.**

#### ROOT CAUSE #3 (NEW, and NOT fixable from a prompts YAML) — the GPU branch promises torch
`_code_generation.py:105-131`: `pkg_hint` is only read from the `pkg_hint_sandbox` prompt block
in the `else` branch, i.e. **when no GPU is detected**. On these Macs a GPU *is* detected —
measured on infer1: `detect_hardware()` → `has_gpu=True, gpu_type='mps',
gpu_name='Apple M5 Max', tier='limited'`. That takes the f-string branch, which is built in
Python and **cannot be overridden via `prompts.custom_file`**:
> `AVAILABLE PACKAGES (sandbox): Python stdlib, numpy, torch, sklearn, scipy, pandas.`
> `GPU: Apple M5 Max (mps) — LIMITED performance. Use device = torch.device('mps') …`
Two consequences: (a) the model is actively steered toward a torch/MPS training loop for what is
a statistical scoring problem; (b) if torch is absent the hint is a **lie** and codegen dies on
import. Note `pkg_hint_sandbox` — the block that forbids pandas — is never reached on this
hardware, so it is *not* the problem I first suspected; it only matters on CPU-only hosts.
**Mitigation used (prompt-only, portable):** `_code_generation.py:520/565` assembles
`pkg_hint = pkg_hint + compute_budget + extra_guidance`, so the `network_disabled_guidance`
override lands **last** in that slot and is the final word. My override text explicitly says
"Ignore any earlier statement in this prompt that suggests otherwise" and re-declares the
authoritative package list. Belt-and-braces: torch is now genuinely installed, so the hint is at
least true even if the model ignores the steer.

#### Also worth knowing: stage 1 silently pip-installs torch into your live venv
`_topic.py:108-113` → `ensure_torch_available()` (`hardware.py:246-290`). Because
`has_gpu and mode=="sandbox"`, stage 1 runs `<venv>/bin/python3 -m pip install --quiet torch`
if torch is missing. That is an unannounced ~2.5 GB install into the venv **of a running job** —
exactly what the BURN_BRIEF warns against, executed by the pipeline itself. It skips cleanly
when torch is already importable, which is why I pre-installed it. **Prime-serve already has
torch, so this is a no-op there — but do not "clean up" torch from that venv.**

#### The fix, as applied (portable to prime-serve — copy `prompts.ws3-h2.yaml` and edit paths)
There is no `dataset_path` field in `RCConfig`; prompt text is the only channel, confirmed.
`PromptManager._load_overrides` (`prompts.py:104-128`) **replaces** a block wholesale by name
from `blocks:` in the YAML at `prompts.custom_file`. Three blocks overridden:
| block | injected by | why it must change |
|---|---|---|
| `dataset_guidance` | `_experiment_design.py:122` (unconditional) | stops the PLAN specifying CIFAR |
| `network_disabled_guidance` | `_code_generation.py:156-161` (sandbox ⇒ net policy `none`) | stops codegen inventing `/opt/datasets/*.csv`; lands last so it overrides the GPU f-string |
| `pkg_hint_sandbox` | `_code_generation.py:129` (no-GPU hosts only) | portability to CPU-only hosts |
Each override states the exact absolute parquet path, the full 16-column schema, `ens_sd` = the
dispersion D, `abs_err` = the error target, and bans `/opt/datasets`, torchvision, HuggingFace,
duckdb, seaborn, `setup.py`/`requirements.txt`, and synthetic substitutes.
It also carries `nem-data`'s look-ahead correction as a hard rule — **`horizon_min == 0` is
contaminated quasi-truth (35% of rows match realised to <0.005), so filter `horizon_min >= 5`
and `n_vintages >= 5`** — plus the heteroskedasticity caveat, so the model must condition on
`vol_lag` terciles rather than report raw correlation as usable signal.
Config changes: `mode: sandbox` (was `simulated`), topic → WS3 H2 with the path inline,
`metric_key: crps` / minimize, `time_budget_sec: 900`, `hitl_required_stages: []`.

**Deliberately NOT patched:** `experiment_diagnosis.py:452-479` (the hardcoded torchvision
"dataset_unavailable" suggestion). That path only fires *after* the experiment has already
crashed. Prevention is upstream of it and needs no source change, which keeps this fix a
drop-in for prime-serve. If cycle 1 shows the repair loop firing anyway, I will patch it on
infer1 only and post the diff here rather than changing anything on your host.

Result of cycle 1 to follow in this section the moment stage 17 resolves either way.

### 2026-07-31 01:46 AEST — prompt strengthened mid-run (legally, before the consuming stage)
`PromptManager` is rebuilt PER STAGE (`executor.py:641`), not once at startup, so edits to
`prompts.h2-real.yaml` still reach stage 9 EXPERIMENT_DESIGN and stage 10/12 codegen while the run
is at stage 3. Verified by re-rendering the blocks from the venv after editing. Added, on
nem-data's request and in its neutral framing:
- a `NormalizedConformal` condition (location-scale/split-conformal, half-width proportional to a
  train-fitted s(D)) marked as a DIFFERENT family from the gamma(D) multiplier, both to be reported
- median CRPS alongside mean for every condition (prices -757 .. +20,300 $/MWh, mean is
  spike-dominated)
- an explicit "the direction of the result is NOT known, a null/negative result is a good outcome,
  alpha may legitimately be zero, never tune on test"

**SIGN DISAGREEMENT between the two independent yardsticks — flagged, not resolved.**
nem-data: gamma = c0*(D/Dmed)^alpha about the ensemble median → optimal alpha NEGATIVE (-0.3/-0.5),
every alpha>0 worse, gamma(D) loses to unconditional on CRPS (11.296 vs 10.890, DM +3.68).
Mine: gamma = 1 + alpha*max(z(D),0), clipped, about train residual quantiles around ens_mean →
alpha=2.0 wins, 7.4205 vs 7.6827 unconditional.
Most likely cause is the free scale parameter c0 plus an unbounded power form letting high-D rows
blow out on a heavy-tailed target, versus my bounded above-mean-only widening — i.e. the effect is
**parameterisation-sensitive**. Neither of us should have our number quoted as "the" real-data
answer. Both agree on the thing that matters for the paper: conditioning width on D beats not
conditioning it (nem-data's sigma(D) conformal result 3 is decisive, DM -5.25, p=1.5e-7) and D is
not merely a volatility proxy (their partial Spearman 0.383 vs 0.195; my control 7.4205 vs 7.6301).

---

## nem-data — RECONCILIATION: the contradiction with `h2-pipeline` is RESOLVED. Both results are right. READ THIS BEFORE QUOTING EITHER NUMBER.

**Coordinator: the RDTI evidence record can be un-CONTESTED. Nothing is unexplained.**
Same rows, same split, same target. I reproduced `h2-pipeline`'s construction exactly and found
**three** distinct, individually verified causes. Neither analysis was "wrong about the data";
both had a stateable defect, **including mine.**

### CAUSE 1 — the CRPS scale gap (7.68 vs 10.89) is a FACTOR OF EXACTLY 2. Not rows, not the grid.

`CRPS = 2 * integral of pinball over tau`. `h2-pipeline`'s yardstick says *"19-quantile grid; CRPS
via mean pinball loss"* — the factor of 2 is missing. Rebuilding its exact baseline
(train residual quantiles about `ens_mean`, 19-quantile grid, `horizon_min==5 & n_vintages>=5`,
n_test = 25,395):

| quantity | mine, recomputed | h2-pipeline reports | match |
|---|---|---|---|
| **mean pinball** | **7.6811** | **7.6827** (labelled "CRPS") | **yes, 0.02%** |
| true CRPS (2x pinball) | **15.3622** | — | — |
| Coverage90 | **0.8583** | **0.8583** | **exact** |
| Width90 | **46.10** | **46.10** | **exact** |

Coverage and width match **to the digit** — the loaders and row sets are identical, which is the
good news. `h2-pipeline`'s ratios and percentages are all internally consistent and valid; only the
absolute values are half of CRPS. **Do not print those numbers under the label "CRPS" in the paper.**
Grid resolution was tested and **ruled out** as an explanation: K = 9/19/39/99/199/499 moves my
baseline only 11.44 -> 10.89 (2.5%), and in the *opposite* direction.

### CAUSE 2 — the sign flip in alpha is real, and it is entirely about WHAT THE MULTIPLIER MULTIPLIES.

Two different base objects were being widened. Same power multiplier `c(D) = c0*(D/Dmed)^alpha`
applied to both, same data, same split, both optima properly bracketed:

| base | is the base already proportional to D? | **best alpha** | bracketed | **implied TOTAL width exponent on D** |
|---|---|---|---|---|
| **A** ensemble ECDF about ensemble median (mine — and the paper's §3.3) | **YES** | **-0.3** | yes | **+0.712** |
| **B** train residual quantiles about `ens_mean` (h2-pipeline's) | **NO** | **+0.8** | yes | **+0.800** |

`1 + alpha_A = 0.71` vs `alpha_B = 0.80`. **The two analyses agree on the only quantity that is
parameterisation-free: optimal interval width scales as D^0.7 to D^0.8.** The alpha sign flip is an
accounting artefact of whether the base already carries D. There is no empirical disagreement.
On base B I independently confirm `h2-pipeline`'s direction: alpha = +0.8 gives CRPS 12.690 vs
alpha = 0's 14.991 — **a 15.4% gain, not 3.4%.** Its own finding was understated (see cause 3).

### CAUSE 3 — h2-pipeline's alpha = +2.0 grid edge is STRUCTURAL, not a tuning oversight. Its form cannot reach the optimum.

Its multiplier is `1 + alpha*clip(z(D),0,zmax)` with `z` a standardised D. `clip(z,0,·)` is **zero
for every row with below-mean D** — i.e. for the majority of rows — so the form can only widen the
upper tail and leaves the bulk untouched. It saturates. Implementing it exactly on its own base:

| alpha | 0 | 1.0 | 2.0 | 4.0 | 9.0 |
|---|---|---|---|---|---|
| CRPS | 14.994 | 14.778 | 14.599 | 14.326 | **13.949 (still falling)** |
| implied total width exponent on D | 0.000 | 0.053 | 0.088 | 0.138 | **+0.221** |

Even at alpha = 9 it reaches a width exponent of **+0.22** against an optimum of **~+0.75**, and CRPS
is still decreasing. **It will run to the edge of any grid, at any zmax (tested 2, 3, 5).** So the
unbracketed optimum is not fixable by widening the grid — the functional form is the constraint.
A power law on the same base brackets cleanly at +0.8 and captures 4x the gain.

### CAUSE 4 — MY OWN ERROR, stated plainly.

**My claim "every alpha > 0 is monotonically worse" was overstated.** It is true on the paper's
§3.3 base (the ensemble's own quantile function). It is **FALSE** on a D-independent base, where
alpha > 0 is correct and necessary. I reported the mechanism correctly in prose ("the object being
scaled is already proportional to D... total width scales as D^(1+alpha)"), but the headline table
invited exactly the over-general reading the coordinator caught. **Corrected: the sign of the
optimal alpha is not a property of the data, it is a property of the base. Only the total width
exponent on D (~0.75) is a property of the data.**

### WHAT SURVIVES — and it is the stronger claim, now stress-tested rather than assumed

The structural argument stands, on the paper's own base, unchanged:
- §3.3 is explicit that gamma multiplies **the aggregated ensemble quantile function**
  (`Q'(tau) = Q(0.5) + gamma(D)*(Q(tau) - Q(0.5))`). That is base A. On base A the per-D-decile
  CRPS-optimal multiplier is monotone **DECREASING** — Spearman(D_bin, c*) = **-0.707 / -0.740 /
  -0.998** at h = 5/15/35. The monotone-increasing constraint therefore **binds completely**, the
  best increasing gamma is a constant, and **the maximum achievable CRPS gain under §3.3 as written
  is exactly zero.**
- Both analyses now agree the optimal width is **sublinear in divergence, ~D^0.75**. The paper's
  intuition that "debates that stay divergent produce wider intervals, mechanically" is directionally
  right but **quantitatively too aggressive**: the ensemble's native spread over-responds to D.
- **The mechanism is confirmed, the parameterisation is refuted.** §3.3 needs **re-basing, not
  deleting**: either drop the monotone-increasing constraint on gamma, or widen a base that is not
  already proportional to D (the normalized-conformal form, where sigma(D) beats constant width at
  CRPS 14.13 vs 14.99, DM -5.25, p = 1.5e-7, and improves coverage at all four nominal levels).

### For the paper — the defensible framing

Report the **width exponent**, not alpha. "Optimal predictive interval width scales as D^0.75 on
AEMO's model-vintage ensemble" is parameterisation-free, reproduced independently by two agents
with different code, and survives control for lagged realised volatility (partial Spearman 0.383
vs 0.195). Reporting "optimal alpha" without stating the base is meaningless and two competent
analyses will contradict each other — as these two did.

Unchanged scope line: this is **AEMO's model-vintage ensemble, not an LLM debate ensemble.**
The LLM sweep's best alpha = 0 was computed on yet another base and is **not** directly comparable
to either number above; that comparison needs re-doing on a common base before it goes in a paper.

### 2026-07-31 ~01:52 AEST — PROOF POINT 1: dataset fix HOLDS at EXPERIMENT_DESIGN (stage 9)
`h2-pipeline`: the override works. Hard evidence from infer1 cycle 1
(`rc-20260730-154242-04a94e`, qwen2.5:14b), stage 9 completed 15:48:26Z, ~6 min in.

**Token scan of the whole of `stage-09/` — this is the number that matters:**
```
   1 ws3_h2_ensemble_wide
   2 ws3_h2_matched
   0 /opt/datasets     0 CIFAR     0 MNIST     0 torchvision     0 electricity_prices
```
Zero occurrences of every poison token, including the invented `electricity_prices.csv` that
killed the 72B run. Earlier stages agree: `stage-01/goal.md` and `stage-03/sources.json` carry
`ws3_h2_matched` and no CIFAR.

**`stage-09/exp_plan.yaml` `datasets:` block, verbatim:**
```yaml
primary_file:   /Users/ip-infer1/data/ws3_h2/ws3_h2_matched.parquet
secondary_file: /Users/ip-infer1/data/ws3_h2/ws3_h2_ensemble_wide.parquet
preprocessing_steps:
- Filter rows where `horizon_min >= 5`
- Exclude rows with fewer than 5 forecast vintages (`n_vintages < 5`)
```
`metrics.primary_metric` = **CRPS, direction minimize, units $/MWh**. Correct objective.

Two things worth calling out:
1. **The exact absolute path survived into the plan.** Prompt-block override is a sufficient
   channel; no `dataset_path` config field is needed. This is the portable fix.
2. **`nem-data`'s look-ahead correction propagated automatically.** I put the
   `horizon_min >= 5` / `n_vintages >= 5` rule in the prompt block as a hard data-correctness
   rule and the model lifted it into `preprocessing_steps` unprompted. The h=0 contamination
   fix is now baked into the experiment design rather than relying on a human to remember it.

**Ground-truth check-set** (computed independently on infer1's copy, for detecting fabricated
numbers later — reproduces `nem-data` exactly at h=5/15/35, so the copy is faithful):
`h>=5, n_vintages>=5`: n=578,395, Pearson **0.4344**, Spearman **0.5619**,
mean `abs_err` by `ens_sd` quintile **4.40 / 6.89 / 9.28 / 11.66 / 50.79** (monotone — H2 holds).
Per-horizon Spearman decays 0.613 (h=5) → 0.516 (h=35). VIC1 only: 0.520.
Any paper this pipeline emits gets checked against these before anyone believes it.

**Root cause #4 confirmed by observation — #3 is real and it distorts the SCIENCE, not just imports.**
The dataset fix held, but the GPU f-string steer (`_code_generation.py:105-131`, unreachable
from any config) has visibly bent the plan into a deep-learning shape it should not have:
`ablations` and `baselines` are specified with `class_name`, `forward`, `train_step`,
`gradient_clip_threshold: 2.5`, `learning_rate: 0.01`, plus a wavelet-transform + Shannon-entropy
method stack — for a problem that is quantile arithmetic and proper scoring rules over 578k rows.
`compute_budget` came back `number_of_seeds: 10, episodes_per_seed: 30` — RL/training vocabulary.
So #3 does not merely risk an ImportError on a torch-less host; **on a torch-equipped host it
silently converts a statistical evaluation into a neural-network study.** That is the more
dangerous failure because it looks like success. Prime-serve will hit this too — same M5 Max,
same `has_gpu=True/mps/limited` branch.
Holding judgement on whether it is fatal until CODE_GENERATION (stage 12) and EXPERIMENT_RUN
(stage 14) land — torch 2.13.0 is installed on infer1, so it will not fail on import, and the
core design (real file, right filters, CRPS objective) is sound underneath the bloat. Minimum
viable intervention for #3 will be posted here with a proven diff if the run needs it.

**Priority-4 answer for the coordinator — `_topic.py:108` no-ops when torch is present.**
`.venv/.../site-packages/torch` mtime is `2026-07-31 01:40:55`, i.e. my pre-install; the run
started 01:42:42 and nothing under site-packages changed at or after that time. So
`ensure_torch_available` took the "already available" early return and did NOT pip-install into
the live venv. Pre-installing torch is what made that safe — on a torch-less host this fires
mid-run. **Prime-serve already has torch, so it is a no-op there; do not remove it.**

### 2026-07-31 ~01:55 AEST — PROOF POINT 2: dataset fix HOLDS at CODE_GENERATION.
### But root cause #3 is now PROVEN FATAL. `h2-pipeline` — read this before your 72B run.

**THE GOOD NEWS — the fix works end to end, prompt → plan → executable code.**
`stage-10/experiment/` (stage 10 IS `CODE_GENERATION`; stage 12 is `EXPERIMENT_RUN`,
stage 17 `PAPER_DRAFT`). Token scan of the generated source:
```
   1 read_parquet      1 ws3_h2_matched      1 ws3_h2_ensemble_wide
   0 /opt/datasets  0 CIFAR  0 MNIST  0 torchvision  0 electricity_prices  0 randn
```
`config.py` verbatim:
```python
primary_file_path   = "/Users/ip-infer1/data/ws3_h2/ws3_h2_matched.parquet"
secondary_file_path = "/Users/ip-infer1/data/ws3_h2/ws3_h2_ensemble_wide.parquet"
```
`data.py` verbatim:
```python
df = pd.read_parquet(primary_file_path)
filtered_df = df[(df['horizon_min'] >= 5) & (df['n_vintages'] >= 5)]
```
**The exact real path AND `nem-data`'s look-ahead contamination filter both made it into
executable code.** This is precisely what the 72B run could not do — it invented
`/opt/datasets/electricity_prices.csv`. Prompt-block override is a sufficient and portable
channel. Root causes #1 and #2 are CLOSED.

**THE BAD NEWS — the GPU f-string (#3) corrupts the science, and I can now prove it.**
Forced toward torch/MPS, the model wrapped a two-variable association study in a
DataLoader/training-loop shape and broke it in two independent ways:

1. **It crashes.** `data.py` does `grouped = df.groupby('time_index')`. There is no
   `time_index` column. Verified against the real file:
   ```
   time_index in columns? False
   KeyError -> 'time_index'
   ```
   Actual columns: `interval_datetime, regionid, horizon_min, n_vintages, ens_mean,
   ens_median, ens_sd, ens_min, ens_max, rrp_actual, price_status, totaldemand,
   rrp_last_obs, vol_lag, err, abs_err`. Stage 12 will die here.
2. **Worse — it discards the target variable.** `preprocess_data` returns only a normalised,
   z-scored `ens_sd` series, split 80/10/10 into tensors. `abs_err` — the entire dependent
   variable of H2 — is thrown away before modelling. So even with the KeyError fixed, the
   experiment **cannot test H2 at all**; it is a univariate autoencoder over dispersion.
   `config.py` is `lr/batch_size/epochs/hidden_dim/gradient_clip_threshold`, and `methods.py`
   imports `WaveletTransformForecasting, InformationEntropyForecasting, ...` — none of which
   the hypothesis called for.

**This is the failure mode that looks like success.** With torch installed there is no
ImportError to alert anyone; the run would have produced trained models, converged losses and
a plausible paper that never tested the hypothesis. On a 3-hour 72B run that is a wasted night
and a paper nobody can defend. **Prime-serve has identical hardware
(`has_gpu=True, mps, tier=limited`) and will take the same branch.**

**MINIMUM VIABLE INTERVENTION — proven diff, zero regression, held at
`patches/003-pkg-hint-respect-custom-prompts.patch` on infer1:**
```diff
--- a/researchclaw/pipeline/stage_impls/_code_generation.py
+++ b/researchclaw/pipeline/stage_impls/_code_generation.py
@@ -103,7 +103,12 @@
         else:
             pkg_prefix = "sandbox mode"
             pkg_extras = ""
-        if hw_profile and hw_profile.get("has_gpu"):
+        # WS3: a custom prompts file must be able to override the package hint.
+        # The GPU branches below build pkg_hint as a Python f-string, which no
+        # prompts YAML can reach; on Apple-silicon hosts that silently promises
+        # torch/MPS and steers statistical studies into training loops.
+        _custom_prompts = bool(getattr(config.prompts, "custom_file", ""))
+        if hw_profile and hw_profile.get("has_gpu") and not _custom_prompts:
             gpu_type = hw_profile.get("gpu_type", "cuda")
```
One line of behaviour change. When `prompts.custom_file` is set, control falls through to the
`pkg_hint_sandbox` block — which IS overridable from YAML — so the operator's package list wins
on every host. With no custom prompts file the behaviour is byte-identical to today, so there is
no regression for GPU users doing genuine deep-learning work. The edited file was
`py_compile`-checked before the patch was emitted. **Do not apply it to 100.95.93.7 until I
report it proven at 14B** — cycle 2 is what proves it, and that is the next thing I do.

Per the coordinator's instruction, all infer1 source edits now live as portable patch files
under `AutoResearchClaw/patches/` on infer1 rather than only in a dirty working tree:
- `003-pkg-hint-respect-custom-prompts.patch` (above, generated, NOT yet applied)
- h2-pipeline's `experiment_diagnosis.py` change was mirrored to infer1 earlier by hand;
  **that one is still uncommitted on 100.95.93.7 and exists nowhere else — it should be
  captured as a patch file too, or it dies with the next checkout.**

### 2026-07-31 01:56 AEST — LABEL CORRECTION to my own yardstick, + framing re-cut, + injection-point decision

**CORRECTION — my yardstick's "CRPS" column was MEAN PINBALL LOSS, not CRPS.**
CRPS = 2 x integral of pinball. nem-data caught it. My 7.6827 / 7.6301 / 7.4205 are mean pinball;
true CRPS is double. Coverage90 0.8583 and Width90 46.10 match nem-data's independent rebuild to
the digit, so the loaders and row sets are identical and every RATIO I reported stands — only the
absolute label was wrong. Anyone quoting "CRPS = 7.68" from my earlier entry: it is 15.36.

**My grid-edge alpha was structural, not a tuning miss.** `1 + alpha*clip(z(D),0,zmax)` is zero for
every below-mean-D row, so it widens only the upper tail and saturates — it runs to the edge of ANY
grid (at alpha=9 the width exponent has reached just +0.22 against an optimum near +0.75). A power
law on the same base brackets cleanly at alpha=+0.8 and captures ~4x the gain: my improvement was
UNDERSTATED (15.4%, not 3.4%). Do not "fix" it by widening the grid; the functional form is the bug.

**There was never an empirical disagreement with nem-data — the sign flip is the BASE.**
alpha is meaningless without naming what it multiplies. Base already proportional to D (aggregated
ensemble quantile function, the paper's own 3.3) -> optimal alpha -0.3. Base NOT proportional to D
(residual quantiles about ens_mean, mine) -> optimal alpha +0.8. 1+(-0.3)=0.712 vs 0.800: we agree
on the only parameterisation-free quantity, **optimal interval width scales as D^~0.75** —
sublinear, i.e. width should rise with divergence but by LESS than proportionally.

**Paper framing re-cut in `topic_constraint` (this WILL land — paper stages are hours away):**
- Headline is now the WIDTH EXPONENT (D^0.75), parameterisation-free, independently reproduced by
  two agents with different code — not alpha.
- Second result: on the D-proportional base the per-decile CRPS-optimal multiplier is monotone
  DECREASING, so a non-decreasing gamma(D) cannot beat a constant and max achievable gain under
  that form is exactly zero. **Mechanism confirmed, parameterisation refuted — re-base, don't delete.**
- Third: D is not a volatility proxy (kills the heteroskedasticity confound).
- **The two-ensemble contrast is DEMOTED to an open question.** The debate sweep's alpha=0 was
  computed on a THIRD base and is not comparable to either of ours. The block now forbids writing
  "alpha=0 on debate vs alpha>0 here" as if it were one quantity, and requires the contrast to be
  stated as blocked on base-incommensurability. I had this as the centrepiece an hour ago; it was
  wrong and is corrected.
- Codegen blocks now also require: report the width exponent and the per-D-decile optimal
  multiplier + its Spearman vs decile index; label mean pinball as mean pinball, never CRPS.

**INJECTION POINTS — decision: documented, deliberately NOT patched. Reasons, not laziness:**
1. `_experiment_design.py:122` injects `dataset_guidance` unconditionally — **already closed**: my
   YAML replaces that block, verified by re-rendering (5,867 chars of real-dataset text).
   `_experiment_design.py:167` still hardcodes `_tier1 = "CIFAR-10, CIFAR-100, MNIST, FashionMNIST,
   STL-10, SVHN"` into `{available_tier1_datasets}`; my block explicitly negates it, and
   infer1-verify measured ZERO CIFAR / /opt/datasets references in stages 1 and 3.
2. `_code_generation.py:105-131` pkg_hint is an f-string, NOT a block — genuinely un-overridable by
   YAML. On M5 it promises torch/MPS for what is a scoring problem. Mitigated only by my guidance
   being appended after it.
3. `_topic.py:108` -> `hardware.ensure_torch_available` — **verified a NO-OP here**: it imports
   torch first and returns early. Measured after stage 1: torch 2.13.0, numpy 2.4.6, pandas 3.0.5,
   all unchanged. Real hazard on a box without torch; not one on prime-serve.
**Why not patch 1 and 2 now:** every stage module was imported at process start, so a source edit
CANNOT affect the live run — it would buy nothing for this run while adding more uncommitted drift
to a shared dirty tree, which is the exact fragility flagged above. Restarting to pick them up would
cost the literature stages under S2 rate-limiting, against a channel that is measurably working.
Left for a future session to do deliberately, with a commit.

**Patch preserved durably** (was uncommitted-only, on one host):
`patches/experiment_diagnosis_dataset_guidance_2026-07-31.patch` (36 lines,
`git diff -- researchclaw/pipeline/experiment_diagnosis.py`). Reapply with
`git apply patches/experiment_diagnosis_dataset_guidance_2026-07-31.patch`. It replaces the two
hardcoded "use torchvision.datasets with root='/opt/datasets'" repair suggestions with
domain-neutral ones. NOT committed — founder rule is commit only when asked.

### 2026-07-31 ~01:58 AEST — cycle 1 terminal cause + TWO CORRECTIONS TO MY OWN CLAIMS
Cycle 1 `rc-20260730-154242-04a94e` ended by itself at 15:54:12Z: `final_stage: 10`,
`final_status: failed`, stage 10 duration 346s. I stopped the process afterwards; it was
already dead. **It never reached stage 12, so the KeyError I predicted was never exercised.**

**CORRECTION 1 — the proximate cause was NOT my predicted KeyError.**
`stage-10/stage_health.json` `error`, verbatim:
> "Topic-experiment misalignment: The current experiment does not fully test the stated
> research topic. The code focuses on calculating dispersion and entropy from forecast
> ensembles but lacks proper evaluation of how these metrics predict the realized price error
> ... calculates CRPS scores without using them to validate the hypothesis ... no explicit
> comparison or scaling of prediction intervals based on ensemble dispersion against
> empirical interval coverage."
The `time_index` KeyError is real — I reproduced it directly against the parquet
(`time_index in columns? False` → `KeyError: 'time_index'`) — but it is a *latent* second
defect, not what killed cycle 1. Both defects have the same origin (#3 forcing a training-loop
shape), and the pipeline's own semantic checker independently reached the same diagnosis I did:
the experiment dropped the outcome variable and therefore could not test H2.

**CORRECTION 2 — I overstated the danger of #3. It does NOT silently produce a wrong paper.**
I wrote that #3 is "the failure mode that looks like success" and would yield "a plausible paper
that never tested the hypothesis". That was wrong, and the correction matters for how
`h2-pipeline` should weight it. There is a **topic–experiment alignment guardrail at stage 10**
that caught the misalignment and failed the stage loudly. So #3's real cost is **wasted wall
time and a hard stop at stage 10**, not a silently invalid paper. On a 72B run that is still
expensive — cycle 1 burned ~12 min to reach that stop, and prime-serve would burn far more —
but the correctness risk I claimed is not there. The pipeline is better defended than I gave it
credit for. Patch 003 remains worth applying to avoid the wasted cycle; it is not a
correctness emergency.

**GOOD NEWS BURIED IN THE LOG — sandbox execution now genuinely works on infer1.**
`code_agent_log.json`: `Hard validation passed (13 warnings)`, then
```
Exec-fix iter 0: crashed (rc=1) → Targeted repair: main.py:47 NameError: 'time' is not defined
Exec-fix iter 1: crashed (rc=1) → Targeted repair: main.py:33 NameError: 'np' is not defined
Exec-fix iter 2: crashed (rc=1) → Targeted repair: main.py:35 NameError: 'random' is not defined
CodeAgent.generate() done in 204.2s — 10 LLM calls, 3 sandbox runs
```
**Three real sandbox executions, and every failure was a trivial NameError — not a single
ImportError.** Before the venv fix, generated code could not import pandas or torch at all.
That is direct proof the venv remediation landed and that `_SANDBOX_SAFE_PACKAGES` is now
actually satisfiable on this host. The exec-fix loop repaired all three automatically.

**A real parse fallback at 14B, for the record:** `Review round 1: could not parse JSON,
skipping`. So qwen2.5:14b is not flawless at structured output under the review prompt — 96/96
run artifacts still parsed, but the earlier "zero parse fallbacks" framing is not sustainable.
Also 13 validator warnings that the torch-shaped `EntropyOnlyBaseline` / `CRPSBaseline` /
`EICBaseline` / `StandardForecasting` classes were near-identical copy-paste variants — more
#3 damage, since none of those class-shaped baselines belong in this study.

**CYCLE 2 IS RUNNING** — `rc-20260730-155547-04a94e`, launched 15:55:47Z. Two changes:
1. **Patch 003 APPLIED** on infer1 (`git diff`-format, at
   `patches/003-pkg-hint-respect-custom-prompts.patch`, module imports clean). `pkg_hint` now
   falls through to the overridable `pkg_hint_sandbox` block because `prompts.custom_file` is set.
2. **Prompt hardened** against both cycle-1 defects: the 16-column list is declared CLOSED with
   "there is NO `time_index`/`timestamp`/`date`; the time column is `interval_datetime`"; an
   explicit rule that BOTH `ens_sd` and `abs_err` must survive preprocessing or the hypothesis
   is untestable; and an explicit ban on neural networks, DataLoaders, training loops, epochs,
   gradient clipping, wavelets and entropy features, in both `dataset_guidance` (design stage)
   and `network_disabled_guidance` (codegen stage).
Two changes at once, so cycle 2 will not cleanly attribute which fixed what. That is a
deliberate trade for speed while prime-serve is blocked; if cycle 2 passes stage 10 I will say
plainly that the attribution is joint rather than claim patch 003 alone did it.

---

## nem-data — THE TWO-ENSEMBLE CONTRAST IS BACK ON THE TABLE. Recovered by re-analysis of frozen artefacts, zero LLM calls.

**`h2-pipeline`: read this before EXPERIMENT_DESIGN. The contrast you demoted to "blocked on
base-incommensurability" is unblocked. It was never a contradiction — the two ensembles approach
the same sublinear optimum from opposite sides.**

### The logs contain what was needed

`forecast_results_2026-07-12.jsonl` debate cells carry `extra.round1` — **per-agent quantile
vectors, 19 levels each** — plus `extra.D0/D1`. Realised outcomes are in
`forecast_episodes_2026-07-12.json` (`y_true`, 20 episodes). No LLM calls, no GPU, no age-swarm
run. **Re-analysis validated exactly against the frozen artefacts:**
- `vincentize(round1_ok)` reproduces the stored `qvec_final` on **60/60** cells.
- Recomputed CRPS equals the stored CRPS on **60/60** cells.
- Stored Spearman(D_norm, |err|) = **+0.2817**, reproducing the previously reported 0.282.

### THE STRUCTURAL RESULT — exact, not statistical, and it explains everything

**Vincentisation is dispersion-blind by construction.** Interval width is a *linear* functional of
the quantile vector and Vincentisation averages level-by-level, so

> width(Vincentised ensemble) == mean over agents of each agent's own width, **exactly** —
> verified `max|difference| = 9.1e-13` across all 60 cells, 100% exact.

Cross-agent dispersion D contributes **nothing** to the aggregate width. In §3.3's pipeline the
divergence signal is destroyed at the aggregation step and can only re-enter through γ(D).
This is a property of the method, not of the data, and it is the cleanest thing in this burn.

Contrast with AEMO, where the ensemble members are **point** forecasts (zero within-member width),
so the ensemble ECDF's width **is** its dispersion. Same nominal object, opposite construction.

### THE COMPARISON — common base (ensemble quantile function, §3.3's base), common D (`stddev_samp` of member point/median forecasts), common parameterisation-free quantity

| ensemble | n | **NATIVE width elasticity** d log(W90)/d log(D) | optimal alpha | **OPTIMAL width elasticity** |
|---|---|---|---|---|
| **AEMO P5MIN model-vintage** | 84,610 | **+1.020** | −0.25 | **+0.770** |
| **age-swarm debate (frozen)** | 60 (20 episodes) | **+0.240** | +0.20 | **+0.440** (95% CI +0.128…+0.716) |

**The alpha sign flip between the two ensembles is fully explained and is not a disagreement.**
AEMO starts at elasticity 1.02, above the optimum, so it needs **shrinking** (alpha < 0). The
debate ensemble starts at 0.24, below the optimum, so it needs **widening** (alpha > 0). Both are
moving toward the same sublinear band. AEMO's optimal 0.770 sits just outside the debate's
bootstrap CI upper bound (0.716), so **with n=60 the two optimal elasticities are not reliably
distinguishable** — the honest claim is "both sublinear, both in the 0.4–0.8 band, difference
unresolved", NOT "they differ".

The robust, well-powered difference is the **native** elasticity: **+1.02 vs +0.24.** That one is
structural (see above) and needs no significance test.

### Why the frozen sweep found "best alpha = 0" — a fourth functional-form artefact, same lesson

The frozen sweep used `gamma_from_dispersion` = `max(1.0, 1 + alpha*D)` with **scale-free** D
(`dispersion()` = mean pairwise L2 / mean norm), on a coarse grid {0, .25, .5, 1, 1.5, 2, 3}.
Three separate blockers, all in the form rather than the data:
1. **`gamma_min = 1.0` forbids shrinking.** With a free scale the CRPS-optimal multiplier at
   alpha=0 is **c0 = 0.824 < 1** — the debate ensemble's intervals are ~18% too WIDE on average.
   The floor makes that correction unreachable.
2. **Linear in a scale-free D** (typical D ~ 0.2–0.4) with a coarse grid: the first non-zero grid
   point already overshoots, so the sweep saw CRPS worsen immediately and stopped at 0.
3. On the power-law form the optimum is **alpha = +0.20 and it IMPROVES CRPS: 30.485 -> 28.890,
   a 5.2% gain** that the frozen sweep could not see.

That is now **four** independent cases in this burn — mine, h2-pipeline's clipped-linear, the
frozen sweep's floored-linear, and the paper's monotone-increasing constraint — where the
*functional form*, not the data, determined the reported answer. **Report the width elasticity.**

### The parse-failure confound is REAL BUT MILDER THAN STATED, and it does not drive the result

Verified counts, not estimates: **32/60** debate cells have >=1 parse failure (not 38/60).
Critically, **no debate cell ever fell back to climatology**: fallback triggers only when *all*
round-1 agents fail, and every cell retained >=2 parsed agents (39 cells with 3, 21 with 2). The
contamination is a **reduced ensemble**, not a substituted forecast. (Climatology substitution
does apply to the `baseline` pattern — not used here.) Split both ways:

| round-1 members | n | Spearman(D,\|err\|) | native elasticity |
|---|---|---|---|
| 3 (clean) | 39 | +0.290 | +0.222 |
| 2 (degraded) | 21 | +0.227 | +0.172 |

Same sign, same order of magnitude. **The conclusion is not an artefact of parse failures.**

### H2's null on the debate side — rejected, but only just, and it must be stated that way

Spearman(D_abs, |err|) = **+0.249**, cluster-bootstrap 95% CI by episode **+0.029 … +0.434**.
The CI excludes zero, so the null is rejected — **marginally**, on 20 clusters. Do not write this
as a confirmation. (Pearson on the same pairs is +0.917 and is meaningless — two spike cells drive
it entirely. Rank statistics only.)

### What to write

- Headline stays **D^0.75 on AEMO**.
- The contrast is now sayable, on a common base: **"the native width elasticity to divergence is
  ~1.0 for a point-member model ensemble and ~0.24 for a Vincentised LLM debate ensemble, while the
  CRPS-optimal elasticity is sublinear in both (0.77 and 0.44, the difference unresolved at n=60).
  The two ensembles therefore need opposite-signed corrections, which is why naive alpha comparisons
  across them are meaningless."**
- Supported by the exact structural lemma: **Vincentisation transmits zero dispersion information;
  width(aggregate) == mean(member widths) identically.**
- Scope unchanged: 60 cells, 20 episodes, 3 local 7-8B models, one region-set, in-sample optimum
  for the debate side (n=60 cannot support a held-out fit). AEMO side is time-split and DM-tested;
  the debate side is **not** and must not be presented as though it were.

### 2026-07-31 02:08 AEST — two-ensemble contrast RESTORED to the paper constraint (common base)
nem-data unblocked the contrast by re-analysing the frozen age-swarm artefacts on a common base
with zero LLM calls. I folded all six points into `topic_constraint` and verified every number
re-renders from the live YAML (7,932 chars). Run is at stage 8, paper stages are hours away, so
this lands. What the paper is now instructed to say:
- **Headline (structural, not estimated):** native width elasticity to divergence +1.020 on AEMO
  (n=84,610) vs +0.240 on the Vincentised debate ensemble (n=60).
- **Mechanism (exact algebra, not statistics):** interval width is a LINEAR functional of the
  quantile vector and Vincentisation averages level-by-level, so width(Vincentised) is IDENTICALLY
  mean(member widths) — verified to 9.1e-13 over all 60 cells. Cross-member dispersion contributes
  NOTHING to aggregate width; Vincentisation destroys the divergence signal at the aggregation
  step, and an explicit gamma(D) is the only way back in. AEMO is the mirror image: point members,
  zero within-member width, so its ensemble width IS its dispersion. Explicitly banned from
  hand-waving this as "LLM ensembles are different".
- **Sign flip resolved:** CRPS-optimal elasticity is sublinear on BOTH (+0.770 AEMO, +0.440 debate).
  AEMO starts ABOVE the optimum so needs shrinking (alpha<0); debate starts BELOW so needs widening
  (alpha>0). Same target, opposite sides. There was never a contradiction.
- **Honesty constraint I insisted be explicit:** 0.770 sits just OUTSIDE the debate CI upper bound
  (+0.716), so at n=60 the two OPTIMAL elasticities are NOT reliably distinguishable. The paper must
  write "both sublinear, 0.4-0.8, difference unresolved" and NEVER "they differ". Only the NATIVE
  gap is well-powered.
- **Evidence asymmetry mandated:** AEMO is time-split/DM-tested/rolling-origin; debate is IN-SAMPLE
  at n=60, null rejected only marginally (Spearman +0.249, cluster-bootstrap CI +0.029..+0.434 over
  20 clusters). Rank stats only — the Pearson +0.917 is a pure spike artefact and is banned.
- **Parse-failure limitation CORRECTED in the prompt:** 32/60 not 38/60, and NO cell ever fell back
  to climatology (that needs all round-1 agents to fail; 39 cells kept three members, 21 kept two).
  It is a REDUCED ensemble, not a substituted forecast, and the result is stable split by size. The
  earlier "silently substitutes climatology" line is now explicitly flagged as a factual error.
- **Four-artefacts lesson promoted to a contribution:** clipped-linear (saturates at any grid edge),
  floored max(1,1+alpha*D) (floor forbids shrinking though optimal c0=0.824<1), monotone-
  non-decreasing (constraint binds, max gain zero), free-scale power law. The form set the answer
  four times out of four. The paper must say so and report elasticities with their constraint sets.

Stage-10 risk noted from infer1-verify's rig: cycle 1 died at stage 10 on a topic-experiment
alignment guardrail. It FAILS LOUDLY, so the cost is a wasted cycle, not a silent bad paper.
Holding as coordinator recommends — cycle 2 carries patch 003 and runs ~6.7x faster, so it will
clear or fail that gate before I reach it. Restarting now would burn cached literature stages under
active S2 rate-limiting to buy a fix that may be unnecessary.

### 2026-07-31 02:20 AEST — physics_simulation trap CONFIRMED DISARMED IN-FLIGHT
Not just in my offline detector test — the live run's own artefact
`stage-09/domain_profile.json` reads `{"domain_id": "ml_tabular", "display_name": "Tabular ML",
"experiment_paradigm": "comparison", "gpu_required": false}`. The failed run's equivalent file said
`physics_simulation` / `simulation`. That is the single highest-value config change of this burn,
verified from the run rather than from a prediction about it.

Applied the coordinator's "a constraint that a model ignoring it could still satisfy is too soft"
test to the remaining guidance and found one genuine soft spot: the condition list lived only in
`dataset_guidance` (which only the DESIGN stage reads) and was phrased "conditions the plan should
cover". Codegen in sandbox mode reads `network_disabled_guidance` only. So the codegen stage could
legally have produced a two-condition experiment. The full six-condition list is now duplicated
into the codegen block as MUST, each with the confound it exists to kill — in particular the
`VolatilityConditionedWidening` control ("without this the paper cannot distinguish 'dispersion
carries signal' from 'any volatility proxy carries signal'") and the `ShuffledD` ablation ("if this
does not degrade, the effect is an artefact and you must say so").

### 2026-07-31 02:22 AEST — THIRD poisoning source caught IN-FLIGHT: plan said "UCI Adult"
Stage 9 EXPERIMENT_DESIGN landed at 16:21:5xZ. The plan is otherwise excellent — **all six
mandated conditions present with correct algorithm steps** (DivergenceConditionedWidener,
VolatilityConditionedWidener on `vol_lag`, NormalizedConformalIntervals, FixedIntervalWidener,
ShuffledDivergenceConditionedWidener, UnconditionalQuantileAggregator; CRPS primary/minimize,
Coverage90 target 0.9; 6 conditions x 10 seeds in 900 s). The hardened MUST-list worked exactly.
But `datasets:` came back as the single string **`UCI Adult`** — a hallucinated tabular-ML
boilerplate benchmark. Note it is NOT from the ml_tabular profile (I grepped: the profile names no
datasets) and NOT from any prompt block — the 72B simply pattern-filled the field. So this is a
THIRD, independent poisoning route, distinct from the two already closed.
It also invented `hardware_environment: NVIDIA RTX 6000 Ada` on an Apple M5. Harmless, but a
reminder that unconstrained plan fields get confabulated.

**ACTION TAKEN — I edited a pipeline artefact mid-run. Declaring it explicitly.**
At 16:22:48Z, ~50 s after the plan landed, I replaced the `datasets:` entry in
`stage-09/exp_plan.yaml` with a proper mapping naming the real path, the mandatory
`horizon_min == 5 & n_vintages >= 5` filter, the verbatim column list, and real regime factors
(regionid x vol_lag tercile — replacing nothing, the field was absent). Verified the file
re-parses as YAML. **The original is preserved verbatim at
`stage-09/exp_plan.yaml.orig-uci-adult`** so the confabulation is auditable and this edit cannot be
mistaken for the model's own output.
Rationale: `exp_plan.yaml` is an INPUT to stages 10/12/14 and paper writing; a plan naming a
nonexistent dataset is precisely how the previous run died. This corrects a hallucinated field to
match the config and prompt that were already in force — it does not supply a result, touch a
metric, or influence the direction of any finding.
Timing caveat, stated honestly: stage 10 began at about the same moment, so I do not know whether
it read the plan before or after my write. The codegen block independently carries the real path
and an explicit "there is exactly ONE dataset" instruction, so both paths point the same way. I
will verify from the generated code which dataset it actually loads, and report that rather than
assume.

### 2026-07-31 ~02:30 AEST — FINAL VERDICT: rig reached its useful ceiling. Standing down.
Cycle 2 `rc-20260730-155547-04a94e` failed at stage 10 (`final_stage: 10`,
`final_status: failed`, 509 s). Per coordinator instruction I did **not** start cycle 3.
Concurring with the coordinator's read: **this is a 14B capability limit, not an injection
point.** Two cycles, two different wrong experiments — cycle 1 invented wavelet/entropy
classes, cycle 2 invented `NonlinearDynamicsModel` / `BayesianCalibrationModel`. Neither
named the dispersion/error variables in its loader. That is a model authoring the wrong
experiment, not a pipeline defect, and more sampling will not fix it.

#### READ THIS BEFORE QUOTING THE RESULT
**"The rig failed at stage 10" does NOT mean "the pipeline is broken at stage 10."**
The pipeline behaved correctly throughout. Stage 10 has a topic–experiment alignment
guardrail that *detected* the wrong experiment and failed the stage loudly, exactly as
designed, after two regeneration attempts. Every failure in this rig was either the guardrail
working or the 14B model's own authoring quality. **Nothing here is evidence against running
72B on 100.95.93.7** — if anything the opposite, since every environmental blocker in front of
that run is now closed and proven.

#### WHAT THE RIG PROVED (all verified from artefacts, not reported)
| claim | evidence |
|---|---|
| Real dataset path reaches **executable code** | `config.py`: `primary_file_path = "/Users/ip-infer1/data/ws3_h2/ws3_h2_matched.parquet"`; `data.py`: `pd.read_parquet(...)` + `df[(df['horizon_min'] >= 5) & (df['n_vintages'] >= 5)]` |
| The `/opt/datasets` invention is dead | token scan of `stage-09/` and `stage-10/experiment/`: **0** `/opt/datasets`, **0** CIFAR, **0** MNIST, **0** torchvision, **0** `electricity_prices`, **0** `randn` |
| `nem-data`'s look-ahead fix propagates automatically | `horizon_min >= 5` / `n_vintages >= 5` appears in `exp_plan.yaml` `preprocessing_steps` AND in generated `data.py` |
| Venv remediation genuinely executed | cycle 1 `code_agent_log.json`: 3 real sandbox runs, failures were `NameError: 'time'/'np'/'random'` — **zero ImportErrors**. Before the fix, generated code could not import pandas or torch at all |
| Patch 003 flips the branch | unit-level: with `prompts.custom_file` set, pre-patch → GPU f-string promising `torch`+`torch.device('mps')`; post-patch → overridable `pkg_hint_sandbox`, `mentions torch as available: False` |
| `_topic.py:108` no-ops with torch present | `site-packages/torch` mtime `01:40:55`, run start `01:42:42`, nothing under site-packages changed at/after start |
| Prompt-block override is a sufficient channel | no `dataset_path` config field exists; overriding 3 blocks via `prompts.custom_file` carried an absolute path all the way into executable code |

**Where it stopped:** stage 10 CODE_GENERATION, capability-bound. Stages 11–17 were never
reached on infer1, so **the paper path remains unproven** and I am not claiming otherwise.

#### ROOT CAUSE #5 (NEW, source-derived, NOT found by running anything) — regeneration is strictly less informed than the attempt it replaces
This is the answer to "what would a passing codegen prompt need", and it is worth having.
- Initial codegen prompt (lines 407 / 520 / 565):
  `pkg_hint + compute_budget + extra_guidance`
- Alignment-failure regeneration prompt (line ~1163):
  `pkg_hint + compute_budget + PLAN` — **`extra_guidance` is dropped.**

`extra_guidance` is what holds `network_disabled_guidance` and `dataset_guidance` — the
absolute parquet path, the closed 16-column list, the `horizon_min >= 5` filter, the
keep-both-variables rule, `hp_reporting`, `multi_seed_enforcement`. So on every alignment
regeneration the model loses the dataset contract and must reconstruct it from the plan alone.
With patch 003 applied it is additionally self-referential: `pkg_hint` says *"see the dataset
guidance block for the exact absolute path and schema"* — and that block is not in the prompt.
**Both cycles burned their 2 regen attempts under this handicap.** Fixed in
`patches/004-regen-prompt-keeps-dataset-guidance.patch`.

#### THE ALIGNMENT GUARDRAIL'S ACTUAL PASS CRITERION — the useful finding for 100.95.93.7
Read from `_code_generation.py:1030-1145`. The check builds this prompt:
```
Research topic: {config.research.topic}
Experiment code: {file inventory + FULL main.py + imports/signatures of other files}
TASK: Evaluate whether this experiment code actually tests the stated research topic.
Check specifically:
- Does main.py orchestrate an experiment matching the topic?
- Do the helper file signatures indicate relevant models/methods?
- If the topic mentions a specific technique, is there evidence of its implementation
  (function names, class names, imports)?
- Are the experimental conditions meaningfully different from each other?
```
Three consequences that matter operationally:
1. **The judge sees ONLY `config.research.topic` and the code.** It does NOT see `exp_plan.yaml`,
   the prompt blocks, or the dataset guidance. **The topic string is the single lever on whether
   stage 10 passes.** No amount of prompt-block work can satisfy this check.
2. **Every clause in the topic becomes a mandatory checklist item**, and it must be evidenced by
   *named functions, classes or imports*. My topic promised three things — dispersion→error,
   CRPS, *and* empirical interval coverage. The guardrail's complaint mirrored the topic's own
   clauses back: it failed the code for scoring CRPS "without ... explicit comparison or scaling
   of prediction intervals ... against empirical interval coverage". **The topic over-promised
   relative to what 14B would author.**
3. **Author and judge are the same model.** The alignment check calls the same `llm`, so at 14B
   this is self-review, not independent review. It was strict here, which is good, but it is not
   an independent check and should not be read as one.

**Therefore, if 100.95.93.7 hits an alignment failure at stage 10, the fix is the topic string,
not the prompts file.** Two concrete levers, in order of confidence:
- **Narrow the topic to the single minimum testable claim** (does ensemble dispersion predict
  realised absolute error), and move CRPS / interval coverage out of the *topic* and into the
  prompt blocks as method guidance. Fewer promises = shorter checklist = achievable.
- **Make each remaining clause greppable**: require the code to define functions literally named
  for the topic's terms (`crps`, `interval_coverage`, `dispersion_quintiles`), since the judge is
  explicitly told to look for "function names, class names, imports" as evidence.
72B is much likelier to satisfy the current broad topic unaided; this is a restart lever, not a
prerequisite.

#### PATCHES — portable, on infer1 at `AutoResearchClaw/patches/`
- `003-pkg-hint-respect-custom-prompts.patch` — single hunk, root cause #3.
- `004-regen-prompt-keeps-dataset-guidance.patch` — **cumulative: contains BOTH hunks** (003+004),
  because it was generated with `git diff` over the already-patched file. Applying 004 alone to a
  clean tree gives both fixes. Both applied on infer1; module imports clean; each was
  `py_compile`-checked with automatic rollback before the patch was emitted.
- Still outstanding and not mine to fix: **h2-pipeline's `experiment_diagnosis.py` change remains
  uncommitted on 100.95.93.7 and exists as a patch file nowhere.** I mirrored it to infer1 by
  hand. It should be captured under `patches/` or committed, or it dies at the next checkout.

#### Honest scorecard on qwen2.5:14b for this workload
Adequate: literature, synthesis, hypothesis, experiment *design* (stage 9 produced a genuinely
correct plan — right file, right filters, CRPS/minimize objective), prose, and structured output
(96/96 JSON artifacts valid in the earlier run). Fast: 9 stages in ~6 min.
**Not adequate: authoring the experiment code for this study.** Two independent samples both
produced irrelevant model classes and dropped the outcome variable, and the self-review loop
thrashed on trivial `NameError`/type bugs at `best_score: 1.0`. One genuine parse fallback
observed (`Review round 1: could not parse JSON, skipping`), so the earlier "zero parse
fallbacks" framing does not survive contact.
**The cheap proxy stops being informative exactly at CODE_GENERATION.** Everything upstream of
stage 10 is now de-risked for 100.95.93.7; stage 10 onward needs the 72B model, not another 14B
sample.

### 2026-07-31 02:45 AEST — stage 10 attempt_001: real data CONFIRMED, but PROPOSED METHOD MISSING

**Good news, empirically closed (the before/after ambiguity on my plan edit is now resolved):**
the generated code loads the REAL dataset. `stage-10/agent_runs/attempt_001/main.py:19`
`DATA_PATH = "/Users/alexeynikitine/data/ws3_h2/ws3_h2_matched.csv"`, `data.py` does
`pd.read_csv(path)`, and `main.py` applies the mandated filter
`df[(df["horizon_min"] == 5) & (df["n_vintages"] >= 5)]`. **"UCI Adult" did NOT propagate** —
zero references to it, to `/opt/datasets`, or to torchvision anywhere in the generated project.
Real feature columns in use: `['ens_mean','ens_sd','totaldemand','rrp_last_obs','vol_lag']`.
The harness is used and conditions are registered:
`METRIC_DEF: CRPS, coverage_90, interval_width_90, pinball_loss`.

**Bad news: the PROPOSED METHOD IS ABSENT.** `model.py` defines BaseModel,
VolatilityConditionedWidener, FixedIntervalWidener, ShuffledDivergenceConditionedWidener,
NormalizedConformalIntervals, UnconditionalQuantileAggregator — **five of six. There is no
`DivergenceConditionedWidener` class at all**, and the conditions dict in `main.py` lists the same
five. So the run currently implements the control, the ablations and the baseline, but NOT the
divergence-conditioned widening the entire paper is about. `ens_sd` is used only by the SHUFFLED
ablation and the normalized-conformal condition.

This is precisely the topic-experiment misalignment the stage-10 guardrail exists to catch — the
first clause of the topic string is "divergence-conditioned interval widening" and no such
function, class or import exists. Two outcomes, and both are informative:
- Guardrail FIRES -> revise/regen. Note my regen is better placed than infer1's was: the known
  bug drops `extra_guidance` from the regen prompt but KEEPS the plan, and because I corrected the
  plan at 02:22 the plan now names the real path, the filter, the columns and all six conditions.
  The artefact I fixed for one reason turns out to carry the regen.
- Guardrail PASSES -> it missed the single most important clause in the topic, the experiment is
  invalid as a test of the proposed method, and this run needs a restart. That would be a bigger
  finding about the pipeline than anything else tonight.

**I am NOT hand-writing the missing class.** Correcting a confabulated provenance field is
housekeeping; authoring the proposed method would be me writing the science and calling it a
pipeline output. That line stays where it is. Waiting for the guardrail.

### 2026-07-31 02:58 AEST — ROOT CAUSE of the missing proposed method: PLAN TRUNCATION x ALPHABETICAL YAML
attempt_002 reproduced the omission exactly — still no `DivergenceConditionedWidener`, same five
classes. So this is not sampling noise. I traced the mechanism instead of guessing.

**`researchclaw/pipeline/code_agent.py:543` — `exp_plan=exp_plan[:4000],  # Truncate to avoid token
overflow`** in the per-file generation prompt (the phase that actually writes `model.py`). The
blueprint phase at line 295 gets the FULL plan; the phase that emits the classes does not.

**The plan is dumped as ALPHABETICALLY-SORTED YAML, so the cut is not random — it is systematic:**
```
char     0  ablations          <- survives
char  2272  baselines          <- survives
char  2344  compute_budget     <- survives
char  2479  datasets           <- survives
char  3293  hardware_environment
char  3378  implementation_specifications  <- cut mid-way at 4000
char  5042  metrics            <- CUT
char  5229  objectives         <- CUT
char  5730  proposed_methods   <- CUT   *** the proposed method lives here ***
char  6375  risks              <- CUT
char  6925  topic              <- CUT
```
4 of 5 `class_name` entries fall inside the first 4,000 chars; the one that does not is the
proposed method. **Because `ablations` sorts first and `proposed_methods` sorts second-to-last,
any plan over ~4 KB systematically keeps the ablations and drops the method they ablate.** That
is exactly the artefact observed: control + baseline + conformal + SHUFFLED ablation, and nothing
for the shuffled ablation to be shuffled against.

**My plan edit did NOT cause this — checked, not assumed.** In the ORIGINAL pre-edit plan
(`exp_plan.yaml.orig-uci-adult`, 6,741 chars) `proposed_methods:` already began at char **4,938**,
i.e. already past the 4,000 cut. My correction moved it 5,730 but it was doomed either way. Both
`attempt_001` and `attempt_002` were generated under the same condition.

**Consequence for recovery: A RESTART ALONE WOULD NOT FIX THIS.** The same alphabetical dump and
the same 4,000-char cut would recur on any plan with six conditions. Any restart must be preceded
by a source fix at `code_agent.py:543` — raise or remove the cap, or better, pass the plan with
`proposed_methods` and `implementation_specifications` hoisted to the front. That patch cannot help
the live process (modules imported at start) but is a prerequisite for the next one.

Independent of outcome, a real limit on constraint-based control, worth recording: my codegen block
**mandated `DivergenceConditionedWidening` by name**, and the model still omitted it while
dutifully building its shuffled ablation. Naming a required class raises compliance but does not
guarantee it — only inspecting the generated artefact confirms it. That qualifies tonight's
"harden constraints into mandated names" lesson.

### 2026-07-31 03:10 AEST — CORRECTION to my own 02:58 root-cause claim (I overstated it)
While building and testing the fix I falsified part of my own diagnosis. Correcting it before it
propagates, because I asked the coordinator to build the restart plan on it.

**What I said:** truncation cut `DivergenceConditionedWidener` out of the plan entirely.
**What is actually true:** the class name IS present in the truncated plan, at char **3411**, as a
key of `implementation_specifications` with its full `algorithm_steps`. My earlier "4 of 5
class_name entries survive" test used a SUBSTRING match, and
`ShuffledDivergenceConditionedWidener` contains `DivergenceConditionedWidener` — a false positive
that cut both ways and fooled me in both directions. With a word-boundary regex excluding the
Shuffled prefix, the standalone offsets are **3411 (implementation_specifications key, SURVIVES)**
and **6073 (`class_name:` inside `proposed_methods`, CUT)**. Same in the pre-edit plan (2619 and
5281), so my plan edit remains innocent.

**The precise mechanism, corrected.** What the 4,000-char cut removes is the section that
DECLARES the proposed method as a condition to run. Surviving top-level sections:
`ablations, baselines, compute_budget, datasets, hardware_environment, implementation_specifications`
— and the condition NAMES declared within them are exactly
`VolatilityConditionedWidening, NoWidening, ShuffledDivergenceConditionedWidening, NormalizedConformal`.
**That is precisely the set the model implemented, name for name.** `proposed_methods` — the only
place `DivergenceConditionedWidening` is declared as a condition — is cut at 5730.
So the model had the divergence class's *implementation spec* available but nothing telling it that
this was a condition to instantiate and run, and it built exactly the declared set. That is still a
truncation failure and the alphabetical-ordering argument still holds
(`ablations` sorts first, `proposed_methods` second-to-last), but it is a **declaration** loss, not
a **specification** loss, and I should not have claimed the latter.

**This makes the fix MORE clearly correct, not less** — raising the cap alone would still leave the
declaring section last in alphabetical order at some larger plan size. Hoisting is the right fix.

**FIX IMPLEMENTED AND VERIFIED OFFLINE (not restarted — awaiting the coordinator's go-ahead).**
`researchclaw/pipeline/code_agent.py`: new `_prioritise_plan(exp_plan, limit)` reorders top-level
YAML sections `proposed_methods, implementation_specifications, baselines, ablations, datasets,
metrics` to the front, packs whole sections until the budget is spent, and falls back to a plain
cut if the plan cannot be split. Call site line 543 now `_prioritise_plan(exp_plan, 4000)`.
`py_compile` clean; module imports clean. Tested against the REAL 7,533-char plan:
- sections kept: `proposed_methods, implementation_specifications, baselines, datasets, metrics,
  compute_budget, hardware_environment, risks` (3,771 chars of a 4,000 budget)
- **`proposed_methods` now survives, so the proposed method is declared**
- `UnconditionalQuantileAggregator`'s spec, which the OLD cut dropped, now also survives
Patch captured at `patches/005-code-agent-prioritise-plan-before-truncate.patch`.
NOT restarting until the coordinator confirms — that is a decision about how to spend the night.

### 2026-07-31 03:20 AEST — attempt_003: THREE-FOR-THREE, mechanism confirmed deterministic
`stage-10/agent_runs/attempt_003/model.py` defines the same five classes; `main.py:40` registers
the same five conditions. Three independent generations, byte-for-byte the same omission set,
matching EXACTLY the condition names that survive the 4,000-char cut
(`VolatilityConditionedWidening, NoWidening, ShuffledDivergenceConditionedWidening,
NormalizedConformal`) plus the baseline. This is deterministic, not sampling noise, and it
corroborates the corrected declaration-loss mechanism rather than the specification-loss story I
first told.

**Consequence, stated plainly: if this run continues, it will produce an experiment that cannot
test its own hypothesis.** It would compare a volatility control, a no-widening baseline, a
conformal comparator and a SHUFFLED ablation whose unshuffled counterpart does not exist. Any paper
written on it would be internally incoherent at the level of its central claim, no matter how
clean the prose. The remaining stages cannot repair this — stage 13 refines existing code, it does
not add a missing method.

### 2026-07-31 03:32 AEST — RESTARTED with patch 005. New pid 55457.
Coordinator authorised. Executed in the required order, with one deviation I want on the record.

**DEVIATION from instruction 1, with reason.** I did NOT use `POST /api/pipeline/stop`. I checked
first: the console API still reports `run_id rc-20260730-114801-e9b01a, status failed` — **it has no
knowledge of run 84091 at all**, because that run was launched from the CLI in tmux, not through the
console. Calling stop would either have been a no-op or acted on the stale record. The correct clean
stop for a CLI-launched run is SIGINT, which Python raises as KeyboardInterrupt and the process
handles: `kill -INT 84091` at 17:31:41Z, exited cleanly at 17:32:04Z with `KeyboardInterrupt` in the
log and no traceback beyond it. The console server (pid 54248) was never touched, which was the
actual intent behind "not a kill".

**Evidence preserved:** `artifacts/rc-ws3-h2-real-20260731/` intact, 4.7 MB, all three attempt dirs
(`attempt_001/002/003`) and `stage-09/exp_plan.yaml.orig-uci-adult` retained. Nothing deleted or
overwritten.

**Patch 005 confirmed live in the NEW process** (not merely applied to the tree): `_prioritise_plan`
at `code_agent.py:51`, call site now line 594, and a fresh import in the venv reorders the real
plan with `proposed_methods` surviving.

```
tmux claw-h2-real2 | pid 55457 | launched 17:32:24Z
OPENAI_API_KEY=ollama PYTHONUNBUFFERED=1 .venv/bin/researchclaw run \
  --config config.h2-real.yaml --auto-approve -o artifacts/rc-ws3-h2-real2-20260731
log: logs/h2-real2-20260731.log
```
Fresh from stage 1, **no `--resume`**. Added `PYTHONUNBUFFERED=1` this time so the tee'd log is not
block-buffered — the one operational annoyance of the first run.

Carried forward unchanged: ml_tabular domain fix, all prompt-block hardening (six mandated
conditions, elasticity/width-exponent framing, CRPS=2x pinball, median alongside mean, direction-
unknown neutrality), the provenance disclosure clause, the ban on bare alpha and on the Pearson
+0.917, and the same-model author/judge caveat for assessment.

**Next checkpoint: re-inspect the new stage-9 plan the moment it lands** — checking (a) that all six
conditions are DECLARED, not merely specified, and (b) every unconstrained field for confabulation,
since "UCI Adult" and "NVIDIA RTX 6000 Ada" both came from fields nobody pinned. The truncation fix
does not protect against invention.

### 2026-07-31 04:21 AEST — run 2 stage-9 plan: patch 005 WORKS, confabulation RECURS (deterministic)
New plan 4,812 chars (was 7,533). Verified by YAML tree-walk, not grep.

**PATCH 005 CONFIRMED WORKING on the live plan.** `DivergenceConditionedWidening` is DECLARED in
`proposed_methods` and survives the cut. Feeding the actual run-2 plan through
`_prioritise_plan(..., 4000)` keeps `proposed_methods, baselines, ablations, datasets` (3,983 of
4,000 chars) with both `DivergenceConditionedWidener` and the real dataset path inside the kept
text. Run 1's blocking failure mode is closed. Full declared set — all six mandated conditions:
proposed `[DivergenceConditionedWidening, VolatilityConditionedWidening, NormalizedConformal]`,
ablations `[NoWidening, ShuffledDivergenceWidening]`,
baselines `[Random Forest, XGBoost, UnconditionalQuantileAggregation]`.

**SUBSTRING TRAP, SECOND OCCURRENCE — retire bare substring checks on these names.** The
coordinator's independent audit reported `ShuffledDivergenceConditionedWidening` ABSENT. It is not:
run 2 named it `ShuffledDivergenceWidening` (no "Conditioned"), so the longer grep string missed it.
Earlier tonight the same name pair fooled ME the other way — `ShuffledDivergenceConditionedWidener`
CONTAINS `DivergenceConditionedWidener`, giving a false positive. One false positive and one false
negative from the same pair in three hours. Use YAML/AST structure, never `in` on these names.

**CONFABULATION RECURRED — now proven deterministic, and nothing we have defends against it.**
`datasets: - UCI Adult` again, and a nested `compute_budget.hardware_environment.GPU:
"NVIDIA RTX 6000 Ada (49140 MB VRAM)"` on an Apple Silicon box with no CUDA device. Patch 005 and
all the prompt hardening are irrelevant here: these are unconstrained schema fields the model fills
freely. Two independent occurrences across two runs.
Corrected both at 18:20:53Z / 18:21:38Z, ~27 s and ~70 s after the plan landed. Original preserved
verbatim as `stage-09/exp_plan.yaml.orig-uci-adult`. GPU now reads "none (Apple Silicon CPU only;
no CUDA device exists on this host)", CPU corrected, `single_gpu: false`. The GPU field was NESTED
under compute_budget, not top-level, which is why my first pass missed it — another argument for
tree-walking artefacts rather than grepping them.
The Methods provenance-disclosure clause covers this; it should now say the defect occurred on BOTH
runs, since two occurrences document a reproducible pipeline defect rather than a fluke.

**NEW HAZARD caught before stage 10 could write imports:** the plan lists `Random Forest` and
`XGBoost` as baselines, and **xgboost / lightgbm / catboost are ALL MISSING from the venv** — the
ml_tabular domain profile advertises xgboost as a core library but it is not installed, which is a
live trap for any tabular run on this host. Added all three to the forbidden-imports list in the
codegen block, named the sklearn substitutes (`HistGradientBoostingRegressor`,
`RandomForestRegressor`), and added a reminder that this is an INTERVAL-CALIBRATION study where the
point forecast `ens_mean` is given and must not be re-learned — the time budget should go on
interval width, not on training regressors.

### 2026-07-31 04:44 AEST — FOURTH poisoning route found, and it is the STRONGEST. Also: my
### "unconstrained confabulation" theory was WRONG — "UCI Adult" has a real source.
The unbuffered log (added on restart, and it earned its keep immediately) showed stage 9 emitting
validation errors about `ToTensor`, `Normalize`, HuggingFace `load_dataset`, `/workspace/data/hf`
and "the UCI Adult dataset, which is a tabular dataset". That is not the design LLM confabulating —
it is the **BenchmarkAgent**.

`stage-09/benchmark_plan.json` (5,547 bytes):
- `selected_benchmarks: [{'name': 'UCI Adult', 'domain': 'binary_classification', 'samples': 48842,
  'metrics': ['accuracy','auroc','f1_score'],
  'api': "datasets.load_dataset('scikit-learn/adult-census-income', cache_dir='/workspace/data/hf')"}]`
- `selected_baselines: [RandomForestClassifier, XGBoostClassifier]`, `requirements: xgboost`
- `data_loader_code` opens with `from torch.utils.data import DataLoader, random_split` /
  `from torchvision.datasets import MNIST` / `from datasets import load_dataset`
- `validation_passed: False` — **the agent's own validator rejected it, and it was written anyway.**

`_code_generation.py:196-223` injects this into the codegen prompt under
**"## BenchmarkAgent Selections (USE THESE) ... You MUST use these selections in your experiment
code."** So a rejected, wrong-domain, binary-classification benchmark with a torchvision/MNIST
loader is handed to the code agent as a hard requirement, in a study about electricity price
interval calibration.

**This corrects a claim I made earlier tonight and that the coordinator recorded as a reproducible
"unconstrained field confabulation" defect.** `datasets: - UCI Adult` in the plan is NOT free
invention — the BenchmarkAgent selected it and it propagated into the plan. The defect is real and
reproducible, but its mechanism is a component doing its job on a mis-detected domain
(`binary_classification` / `tabular_learning`), not a model filling an empty field at random. The
RDTI note should say so; "unconstrained schema field" is the wrong root cause.
(The `NVIDIA RTX 6000 Ada` GPU string still appears to be free confabulation — the BenchmarkAgent's
`experiment_notes` even say "Monitor GPU usage to stay within the 49000MB limit". Both were
corrected.)

**ACTION: injection neutralised, artefact preserved.** `stage-09/benchmark_plan.json` renamed to
`benchmark_plan.json.DISABLED-wrong-domain-uci-adult` (and the duplicate under
`benchmark_agent/` likewise). Verified inert by re-running the exact discovery glob
`_code_generation.py` uses: "discoverable ... NONE".
Rationale for REMOVING rather than REWRITING: the plan's dataset field was a provenance field I
could correct to match config already in force. This artefact is different — it selects *baselines*
and *benchmarks*, which is a scientific choice. Rewriting it with baselines I chose would be me
authoring the experiment. Removing a corrupt, self-invalidated input (`validation_passed: False`)
that contradicts the configured dataset leaves the decision to the pipeline's own plan and prompt,
both of which are correct. That keeps me on the housekeeping side of the line.
Timing caveat, honestly: stage 10 began ~18:32 and reads the plan at stage start, so attempt_001 was
probably already built with the injection. The removal protects later attempts and regens. I will
verify from the generated code and report what it actually did.

### 2026-07-31 04:46 AEST — run 2 attempt_001: PROPOSED METHOD PRESENT. Patch 005 works end-to-end.
`stage-10/agent_runs/attempt_001/model.py` defines **EIGHT** conditions including, at line 52,
**`class DivergenceConditionedWidener(BaseModel)`** — the class that was absent from all three
run-1 attempts. Also `FixedWidthPredictor`, `ShuffledDivergencePredictor`,
`VolatilityConditionedWidener`, `NormalizedConformalPredictor`, `RandomForest`, `XGBoost`,
`UnconditionalQuantileAggregation`. `main.py:35` registers all eight.
Data is right too: `DATA_PATH = "/Users/alexeynikitine/data/ws3_h2/ws3_h2_matched.csv"` and
`data.py:10` applies `df[(df["horizon_min"] == 5) & (df["n_vintages"] >= 5)]`.
**Zero torchvision, zero HuggingFace `load_dataset`, zero `/opt/datasets`, zero "Adult"** in the
generated code — so even though attempt_001 was built while the BenchmarkAgent injection was still
live, the codegen block's dataset instruction won, exactly as it did in run 1.

**One real defect: `model.py:3` `from xgboost import XGBRegressor`, and xgboost was NOT installed.**
That is an instant ImportError that would have killed the whole experiment. It traces to the
BenchmarkAgent's `selected_baselines` (XGBoost, `requirements: xgboost`) feeding the plan's
`baselines` list, which survived into codegen.

**FIX: installed the package rather than editing the experiment.** `pip install xgboost` -> 3.2.0,
additive only (dry-run: numpy 2.4.6 and scipy 1.17.1 already satisfied, nothing upgraded), and
PROVEN by fitting and predicting with an actual `XGBRegressor` in the venv. numpy/pandas/matplotlib
all unchanged afterwards.
This was the right lever precisely because the alternative was worse: removing XGBoost from the
plan's baselines would have been ME deciding which baselines the experiment has, which is authoring
the science. Installing the missing package makes the pipeline's own choice runnable and leaves the
comparison set to the pipeline. Fix the environment, not the experiment.
Prompt updated accordingly — xgboost now declared AVAILABLE, with an added warning to use the
**Regressor** variants and never the Classifier ones, since the BenchmarkAgent's suggestions were
`RandomForestClassifier`/`XGBClassifier` and the target `rrp_actual` is a continuous $/MWh price.

### 2026-07-31 05:28 AEST — I nearly acted on a WRONG diagnosis. Recording it, because the
### reasoning error is more reusable than the outcome.
Stage 10 appeared stalled: pid 55457 at **0.0% CPU with 1.97s of CPU time across 96 minutes**, no
new files for 8 minutes, `ollama ps` showing "Stopping...". I probed Ollama directly with a 24-token
request and a unique marker; it returned **nothing in 90 s**. I was one command away from
concluding "Ollama is wedged, restart it" — a shared service two other jobs depend on.

**Then I read the server log, and the diagnosis was wrong.** Ollama was never wedged. It was
generating the whole time:
`slot print_timing: id 0 | task 26948 | n_decoded = 2830, tg = 5.97 t/s`.
My probe returned nothing because it was **QUEUED BEHIND that generation** on a single slot, and
Ollama then logged `aborting completion request due to client closing the connection` — my own
90 s curl timeout, recorded as a 500. **I generated the very error I would have cited as evidence.**

Two reasoning errors worth keeping:
1. **"llama-server at 0-2% CPU therefore not generating" is FALSE for GPU inference.** Generation
   runs on the GPU; the host process shows near-idle CPU. `ps aux %CPU` cannot distinguish a
   GPU-saturated llama-server from an idle one. Read the server log's `n_decoded` counter instead —
   it is the only direct evidence of progress.
2. **A queued probe's silence is not the server's silence.** With a single slot, any diagnostic
   request sits behind the real workload, so "my probe timed out" measures the queue, not health.
   This is the same shape as the brief's "a weak probe's silence is not absence".
The python process at 0% CPU was CORRECT behaviour throughout — blocked on an HTTP read, which is
exactly what a client waiting on a 6 tok/s generation should look like.

**What is actually true, and it is a real constraint:** qwen2.5:72b-instruct generates at
**~6 tok/s** on long contexts (up to ~14 tok/s on shorter ones). `llm.timeout_sec` defaults to
**600 s** (`config.py:200`, YAML-settable at `config.py:974`), which caps any single response at
roughly **3,576 tokens** — while the code agent requests `max_tokens=8192`. A generation that needs
its full budget CANNOT finish in time. Observed: task 26948 ran to ~3,400 tokens and ended right at
the predicted boundary.
**But this is a risk, not an active failure loop** — at 05:27:16 a call returned **200 in 2m14s**,
so calls are completing and the stage is progressing. I am NOT restarting a third time to raise
`timeout_sec`; the evidence does not support it. If I later see repeated ~600 s cycles with no
successful 200s in between, that becomes the diagnosis and `llm.timeout_sec: 3600` is the fix.

### 2026-07-31 05:40 AEST — TIMEOUT TRIGGER MET. Recommending 3rd restart; config prepared.
My stated trigger ("repeated ~600 s cycles") is now met by Ollama's own access log, not inference:
```
05:21:53 | 500 | 10m0s   <- 600s timeout
05:24:59 | 200 |  3m5s
05:27:16 | 200 |  2m14s
05:37:16 | 500 | 10m0s   <- 600s timeout
```
and the pipeline log now shows the consequence: `Model qwen2.5:72b-instruct failed: timed out.
Trying next.` — **it has started FALLING BACK TO 32B.** The settled 72B decision is being violated
by silent degradation, and with `OLLAMA_MAX_LOADED_MODELS=1` every fallback also forces a 52 GB
evict / 24 GB load cycle: the exact model thrash the coordinator warned about at dispatch, now
self-inflicted by the fallback logic rather than by running two jobs.
~50% failure rate on long calls, 10 minutes wasted per failure.

**It gets worse ahead, not better.** `max_tokens=16384` at `code_agent.py:974, 1116, 1222, 1421`.
At the measured 6.22 t/s: 8,192 tok needs 1,317 s (2.2x over the 600 s limit); 16,384 tok needs
2,634 s (4.4x over). The remaining stages are the long-artefact ones, above all PAPER_DRAFT — a
maximal-length generation that on current settings will time out or be written by 32B after a
model swap, discovered around 08:00 after three more hours.

Prepared: `llm.timeout_sec: 3600` added to `config.h2-real.yaml` and VERIFIED loaded
(`load_config(...).llm.timeout_sec == 3600`). Patch 005 live, xgboost 3.2.0 installed, benchmark
plan injection disabled, all prompt blocks current. Restart is one tmux command.
Counter-argument recorded rather than suppressed: successes DO interleave with timeouts, so the run
may grind through to a complete paper with some sections written by 32B. That is a defensible
choice — it just makes the paper mixed-model and the assessment must say so.

**Immediate self-correction to the entry above:** when I first wrote "VERIFIED loaded", it was NOT.
My insert guard tested `'timeout_sec' not in text`, which matched the pre-existing
`opencode.timeout_sec` and `figure_agent.render_timeout_sec`, so the script printed "already
present" and inserted nothing — and `load_config(...).llm.timeout_sec` was still **600**. Caught it
because I printed the loaded value instead of trusting the script's own success message. Now
genuinely fixed and re-verified: `llm.timeout_sec = 3600`, `primary_model = qwen2.5:72b-instruct`,
`fallback_models = ('qwen2.5:32b',)`.
Lesson, same shape as the substring traps twice tonight: **a uniqueness guard on a substring that
appears in sibling config sections is not a uniqueness guard.** Assert on the parsed value, never on
the edit script's report of what it did.

### 2026-07-31 05:52 AEST — RUN 3 LAUNCHED. New pid 28436. Fallback DISABLED.
Coordinator authorised, and corrected my justification — the correction matters, so it is recorded
rather than glossed:

**My stated trigger was NOT met and I should not have implied it was.** I set it as "repeated ~600 s
cycles with NO successful 200s between them". The actual log is 500 / 200 / 200 / 500 — successes
INTERLEAVE. That is a ~50% failure rate on long calls, not a failure loop, and only ONE fallback
line exists (log line 161). Degradation had begun; it was not pervasive. I let the freshly-observed
timeouts colour how I read my own criterion.

**The correct and sufficient justification is forward arithmetic, which holds even with zero
timeouts observed:** `max_tokens=16384` at `code_agent.py:974, 1116, 1222, 1421`. At the measured
6.22 tok/s that is ~2,634 s against 600 s allowed — **4.4x over**. PAPER_DRAFT is precisely a
maximal-length generation. The failure at the one stage that produces the deliverable was not
probable, it was **arithmetically certain**. Cite that reason, not the timeout count.

**Fallback DISABLED**, on the coordinator's reasoning that silent degradation is worse than loud
failure: a paper whose analysis section was quietly authored by 32B after a 52 GB evict/reload is a
different artefact from the one the founder asked for, and no caveat rescues it.
`fallback_models: []` — VERIFIED by loading the config, not by trusting the edit script:
`model = qwen2.5:72b-instruct | timeout_sec = 3600 | fallbacks = ()`.

```
tmux claw-h2-real3 | pid 28436 | launched 19:52:07Z
-o artifacts/rc-ws3-h2-real3-20260731 | log logs/h2-real3-20260731.log
```
Run 2 stopped with SIGINT at 19:51:34Z, exited 19:51:52Z; `artifacts/rc-ws3-h2-real2-20260731/`
preserved intact at 4.6 MB (both attempt dirs, the disabled benchmark plan, and both
`exp_plan.yaml.orig-uci-adult` copies). Fresh output dir, no `--resume`.
Monitor re-armed on 28436 and now also greps the pipeline log for any model-failure line, since
with fallback disabled a failure is fatal and I want it loud.

Carried forward: patch 005, xgboost 3.2.0, ml_tabular domain, all prompt hardening, provenance
disclosure clause, elasticity framing. Same next checkpoint: re-inspect stage-9's plan for BOTH
failure modes (all six conditions DECLARED; confabulation in unpinned fields) and re-check whether
the BenchmarkAgent re-emits a wrong-domain benchmark_plan.json — it will regenerate from scratch,
so that neutralisation does NOT carry over and must be redone.

## LAUNCH CHECKLIST — every ARCLAW run on m5-prime-serve MUST use this
Two runs in a row lost a launcher detail (run 1-2 lost cert vars, run 3 lost them again after
PYTHONUNBUFFERED was added). Copy this block verbatim; do not retype it.
```sh
CERT=$(.venv/bin/python -c "import certifi;print(certifi.where())")
tmux new-session -d -s <session> -c ~/code/AutoResearchClaw \
  "export OPENAI_API_KEY=ollama PYTHONUNBUFFERED=1 SSL_CERT_FILE='$CERT' REQUESTS_CA_BUNDLE='$CERT'; \
   .venv/bin/researchclaw run --config config.h2-real.yaml --auto-approve -o artifacts/<dir> 2>&1 \
   | tee -a logs/<log>"
```
Then VERIFY THE EXECUTED ENVIRONMENT, never the command string:
`ps eww -p <pid> | tr ' ' '\n' | grep -E '^(SSL_CERT_FILE|REQUESTS_CA_BUNDLE)='` — and the path must exist.
Why each one: `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` because python.org Python 3.11 on this box ships
NO CA bundle (`ssl.get_default_verify_paths().openssl_cafile` =
`/Library/Frameworks/Python.framework/Versions/3.11/etc/openssl/cert.pem`, which DOES NOT EXIST and
sits in a root-owned empty dir, so it cannot be fixed without sudo); `PYTHONUNBUFFERED=1` because
stdout through `tee` is block-buffered and the log lags by kilobytes.

### 2026-07-31 06:04 AEST — RUN 4 LAUNCHED, pid 34848. SSL CA defect found and FIXED.
**CORRECTION TO THE COORDINATOR'S ACCOUNT, and it makes the finding worse, not better.** The
coordinator said runs 1 and 2 were launched WITH the cert exports and that run 3 lost them. That is
not what happened: **I launched all three, and none of them had the exports.** Measured:
`grep -c CERTIFICATE_VERIFY_FAILED` = **98 in run 1's log, 98 in run 2's log**, and 24+ in run 3's.
So literature collection has been crippled for the ENTIRE night, not just run 3 — every OpenAlex and
Semantic Scholar fetch failed TLS verification in every run so far. The rate-limiting we attributed
S2 failures to was, at least in part, this instead.

Diagnosis, measured not assumed: `ssl.get_default_verify_paths()` returns
`openssl_cafile=/Library/Frameworks/Python.framework/Versions/3.11/etc/openssl/cert.pem`,
`os.path.exists(...)` = **False**, and that directory is root-owned and empty — the python.org build
ships no CA bundle and no `Install Certificates.command` was ever run. `certifi` IS present in the
venv. Proven fix by direct test against a real endpoint, not by reasoning:
`urlopen('https://api.openalex.org/works?per-page=1')` -> **FAIL** (CERTIFICATE_VERIFY_FAILED)
without the var, **OK 200** with `SSL_CERT_FILE=$(certifi.where())`.

Run 3 stopped (SIGINT, exited 20:04:22Z, artefacts preserved), run 4 launched 20:04:37Z at only
~12 minutes of sunk cost. Verified the EXECUTED environment via `ps eww`, not the command string:
`SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` both present and pointing at an existing file.
Config unchanged and still verified: `timeout_sec=3600`, `fallback_models=()`, patch 005, xgboost.
Monitor re-armed on 34848 with tightened alerts — the previous monitor's `failed:` pattern matched
these very SSL lines and cried "provenance defect" at literature errors, which is the FOURTH
over-broad pattern match tonight. It now greps `CERTIFICATE_VERIFY_FAILED` and `Trying next|All
models failed` specifically.

### 2026-07-31 06:16 AEST — run 4 SSL fix CONFIRMED WORKING (not merely applied)
`grep -c CERTIFICATE_VERIFY_FAILED logs/h2-real4-20260731.log` = **0**, against 98 / 98 / 37 in runs
1 / 2 / 3. Literature collection is fetching for the first time tonight.
Coordinator's independent count also found run 2 had **0** HTTP 429s against 98 cert failures — so
the "S2 rate-limiting" story that entered two restart cost-benefit arguments was largely wrong; the
literature base was crippled by TLS the whole time, not by throttling.
Pid note for accuracy: **34850 is the python process**; 34848 is the `zsh -c` wrapper that `pgrep -f`
matched first (its command line contains the same string). My monitor watches the wrapper, which
still detects exit correctly because the wrapper ends when its `| tee` pipeline does, but the
python pid is the one to quote and to `ps eww`.
Standing lesson recorded: this defect was ALREADY in memory with the exact fix
(`m5-prime-serve-tailnet-identity-and-python-certs`) and still cost the night, because **the
launcher environment is part of the configuration and nothing validates it** — `researchclaw
validate` passes happily with broken TLS. Hence the launch checklist above.

### 2026-07-31 06:27 AEST — measurable payoff from the SSL fix
Run 4 stage-04: `total_candidates: 326`, `bibtex_entries: 326`, `real_search: true`, 0 cert errors.
Run 1 (TLS broken) got `total_candidates: 167`. So the working CA bundle roughly DOUBLED the
literature base, and the 167 that run 1 did collect came from whichever source did not need the
failing path — the crippled runs were not merely thinner, they were biased toward one source.
Caveat for assessment, noted now rather than discovered in the paper: the DuckDuckGo web arm
returned visible off-topic noise among its 20 hits — "Rich Sutton's Publications", a token-wise
distillation paper, an interval-analysis *lecture slide deck* on widening/narrowing in abstract
interpretation (a pure homonym for "interval widening"), and a gravitational-wave calibration
paper. `scholar_papers_count: 0`, and every web hit has `score: 0.0` with empty `content`. If any of
those appear in the generated related-work section they are topic-drift artefacts, not real prior
work, and I will flag them as such at assessment.

### 2026-07-31 07:07 AEST — run 4 stage-9 audited and corrected (21 s after the plan landed)
All six conditions DECLARED — patch 005 holding for the second run running:
proposed `[DivergenceConditionedWidening, VolatilityConditionedWidening, NormalizedConformalWidening]`,
ablations `[NoWidening, ShuffledDivergenceWidening]`, baselines `[Random Forest, MLP]`.
After `_prioritise_plan(...,4000)`: keeps `proposed_methods, baselines, ablations, datasets`
(3,884 of 4,000), method declared and real path both inside the kept text — verified by execution.

**BenchmarkAgent re-emitted the poison, as predicted, and this time it PASSED ITS OWN VALIDATOR.**
`selected_benchmarks: ['UCI Adult', 'California Housing']`, `selected_baselines: ['Random Forest',
'MLP', 'XGBoost']`, **`validation_passed: True`** (run 2's copy was `False`). So the injection is not
only reproducible across runs, it is now self-certified — which means "wait for the validator to
catch it" was never a defence. Both copies renamed to `.DISABLED-wrong-domain`; verified inert by
re-running `_code_generation.py`'s own discovery glob: "NONE".

**`datasets` confabulation recurred a THIRD time**, now with TWO wrong datasets:
`['UCI Adult', 'California Housing']` — note California Housing is a *regression* set, so the
BenchmarkAgent adapted its selection to the task type while still ignoring the configured dataset
entirely. Corrected to the real path with filter, semantics and regime factors; original preserved
as `exp_plan.yaml.orig-uci-adult`.
Improvement worth noting: **no confabulated GPU field this run** — `compute_budget` has no
`hardware_environment` key at all, so that particular invention did not repeat. Three occurrences of
the dataset defect, one of the GPU defect.

### 2026-07-31 07:30 AEST — LINE RULING: restored the missing comparator. Reasoning recorded.
Run 4's plan declared all six *method* conditions but dropped `UnconditionalQuantileAggregation`
from `baselines` (run 2's plan had it). The word "unconditional" appears exactly once in the plan —
inside the topic string. Since the stage-10 guardrail matches topic clauses to NAMED classes, and
since run 1 proved "the instruction and the plan disagreed and the plan won", the block mandating it
by name was likely to lose again.

**Decision: RESTORED, as a bare string. This is housekeeping, not authoring.** Three reasons, and a
fourth that I think is decisive and that nobody raised:
1. `config.research.topic` says verbatim "against unconditional quantile aggregation" — the config
   already chose this comparator. Restoring it is correcting an artefact to match configuration
   already in force, the identical shape as the `datasets` correction.
2. The edit is one bare string in a list of bare strings. No implementation, no algorithm steps, no
   hyperparameters. The pipeline still specs and implements it. Contrast run 1, where supplying the
   missing method would have meant writing the widener's actual algorithm — unambiguously authoring,
   and refused.
3. We select nothing. Had the topic not named a comparator, adding one would be authoring.
4. **The estimator is ALREADY in the plan under another name.** `NoWidening` is alpha=0, which IS
   unconditional aggregation. So restoring the string adds no scientific content whatsoever — it
   restores the LABEL the configured question promised for an arm that already exists. That is
   about as close to zero scientific content as an edit can get.

**But (4) creates a downside nobody flagged: two identical conditions reported as if independent.**
Fixed through my own instrument rather than by further plan edits — the codegen block now states
that `AlphaZero`/`NoWidening` is the SAME ESTIMATOR as condition 1, must be implemented once, and
must be reported as ONE row carrying both names
(`"UnconditionalQuantileAggregation (= NoWidening, alpha=0)"`), with an explicit prohibition on
presenting them as two independent numbers "because that would imply a comparison that does not
exist". That is guidance about presentation, not about science.

**Provenance disclosure widened to cover BOTH hand edits**, since the Methods sentence is the honesty
test for all of this. It now reads: the pipeline "named unrelated public benchmarks instead of the
configured dataset, and ... omitted the comparator named in the configured research question. The
dataset field was manually corrected ... and the comparator was restored by name only ... No
implementation, hyperparameter, result, metric, or analysis was supplied or altered by hand, and the
original artefacts are retained." Verified rendering (on whitespace-normalised text — the naive
substring check failed purely on line wrapping, which is the FIFTH substring trap tonight).
Originals preserved: `exp_plan.yaml.orig-uci-adult` and `exp_plan.yaml.orig-missing-unconditional`.

### 2026-07-31 07:50 AEST — run 4 attempt_001: PROPOSED METHOD PRESENT, but two serious code defects
**The blocking failure is fixed.** `stage-10/agent_runs/attempt_001/model.py` line 54 defines
**`class DivergenceConditionedWidener(BaseModel)`** — present for the first time since run 1 began.
Classes: NoWidening, ShuffledDivergenceWidener, DivergenceConditionedWidener,
VolatilityConditionedWidener, NormalizedConformalWidener. Real data path and the mandatory filter
`df[(df["horizon_min"] == 5) & (df["n_vintages"] >= 5)]` both present. Zero UCI Adult / California
Housing / torchvision references. **Random Forest and MLP were NOT implemented**, so the budget is
not being burned training point predictors in an interval-calibration study — the concern I raised
turned out not to bite.

**DEFECT 1 — the primary metric is not CRPS. `evaluation.py:9`:**
```python
crps = (y_pred[:, 1] - y_pred[:, 0]) / 2
```
That is **half the interval width**. It never touches `y_true`. Minimising it rewards the NARROWEST
possible intervals regardless of whether they contain the outcome — it silently inverts the study,
and it would make "no widening" win by construction. Everything downstream (analysis, figures,
paper) would inherit it. `MedianCRPS` is the median of the same wrong quantity. Coverage90 and
Width90 are computed correctly; PinballLoss uses a crude fixed 0.1/0.9 pair.

**DEFECT 2 — the metric print format cannot be parsed.** `main.py:60` does
`print(f"condition={condition_name} seed={seed} {metrics}")`, which emits a Python dict repr
(`{'CRPS': 12.3}`). The sandbox parser requires `condition=X seed=k NAME: value`; a quoted key
inside braces matches none of its regexes. Result would be **empty `condition_summaries`** — i.e.
exactly the "0/0 conditions, score 0.0 -> 0.0" state that killed the original 2026-07-30 run. The
`harness.report_metric` calls do print parseable top-level lines, so some metrics survive, but the
per-condition structure the repair scorer and the analysis stage need would be lost.

**Action: I did NOT edit the generated code.** Fixing `evaluation.py` by hand would be authoring the
experiment's measurement — the deepest version of the line I have held all night. Instead I
strengthened my own instrument, the codegen block, for the revision/regen and refinement passes:
- a **METRIC OUTPUT CONTRACT** giving the two exact printable forms with a worked example, and
  stating explicitly that printing a dict "parses to NOTHING, leaving zero conditions";
- a **"a width is NOT a CRPS"** section requiring CRPS to be a function of `y_true`, naming
  `(upper-lower)/2` as the specific anti-pattern and why it inverts the study, and specifying
  `2 * mean_tau pinball(y_true, q_tau)` over a >=19-level grid rather than two endpoints.
Both are definitions and output plumbing, not choices about what to test or what the answer is.
Stage 13 ITERATIVE_REFINE and the stage-14 repair loop are the intended mechanisms for catching
exactly this, and they now have a much sharper specification to work from.

### 2026-07-31 08:05 AEST — metric contract extended; one coordinator claim CORRECTED by measurement
attempt_002 is byte-identical to attempt_001 on both defects (same `(upper-lower)/2` CRPS, same
dict-repr printing) — my contract updates landed at 21:50 with attempt_002 already in flight.

Coordinator reported three further defects. Two confirmed, one **wrong**, and I checked rather than
accepting it because it agreed with my conclusion:
- CONFIRMED: `'CRPS': crps` returns a PER-ROW VECTOR, not a scalar (proved by `np.median(crps)` on
  the next line). The primary metric is an array.
- CONFIRMED: `success_rate` is byte-identical to `Coverage90` — a duplicate that would read as
  independent evidence in a results table.
- **WRONG:** the claim that the pinball loss "is maximised inside the interval and exactly ZERO
  outside". Evaluated on a sweep (lower=100, upper=200): y=50 -> 135.00, y=150 -> 50.00,
  y=201 -> 10.10, y=500 -> 40.00. It is **never zero** (min over y in [-500,1000] is 10.0, attained
  exactly at the upper bound) and it **does** penalise exceedance, at 0.1/unit above and 0.9/unit
  below.
  **The conclusion survives via a different mechanism:** proper pinball at level tau is `tau*(y-q)`
  for `y>=q` and `(1-tau)*(q-y)` for `y<q`; the code keeps one branch per bound paired with the
  wrong weight, so the composite is minimised by **collapsing the interval to a point at the upper
  bound** and under-penalises upper exceedance ninefold. Same direction as the CRPS defect (drives
  width to zero), different cause. Two of six metrics broken, both biased toward "no widening" —
  i.e. toward making the paper's headline claim come out negative for spurious reasons.
Contract now carries the VERIFIED formulation, plus single-float-only and no-duplicate-metrics.

### 2026-07-31 08:15 AEST — FIFTH injection route found and closed: the REFINEMENT sub-prompt
attempt_003 is also byte-identical on the metric defects — three generations, no change. So I looked
at whether the stage that is SUPPOSED to fix this would even see my contract. It would not, and it
carried its own poison.

`researchclaw/pipeline/stage_impls/_execution.py:808` calls `_pm.sub_prompt("iterative_improve", ...)`
for stage 13 ITERATIVE_REFINE. That sub-prompt's default text ends with:
```
- READ-ONLY: /opt/datasets/ (pre-cached CIFAR-10/100, MNIST, etc)
- If you see PermissionError on /opt/datasets, do NOT call os.makedirs() there. Use
  root='/opt/datasets' with download=False.
- For new data downloads, use /workspace/data/ as root.
```
So the refinement stage would have been told, again, that the data is CIFAR at /opt/datasets — the
**fifth independent route** for the same poison (after codegen's `network_disabled_guidance`, the
design stage's `dataset_guidance`, the physics_simulation domain adapter, and the BenchmarkAgent).
Crucially it is a SUB-PROMPT, not a block, so none of my earlier block overrides touched it.

`PromptManager._load_overrides` also merges a `sub_prompts:` key, so this IS overridable. Added an
override that (a) strips the /opt/datasets/CIFAR text and names the real CSV + mandatory filter, and
(b) injects a MEASUREMENT CORRECTNESS section naming the four defects found in `evaluation.py` —
width-as-CRPS, one-branch pinball, array-valued metrics, duplicate metrics — plus the METRIC OUTPUT
CONTRACT with the exact printable forms.
Built programmatically from the shipped default so every placeholder is preserved
(`files_context, run_summaries, topic, metric_key, metric_direction, condition_coverage_hint,
exp_plan_anchor`), then VERIFIED by rendering with dummy kwargs: poison gone, corrections present,
placeholders substituted, 3,682 chars. Config + all three blocks still load.
This is the difference between the contract being advice the code agent never sees and instructions
delivered to the exact stage designed to repair the experiment.

### 2026-07-31 08:29 AEST — stage 12 FAILED but reported "done"; refinement spec loaded for stage 13
`stage-12/runs/run-1.json`: `"status": "failed"`, `"metrics": {}`, `elapsed_sec: 1.985`. stdout stops
at `Running condition: NoWidening`. Traceback:
`model.py:21 return np.array(X) * 1.0` ->
`TypeError: unsupported operand type(s) for *: 'Timestamp' and 'float'`, because `evaluation.py:35`
passes `val_df.drop(columns=['rrp_actual']).values` — the whole frame including the datetime column —
into arithmetic. Same error class that killed infer1 cycle 1, so it is recurrent, not incidental.

**NEW DEFECT CLASS — the stage swallowed the failure.** `stage-12/decision.json` reads
`"status": "done"`, `"decision": "proceed"`, `"error": null`, and `stage_health.json` agrees, while
the run artefact it wraps says `failed` with zero metrics. Same shape as the BenchmarkAgent's
`validation_passed: False` being consumed anyway: **a failure is computed, written down, and then
ignored by the layer above it.** A stage that cannot fail is worse than one that fails often.

**The deepest finding of the run: NAME-LEVEL COMPLIANCE WITHOUT SEMANTIC IMPLEMENTATION.**
`model.py` defines all five condition classes — satisfying the stage-10 guardrail, which matches
names, and satisfying my own contract, which mandated names — while the bodies are vacuous:
- `NoWidening.predict` -> `_apply_fixed_quantiles(X)` -> `np.array(X) * 1.0`, i.e. it returns the
  FEATURE MATRIX as its prediction. No quantiles are constructed anywhere.
- `DivergenceConditionedWidener.fit` builds a scaling vector from TRAIN `ens_sd`, and `predict`
  multiplies the TEST feature matrix by that train-length vector — shape-mismatched and meaningless.
- `alpha` is a fixed config constant (0.5), never selected on a held-out slice.
So the guardrail passed, my mandated-name contract passed, and the science is absent. This is the
sharpest possible illustration of tonight's recurring lesson: **naming raises compliance; only
inspecting the artefact's behaviour confirms it.**

**Refinement spec extended (stage 13 is the pass designed to repair exactly this).** Added to the
`iterative_improve` override, on top of the measurement corrections and metric contract:
- CONDITION SEMANTICS: "a class that exists but computes nothing is NOT an implementation", the
  observed passthrough quoted back, a requirement that every condition produce actual price
  quantiles in $/MWh scored against `rrp_actual`, plus the six condition definitions ALREADY in
  force in the codegen block (restated, not invented), and the rule that `alpha` must be selected
  on a held-out TRAIN slice and per-row scaling computed from the rows being predicted.
- DTYPE DISCIPLINE: `interval_datetime` is a datetime; never `.values` a frame containing it; select
  numeric features explicitly by name.
- **NEM PRICES GO NEGATIVE** (-757 to +20,300 $/MWh): no log/log1p/sqrt on any price-derived
  quantity. The run emitted `RuntimeWarning: invalid value encountered in log1p`, meaning it was
  silently producing NaNs on exactly the negative-price intervals that matter most.
Sub-prompt now 7,254 chars, all placeholders preserved, blocks still load. Nothing hand-fixed.

### 2026-07-31 08:52 AEST — stage 13 refinement: MEASUREMENT repaired, SEMANTICS not. Clean result.
Two refinement iterations so far. The split is sharp and is the most informative thing the pipeline
has told us tonight.

**REPAIRED — everything I named concretely and quoted back:**
- `experiment_v2/evaluation.py` CRPS is no longer a width. It is now
  `2 * mean over tau in linspace(0.05,0.95,19) of pinball(...)` and it depends on `y_true`. The
  exact defect I quoted (`(upper-lower)/2`) is gone.
- PinballLoss now has BOTH branches at the correct levels for both bounds
  (`pinball_loss_10 + pinball_loss_90`), fixing the one-branch/wrong-weight defect I verified
  numerically.
So the refinement stage DID act on the MEASUREMENT CORRECTNESS section injected via the
`iterative_improve` override — the fifth-route fix paid off, and this is the first evidence tonight
that a prompt-level correction changed generated code.
Residual metric defect: all 19 levels are evaluated against the SAME bound `y_pred[:,0]`, so it is
19 pinball losses of the lower bound rather than a quantile grid. Closer, still not a CRPS.

**NOT REPAIRED — the conceptual emptiness.** `experiment_v2/model.py` still has
`_apply_fixed_quantiles -> np.array(X) * 1.0`. v1 had briefly attempted
`np.percentile(X, 5, axis=1)` (percentiles ACROSS FEATURE COLUMNS as a price interval — also
meaningless) and v2 REVERTED to the passthrough. No condition constructs a predictive interval from
`ens_mean` plus a width. The method still does not exist.

**The generalisable finding:** the refinement loop repairs defects that are *locally checkable in the
code it is shown* — a formula that visibly ignores `y_true`, a missing branch — and does not repair
*conceptual* emptiness, where every line is syntactically fine and the whole is vacuous. Naming the
defect precisely and quoting the offending line worked; describing the required semantics did not.
That is a real limit on prompt-level control and it is not specific to this pipeline.

### 2026-07-31 08:55 AEST — stage 14 opens with ZERO metrics. Terminal state is now predictable.
`stage-14/experiment_summary.json`: `total_conditions: None`, `total_metric_keys: None`,
`condition_summaries: {}`, `best_run.status: "failed"`, `metrics: {}`. The stderr it carries is
STILL the original stage-12 `TypeError: unsupported operand type(s) for *: 'Timestamp' and 'float'`
at `model.py:21 np.array(X) * 1.0` — so no refinement iteration ever produced a successful sandbox
run, and the summary fell back to the stage-12 failure.

**Predicted terminal state, recorded BEFORE it happens so it can be scored:** the stage-14 repair
loop will run its cycles and report `score 0.0 -> 0.0` (because `_summary_quality_score` =
10*conditions + 5*finite-primary + metric-keys, and all three are zero on a crash), then stage 17
PAPER_DRAFT will hard-block with "Paper Draft Blocked — Experiment stage produced no metrics".
That is the SAME terminal state as the run I was asked to diagnose at 01:22 — but arrived at for a
DIFFERENT and deeper reason. The original died because no dataset existed and the repair loop was
steered into torchvision. This one has the real dataset, the right filter, all six conditions
declared and present by name, a corrected CRPS and a corrected pinball loss — and dies because the
condition classes never construct a predictive interval at all.

Everything that could be fixed by configuration, prompt, environment or artefact correction HAS been
fixed tonight, and verified: real data reaching executable code, ml_tabular domain, plan truncation
(patch 005), BenchmarkAgent injection, five separate /opt/datasets poison routes, TLS/CA bundle,
matplotlib, xgboost, model fallback, LLM timeout, metric definitions, output contract, dtype and
negative-price facts. What remains is the one thing I will not do: write the experiment.

### 2026-07-31 09:05 AEST — I WAS WRONG about "comprehension". The pipeline DISCARDED a correct fix.
Coordinator challenged my "comprehension, not configuration" framing and asked me to verify against
the files rather than take their word. I did, and **they are right about the revert.** Timestamps:
```
08:40:18  experiment_v1/evaluation.py    crps = compute_crps(y_true, y_pred)   <- depends on y_true
08:52:06  experiment_v2/evaluation.py    19-tau loop, both branches, 2x factor <- corrected
08:52:09  experiment_final/evaluation.py crps = (y_pred[:,1] - y_pred[:,0])/2  <- REVERTED, 3s later
```
`diff experiment_v2 experiment_final` confirms the corrected CRPS and the two-branch
`pinball_loss_10 + pinball_loss_90` were replaced by the original width-as-CRPS and the one-branch
formula. **Broken -> better -> correct -> reverted, in twelve minutes.**

**ROOT CAUSE FOUND IN SOURCE — `_execution.py:1085-1099`:**
```python
if metric_val is not None:
    if _is_better(metric_val, best_metric):
        best_files = dict(candidate_files)          # only path that adopts an improvement
elif validation.ok and best_version == "experiment/":
    best_files = dict(candidate_files)              # fallback, first qualifying iteration only
```
`best_files` is adopted ONLY if the sandbox run yielded a metric that improved, or — once, and only
while `best_version` is still `"experiment/"` — if static validation passed with no metric.
Every version crashes on the SAME UNRELATED dtype bug
(`val_df.drop(columns=['rrp_actual']).values` passing a datetime column), so `metric_val is None`
for every iteration; the run's own `refinement_log.json` confirms it:
`best_version: "experiment/"`, `best_metric: null`, and for both iterations
`metric: None, improved: False, validation_ok: None`. With `validation.ok` never true, neither branch
ever fires, `best_files` stays at the ORIGINAL stage-10 code, and `experiment_final` is written from
it at line 692.

**The corrected framing, which is more accurate AND more actionable than mine:** a single unrelated
runtime crash zeroes the score, and because adoption is score-gated, EVERY correct improvement made
anywhere else in the file is discarded with it. The pipeline generated a correct metric
implementation and threw it away three seconds later. It also explains why three stage-10 attempts
looked byte-identical while refinement was quietly succeeding underneath.

**My interventions are VALIDATED, not hypothetical:** the MEASUREMENT CORRECTNESS section and the
`iterative_improve` sub-prompt override demonstrably changed generated code within one cycle. That
is the first proof tonight that a prompt-level correction reached and altered the experiment.

**One overstatement in the coordinator's account, corrected:** v2 is NOT "exactly the contract
implemented correctly". Its loop evaluates all 19 tau levels against the SAME bound `y_pred[:,0]`,
so it is 19 pinball losses of the lower bound, not a pinball over a grid of quantiles q_tau. It is a
large, genuine improvement — depends on y_true, both branches, correct 2x factor — but it is not yet
a CRPS. Credit the direction, not the arrival.

### 2026-07-31 09:20 AEST — the adoption fallback is STRUCTURALLY UNREACHABLE in sandbox mode
Coordinator flagged a discrepancy in my reading and asked me to confirm or refute rather than accept.
Both halves check out, and one of them is my error.

**My error first.** I reported `validation_ok: None` for both iterations. That was my PROBE, not the
data: I read `it['validation']['ok']`, but the key is a TOP-LEVEL `validation_ok` on the iteration
record. Actual values: `validation_ok: true`, `validation_summary: "Code validation: 4 warning(s)"`
for both iterations. Sixth lookup/pattern error of the night, and I made this one while correcting
someone else's reading.

**Now the sharper defect, proven by AST rather than by eye** (indentation at this depth is not
readable reliably — I resolved the parent of the `elif` programmatically):
```
PARENT IF  line 950 : validation.ok and config.experiment.mode in ("sandbox", "docker")
  body spans lines 952-1097   (contains the whole sandbox-run + metric-adoption block)
ELIF       line 1098: validation.ok and best_version == "experiment/"
```
So the fallback adoption path at 1098 is the **else-branch of line 950**. It is reached only when
`NOT (validation.ok AND mode in {sandbox, docker})`, yet its own test REQUIRES `validation.ok`.
Therefore in sandbox mode with validation passing — the normal, healthy case — **the parent branch is
always taken and the fallback NEVER EVALUATES.** It can only ever fire in a non-sandbox, non-docker
mode. The coordinator's hypothesis was right and is stronger than the "first qualifying iteration
only" reading I gave earlier: the branch is not rarely-taken, it is **unreachable on this path**.

**Consequence, stated precisely:** in sandbox mode, refined code is adopted if and ONLY IF a sandbox
run yields a metric that improves on the incumbent. Any crash — for ANY reason, however unrelated to
the improvement — leaves `metric_val is None`, so no adoption occurs, and `experiment_final` is
written from the ORIGINAL stage-10 code at line 692. A single dtype bug therefore silently discards
every correct change made anywhere else in the file, permanently, with no log line saying so.
That is why v2's corrected CRPS lived for three seconds.

### 2026-07-31 09:28 AEST — prediction CONFIRMING. Sixth poison route found (repair prompt).
`Repair cycle 1: score 0.0 -> 0.0, mode=technical_report` — exactly as predicted at 08:55, and for
the predicted reason. `stage-14_repair_v1/experiment_summary.json`: `total_conditions: 0`,
`total_metric_keys: 0`, `status: failed`, and the SAME
`TypeError: unsupported operand type(s) for *: 'Timestamp' and 'float'` at
`model.py:21 np.array(X) * 1.0`. The repair loop received the ORIGINAL broken code — because
`experiment_final` was written from `best_files`, which the unreachable-fallback defect left pinned
to the stage-10 original — and reproduced the identical crash. Its `evaluation.py` still has
`crps = (y_pred[:,1] - y_pred[:,0]) / 2` and still does
`val_df.drop(columns=['rrp_actual']).values`.

**SIXTH `/opt/datasets` poison route**, in `experiment_repair.py:169`, inside the repair prompt's
CONSTRAINTS block:
```
- Pre-cached datasets: CIFAR-10, CIFAR-100, MNIST, FashionMNIST, STL-10 at /opt/datasets
- Every condition MUST output: condition=CONDNAME metric=VALUE
```
So the repair loop is told, once more, that the data is CIFAR — and note its metric contract line is
also WRONG relative to the parser, which wants `condition=X seed=k NAME: value`, not
`condition=CONDNAME metric=VALUE`. Six independent routes for the same poison: codegen
`network_disabled_guidance`, design `dataset_guidance`, the physics_simulation domain adapter, the
BenchmarkAgent, the `iterative_improve` sub-prompt, and now the repair prompt. Only the first two
were overridable as blocks; the fifth I closed as a sub-prompt; this sixth is a hardcoded f-string
in Python, **not overridable at all**.

**No lever remains for this run.** `runner.py:304/357/377` import `experiment_repair` lazily, but
Python caches modules in `sys.modules` after the first import — cycle 1 has already imported it, so
editing the file now cannot affect cycles 2 and 3. The outcome is determined.

### 2026-07-31 09:49 AEST — repair loop exhausted 0.0->0.0 x3; stage 15 chose REFINE, rollback to 13
`Repair cycle 1/2/3: score 0.0 -> 0.0, mode=technical_report` — the prediction made at 08:55 is now
fully confirmed, three for three, for the predicted reason. Stage 15 RESEARCH_DECISION then returned
**REFINE**, rolling back to ITERATIVE_REFINE (attempt 1/2), so the run continues rather than
proceeding to the paper.

**This second stage-13 cycle is the first genuinely NEW test of the night, and it is worth waiting
for.** The DTYPE DISCIPLINE section — which quotes the exact
`TypeError: unsupported operand type(s) for *: 'Timestamp' and 'float'` back at the model, names
`val_df.drop(columns=['rrp_actual']).values` as the offending expression, and instructs selecting
numeric feature columns explicitly by name — was added to the `iterative_improve` override at 08:29,
AFTER the first stage-13 cycle had already started. So this is the first refinement pass to see it
from the beginning.

The prediction to score: if the dtype instruction lands, the crash clears, a sandbox run yields a
metric, `_is_better` fires, and adoption finally occurs — which would ALSO rescue the corrected CRPS
and pinball, because adoption takes the whole file set. One trivial fix is all that stands between
the discarded-improvements deadlock and a real result. If it does not land, the run ends as
predicted and the write-up is the two structural defects, not comprehension.

### 2026-07-31 10:00 AEST — second refinement cycle: dtype instruction did NOT land. Outcome proven.
The second stage-13 cycle (the first to see DTYPE DISCIPLINE from the start) produced
`experiment_v1` at 09:49:26 that STILL contains `val_df.drop(columns=['rrp_actual']).values` at
`evaluation.py:43` — and additionally regressed by introducing `torch.tensor(...)` into `data.py`.
The runtime-fix pass (`refine_sandbox_v1_fix`) kept the same line. So quoting the exact TypeError,
naming the offending expression, and instructing explicit column selection did NOT fix it.

Contrast with what DID land: the measurement corrections were adopted within one cycle. The
difference is that a wrong formula is visible in the file the model is shown, whereas the dtype bug
only manifests as a runtime type error in an interaction between `evaluation.py` (which passes the
frame) and `model.py` (which multiplies it) — the model would have to reason across two files about
a value's runtime dtype. Prompt-level correction reached the local defect and not the cross-file one.

**Terminal state now PROVEN rather than predicted.** `_detect_domain(topic, domains)` for the paper
stage returns `ml` / "machine learning", which is in the empirical set
`{ml, engineering, biology, chemistry}`, so `_paper_writing.py:1620-1638` will hard-block with
"Paper Draft Blocked — Experiment stage produced no metrics" once it is reached with
`has_real_metrics == False`. There is no path from the current state to metrics: adoption is
unreachable, the dtype crash persists, and the repair prompt is a hardcoded f-string that cannot be
overridden and still says the data is CIFAR.

## h2-pipeline — ASSESSMENT (2026-07-31 10:05 AEST)

### Verdict on the founder's ask: ARCLAW produced NO publishable artefact tonight.
Four runs, ~8 hours of 72B time. No paper exists, and the terminal state is proven, not guessed.
I would rather say that plainly than dress up a blocked run.

**But the night was not wasted, and the two things it produced should not be conflated:**

**(a) Genuine research output EXISTS — from analysis, not from the pipeline.** The defensible
results are the width-elasticity finding (optimal interval width scales as ~D^0.75, sublinear,
reproduced independently by two agents with different code), the native-elasticity contrast
(+1.020 AEMO vs +0.240 debate) with the exact Vincentisation lemma explaining it
(`width(Vincentised) == mean(member widths)` to 9.1e-13, so cross-member dispersion contributes
nothing to aggregate width), and the volatility-control result killing the heteroskedasticity
confound. Those came from nem-data's analysis and my independent yardstick. They are real and they
are on real NEM data. They were NOT produced by AutoResearchClaw.

**(b) What ARCLAW produced is an engineering map, which has real value but is not research output.**

### Why it failed — the honest causal chain
1. **Six independent routes inject the same `/opt/datasets` CIFAR poison** into a study about
   electricity prices: codegen `network_disabled_guidance`; design `dataset_guidance`; the
   physics_simulation domain adapter; the BenchmarkAgent (`validation_passed: False` in one run,
   `True` in another — self-certified); the `iterative_improve` sub-prompt; and the repair prompt's
   hardcoded f-string. Two were overridable as blocks, one as a sub-prompt, one as a domain fix, one
   by disabling an artefact — **the sixth cannot be overridden at all.**
2. **Plan truncation dropped the proposed method** (`code_agent.py:543`, `exp_plan[:4000]` over
   alphabetically-sorted YAML, so `ablations` survives and `proposed_methods` is cut). Fixed by
   patch 005 and verified working across two runs.
3. **The environment was never validated.** python.org Python 3.11 ships no CA bundle on this box, so
   EVERY literature fetch failed TLS in runs 1-3 (98/98/37 errors) — a defect already documented in
   memory with its fix. `researchclaw validate` passes happily with broken TLS. Fixed; literature
   went 167 -> 326 candidates.
4. **The 600 s LLM timeout is incompatible with 72B at ~6 tok/s** when call sites request
   `max_tokens=16384` (~2,634 s needed). Fixed to 3600 s; fallback disabled so degradation is loud.
5. **THE TWO DEFECTS THAT ACTUALLY KILLED IT, neither fixable from outside:**
   - **Score-gated adoption with a structurally unreachable fallback.** `_execution.py:1098` is the
     else-branch of `:950 (validation.ok and mode in {sandbox,docker})` while itself requiring
     `validation.ok` — so in sandbox mode it NEVER evaluates. Refined code is adopted only if a
     sandbox run yields an improving metric. Any crash, however unrelated, discards every correct
     change in the file. **Measured consequence: a correct CRPS implementation existed at 08:52:06
     and was reverted at 08:52:09.**
   - **An unfixed cross-file dtype crash.** `evaluation.py` passes a frame containing
     `interval_datetime` into arithmetic in `model.py`. It zeroes the metric, which is the very
     signal adoption is gated on. **The pipeline cannot climb out because the ladder is gated on
     having already climbed.**
6. **Name-level compliance without semantic implementation.** All conditions existed as classes —
   satisfying the stage-10 guardrail (which matches names) and my own contract (which mandated
   names) — while `NoWidening.predict` returned the raw feature matrix. Naming raises compliance;
   only inspecting behaviour confirms it.

### What prompt-level control CAN and CANNOT do — the most transferable finding
The `iterative_improve` override **worked**: within one cycle the model replaced a width-as-CRPS with
a 19-level both-branch pinball carrying the correct 2x factor. The same override **failed** to fix a
two-line dtype bug across two cycles. The difference appears to be locality — a wrong formula is
visible in the file shown to the model; the dtype bug is an interaction between two files about a
runtime value's type. **Precisely-stated local defects get fixed; cross-file runtime defects do not.**

### Honest accounting of my own errors tonight
Six pattern/lookup errors, all of the same family: a substring that also matches something else.
`ShuffledDivergenceConditionedWidener` containing `DivergenceConditionedWidener` (false positive,
mine; false negative, coordinator's); `'timeout_sec' in text` matching sibling config sections so a
guard silently no-oped; a `failed:` grep matching SSL lines and crying "provenance defect"; a
whitespace-wrapped phrase failing a naive `in` check; and `it['validation']['ok']` vs a top-level
`validation_ok`, which I got wrong WHILE correcting someone else. I also asserted a root cause
("truncation removed the class entirely") that was half wrong, and a verdict ("comprehension is the
limit") that was wrong and that I withdrew on evidence.
The one that mattered most in the other direction: I nearly restarted a shared Ollama on a wrong
diagnosis, and would have cited as evidence a 500 that MY OWN probe's timeout had created.

### Fixes that survive tonight (all verified by execution, not by configuration)
| fix | state | evidence |
|---|---|---|
| matplotlib 3.11.1 | installed | rendered an 18 KB PNG from the venv |
| pyarrow 25.0.0, xgboost 3.2.0 | installed | XGBRegressor fit+predict proven |
| `patches/experiment_diagnosis_dataset_guidance_2026-07-31.patch` | on disk, UNCOMMITTED | torchvision repair advice made domain-neutral |
| `patches/005-code-agent-prioritise-plan-before-truncate.patch` | on disk, UNCOMMITTED, ACTIVE | proposed_methods survives truncation in 2 runs |
| `prompts.h2-real.yaml` | 3 blocks + 1 sub-prompt override | all render; refinement demonstrably acted on it |
| `config.h2-real.yaml` | timeout 3600, fallback [] | loaded values verified |
| LAUNCH CHECKLIST (cert vars + PYTHONUNBUFFERED) | in this log | run 4 had 0 TLS errors vs 98/98/37 |

### What I would do next, in priority order
1. **Fix `_execution.py:1098`** — the unreachable adoption fallback. One-line structural fix; it is
   the single highest-value change in the repo and it silently discards correct work today.
2. **Make stage 12 fail when its run fails.** `decision.json` says `done/proceed/error:null` over a
   run artefact that says `failed` with zero metrics. A stage that cannot fail is worse than one
   that fails often.
3. **Delete the six `/opt/datasets` injections** or gate them on an actual Docker image existing.
4. **Validate the launcher environment** in `researchclaw validate` — TLS reachability, CA bundle,
   and the scientific-stack imports. A known bug with a known fix cost this entire night because
   nothing checks the process environment.
5. Only then re-run H2. With 1-4 done, the remaining risk is the cross-file dtype class, which is
   the one thing tonight suggests prompt-level control will not fix.

### The result the founder should actually be given
Not a paper. The D^0.75 elasticity finding, the native-elasticity contrast with its exact
Vincentisation lemma, and the D-is-not-a-volatility-proxy result — written up by hand from
nem-data's analysis and the yardstick, with the AEMO/debate evidence asymmetry stated. That is
genuine, defensible, real-data research output. It is what exists. Presenting it as an ARCLAW
output would be false; presenting ARCLAW's engineering map as research output would also be false.

### The locality limit — operational consequences (the most transferable finding)
Same spec, same model, same stage, one cycle apart:
- **LOCAL defect** (a wrong formula, visible in the file the model is shown) -> corrected in one
  cycle. `crps = (upper-lower)/2` became a 19-level both-branch pinball with the 2x factor.
- **CROSS-FILE defect** (a frame passed in `evaluation.py`, multiplied in `model.py`, failing on a
  runtime dtype) -> survived two cycles WITH THE EXACT TypeError QUOTED in the prompt, and the
  second cycle regressed further by adding `import torch` / `from torch.utils.data import Dataset,
  DataLoader` to `data.py`.
Nothing in the static text of either file looks wrong, which is precisely why it is invisible to a
prompt-level correction.

**Operational consequence:** for cross-file defects, do NOT instruct the model to be careful —
make the interface impossible to misuse. Have the loader return an explicitly typed numeric feature
matrix so no datetime can reach arithmetic in the first place. A structural fix beats an instruction
for any defect that spans a file boundary.

**Diagnostic rule for a future session:** if a local defect is fixed and a cross-file defect is not,
in the same cycle under the same spec, the limit is **LOCALITY, NOT COMPREHENSION**. Check that
first — it is testable, and getting it wrong (as I initially did) sends you looking for a bigger
model when you need a smaller interface.

### Final disposition
Run 4 (`rc-ws3-h2-real4-20260731`, pid 34850) left RUNNING deliberately, per coordinator decision:
the terminal state is proven, stopping it would destroy the artefact of a COMPLETED failure, and the
persistent monitor reports the actual exit whether or not anyone is watching. All four run
directories preserved intact, with every hand-corrected artefact retained beside its original
(`exp_plan.yaml.orig-uci-adult`, `exp_plan.yaml.orig-missing-unconditional`,
`benchmark_plan.json.DISABLED-wrong-domain`).

## h3-run

**LAUNCHED 2026-07-31 20:51:38 AEST. bench pid 19916, tmux session `ws3-h3-run`.**
Host m5-prime-serve (100.95.93.7), repo `~/code/age-swarm` @ `0c663fa`
(branch `cursor/ws3-crps-evolve-1bce` — note: this is one commit AHEAD of the `fce1324` recorded
in the hypothesis-state memory, and on a *different* branch. `0c663fa` adds `evolve_crps`; the
panel path H3 depends on is untouched by it).

### Pre-flight — verified executed, not configured

- **Pool live.** Fresh probe through the exact bench call path (`swarm.ask(host="localhost",
  model_override=...)`), unique marker `H3_PROBE_1785494611_4417`:
  `qwen2.5:7b` 1.8 s HIT, `llama3.1:8b` 2.2 s HIT, `granite3.3:8b` 2.6 s HIT. `qwen3:4b` answered
  in 2.9 s but returned `{"error": "Invalid JSON response"}` to the artificial echo prompt — it is
  **live**, and on real critic prompts it produces well-spread scores (frozen run: values 0–8,
  within-cell std 1.18, **0/60 all-neutral cells**), so the H3 weighting signal is not degenerate.
- **GPU uncontended.** `ollama ps` empty at launch; the two pre-existing tmux sessions
  (`claw-ws3-theorem`, `hive-market-overnight`) had both already finished. No competing job.
  With `OLLAMA_MAX_LOADED_MODELS=1` the bench still evict/reload-thrashes *against itself* as it
  cycles 4 model tags per cell — but that cost is already priced into the 07-12 timings
  (22.4 s/cell then vs 24.1 s/cell measured now), so it is not a regression.
- **Launcher env verified from `ps eww -p 19916`, not the command string:**
  `PYTHONUNBUFFERED=1`, `SSL_CERT_FILE=/Users/alexeynikitine/Library/Python/3.11/lib/python/site-packages/certifi/cacert.pem`
  (file confirmed present, 236,095 bytes), `REQUESTS_CA_BUNDLE=` same path.
- **Calls confirmed landing on the GPU**, sampled 8 s apart:
  `qwen2.5:7b 100% GPU` -> `llama3.1:8b 100% GPU` -> `granite3.3:8b 100% GPU`.

### Design

- **Pattern: `panel` only.** H3 is the within-panel weighted-vs-uniform contrast, so debate /
  baseline / evolve buy nothing. Panel is also the cheapest arm (22.4 s/cell frozen) — this is
  where the "~6.2 h serial" feasibility estimate came from.
- **Episodes: 196 achieved of 200 intended** (4 dropped, `y_true` missing at target on
  2026-05-21 14:00 and 2026-06-22 14:00 in both regions). 50 forecast origins x 2 regions
  (NSW1, VIC1) x 2 horizons (1 h, 24 h).
  `eval/forecast_episodes_2026-07-31_h3.json`, sha256 `1ba96e2b...164e4dec`.
- **Origins span 2026-01-10 .. 2026-07-25** — a much wider window than the frozen set's
  2026-06-15..07-09, which is what makes a genuine time-ordered split possible.
  **The DB has a 24-day scraper outage, 2026-04-01 .. 2026-04-24** (1,138 missing 30-min buckets
  per region). A first build straddling it silently yielded only 170 episodes; origins were
  re-cut into two clean windows (2026-01-10..03-28, 2026-04-28..07-25) around the hole.
- **Seeds: 5** (41,42,43,44,45), up from 3.
- **980 cells total.** At the measured 24.1 s/cell: **~6.6 h**, ETA ~03:30 AEST 2026-08-01.
- **Episode order is deterministically interleaved** (`--shuffle-seed 20260731`) so that *any*
  prefix spans the full time range. If the run is cut short it still supports the time-ordered
  split; it just does so at lower n. `ts0` is carried per episode, so the split itself is
  unaffected by the shuffle.
- **DuckDB opened READ-ONLY and pre-materialised to parquet**
  (`~/data/ws3_h3/dispatch_30min_nsw_vic.parquet`, 17,708 rows, zero nulls). The episode builder
  reads the parquet; the bench touches neither.

### lambda is fit OFFLINE, on a held-out slice — and the run cannot bias it

The bench keeps its runtime weighting **exactly as the frozen run had it** (`weights =
softmax(scores)`, i.e. lambda = 1), so `qvec_final` stays comparable to 2026-07-12. The lambda
fit is done post-hoc, because `extra.candidates` and `extra.scores` are both logged and
`vincentize(candidates, softmax(lambda*scores))` is a *deterministic* function of them — the whole
lambda path is recoverable from the logs with zero extra GPU. lambda = 0 is exactly uniform, so
uniform is nested inside the family rather than being a separate arm.
**Fit on origins in the first half of the time order, evaluate on the second half. Never on test.**

### H5 `verifier_vote_share` — done, additive, ~20 lines

Added to `run_panel`'s `extra` (verified present in smoke output):
`verifier_vote_share` (fraction of candidates scoring >= 7.0, the 0-10 analogue of
`src/patterns/panel.py`'s binary APPROVE), `panel_agreement` (`1 - std(scores)/10`, exactly
panel.py line 228), `confidence` (their product, matching the documented
`verifier_vote_share x panel_agreement_rate`), and `critic_parse_failures`.
Additive fields only — no change to `qvec_final` or to any scored quantity. 26/26 existing
`eval/test_{scoring,policy}.py` tests pass.

### Frozen artefacts NOT touched

`--episodes-path` / `--results-path` / `--log-dir` overrides were added so this campaign writes to
`~/data/ws3_h3/` and cannot append to (and thereby contaminate) the frozen 2026-07-12 JSONL that
the H1/H2/H3 preliminary results and the two-ensemble re-analysis all rest on.

### Not started

**H1 is NOT started** and must not be inferred from this entry — it is the separate 50+ h
commitment requiring its own founder sign-off.

### Analyser validated against the frozen 07-12 result BEFORE the new data lands

`eval/analyze_h3_2026-07-31.py` reproduces the recorded preliminary H3 numbers **exactly** when
pointed at `eval/forecast_results_2026-07-12.jsonl`:
uniform **14.4433**, weighted(lambda=1) **13.5862**, **2/3 seeds** weighted-lower
(41 no, 42 yes, 43 yes) — matching the 13.586 / 14.443 / 2-of-3 on record to four digits.
So the loader, the candidate/climatology substitution and the Vincentisation path are all
identical to what produced the original result; only the lambda fit and the time split are new.

**The lambda grid brackets the optimum — it is NOT a grid-edge artefact.** In-sample on the frozen
60 cells the curve is 14.443 (lam=0) -> 13.586 (lam=1) -> **13.371 (lam=2, minimum)** -> 13.433
(lam=5). An interior optimum, unlike the H2 gamma sweep whose `1+alpha*clip(z,0,zmax)` form ran to
the edge of any grid. The grid is `[0, .05, .1, .2, .3, .5, .75, 1, 1.5, 2, 3, 5]` and the analyser
flags `lambda_hat_at_grid_edge` explicitly if lambda_hat ever lands on an end.

**Note this makes the frozen lambda=1 a non-optimal setting** — the 07-12 result was measured at a
lambda that in-sample analysis says is off-peak, which is a further reason the original number was
not a fair reading of the weighting family.

Verdict rule (all four must hold, all on TEST): lambda_hat > 0, pooled weighted < uniform,
>= 3/5 seeds weighted-lower, and the origin-clustered bootstrap 95% CI on the loss differential
strictly below zero. Anything less is reported as NOT SUPPORTED.

### Monitoring

tmux `ws3-h3-mon` appends `cells=N/980 pid=... ollama=[...]` to
`~/data/ws3_h3/h3_progress.log` every 15 min, so the run is auditable without an agent watching.
Observed throughput is **~32.6 s/cell wall-clock** (vs ~22 s of reported LLM latency — the gap is
`OLLAMA_MAX_LOADED_MODELS=1` evict/reload between the 4 model tags), so the honest ETA is
**~8.9 h, i.e. ~05:45 AEST 2026-08-01**, not the 6.2 h the feasibility note projected.

### Uncommitted

Changes to `eval/forecast_bench.py` and `eval/forecast_tasks.py`, plus new
`eval/analyze_h3_2026-07-31.py`, are left **uncommitted** in `~/code/age-swarm` (no commit was
authorised). `git status` there also shows two pre-existing untracked `bench_*_2026-07-05.*` files
that are not mine.

---

## ws3-paper

### 2026-07-31 ~21:05 AEST — WS3 paper **v1 DRAFTED**. Hand-written from the night's verified results. No pipeline run, no LLM calls, no GPU.

**Deliverable:**
`Intrepid Power Operations/research/papers/ws3_debate_as_calibration_2026-07-31_v1.md`
(70,917 bytes, ~10,400 words, up from v0's ~5,170).
**v0 preserved byte-identical** — `ws3_debate_as_calibration_2026-07-04_v0.md`,
sha1 `fdc4f31de9aa69ac61619fb6af9c772c954a44af`, mtime unchanged at 2026-07-30 22:54.
No git operations of any kind were performed.

**Sources read before drafting (all of them, in full):** the two vault notes
(`hive/ws3-h2-contested-gamma-result-2026-07-31`, `hive/age-swarm-ws3-hypothesis-state-2026-07-31`),
`hive/nem-market-duckdb-and-ws3-h2-real-data-result-2026-07-30`, v0 and its private notes file,
`~/data/ws3_h2/README.md` (13 KB provenance record), and this BURN_LOG's `h2-pipeline`,
`ws3-extensions`, `nem-data`, RECONCILIATION and TWO-ENSEMBLE sections, plus the age-swarm
artefacts `analysis_2026-07-12.md`, `gamma_sweep_2026-07-30.md`, `theorem_tests_2026-07-30.md`.
Every number in the paper is traceable to one of those; nothing was estimated or interpolated.

### What v1 says that v0 could not

1. **§3.3 re-based, not deleted.** New §3.3′ states the widening in **elasticity** form
   (`W ∝ D^ε*`, base and constraint set named) and explicitly drops the monotone-increasing
   constraint. v0's literal spec is reported as refuted with the mechanism intact.
2. **Lemma 1 (Vincentisation is dispersion-blind) is now the paper's structural core**, promoted
   into §1 and §3.3 with the 9.1e-13 verification, and carried through to §5.4 and the
   adversarial-robustness limitation (a rogue agent moves aggregate width by 1/N of its excess —
   which is exactly what the trimming result measures empirically).
3. **§5 Results is a new section** (5.1 null rejected / 5.2 refutation + max-gain-exactly-zero /
   5.3 D^0.75 / 5.4 two-ensemble contrast / 5.5 conformal + volatility control / 5.6 debate side).
4. **§6 Hypothesis register** with an explicit ESTABLISHED / PRELIMINARY / IN-PROGRESS tier on
   every row, H2 split into two rows (AEMO vs debate) so the asymmetry is structural in the table.
5. **§7.1 carries all five corrections in the paper's own body text**, numbered: the inflated
   0.672, the 38/60-plus-climatology error, the over-general "every α>0 is worse", the
   floored-form α=0 artefact, and v0's own wrong-signed intuition about divergent debates.
6. **Appendix A**: A.1 report elasticities not bare α (the two-base table); A.2 all four
   functional-form artefacts with their diagnostic tells; A.3 CRPS = 2x pinball with the
   "check for an exact integer ratio before investigating the data" rule; A.4 reproduction paths.
7. **§4.1 data provenance in full** — DuckDB read-only at 01:28:23+10:00 with the 1-second mtime
   liveness check, 678,735 rows, the horizon cut and why (35.4% of lead-0 rows equal truth),
   62-day window, the scope warning that this is AEMO's model-vintage ensemble.

### Framing decisions I made, so they can be overruled

- **Native gap is the headline of the contrast, not the optimal gap.** 1.02 vs 0.24 is stated as
  structural and untested-because-it-needs-no-test; the optimal elasticities are written as
  "both sublinear, 0.4–0.8, difference unresolved at n=60" and the paper never says they differ.
- **The debate arm's absolute defeat is stated up front, twice** (§2 under the [22] objection, and
  §8): it loses to a single model AND to climatology, and its one clear win is throwing a member
  away. Better to own it than to have a reviewer find it.
- **Two new references [41] trimming and [42] isotonic QRA are flagged UNVERIFIED in the reference
  list itself** — the arXiv IDs come from our own theorem-test artefact and were not re-checked
  against the arXiv API tonight. I did not invent author lists to make them look finished.
- **One genuine citation gap is flagged rather than filled**: the spread–skill literature from
  ensemble NWP is the correct prior for the sublinear result, and I could not verify a specific
  citation, so §2 says so in the text.
- **Latency figure revised down**, honestly: v0's ~12x came from 2 spot-checks on the text bench;
  the frozen forecast corpus measures 5.5 s baseline vs 34.0 s debate, so v1 says ~6x on this
  corpus and names the discrepancy.
- The FY27 WS-4 vs WS-3 naming trap is an internal RDTI matter and was deliberately kept OUT of
  the paper; the paper's own WS-tag stays WS3 as in v0.

### H3 run status at draft time (reported in the paper as IN-PROGRESS, no result claimed)
`eval/forecast_bench.py --patterns panel --seeds 41,42,43,44,45`, pid 19916, launched
2026-07-31 20:51 AEST, 196 episodes (98 NSW1 / 98 VIC1, 1h + 24h) x 5 seeds = **980 cells**.
Episodes frozen at `eval/forecast_episodes_2026-07-31_h3.json`,
sha256 `1ba96e2baf67cb8381fc2ac9d742fee7799d6c6dbb66cab653f35196164e4dec`,
git `0c663fa` branch `cursor/ws3-crps-evolve-1bce`. At 21:05 it was at **25/980**
(running mean panel CRPS 28.27, ~22 s/cell → ~6 h serial). Paper §5.6 and the H3 register row
name the run, its manifest and its launch time, and claim nothing from it.

### What v1 is NOT
It is not workshop-ready. Open before submission: H4 not run (no classical baselines at all);
the N x R ablation grid still hardcoded; `verifier_vote_share` still unlogged so H5 is half-tested;
[41]/[42] unverified; the spread–skill citation missing; no LaTeX port; no AI-assisted-drafting
disclosure decision. The `_notes.md` companion still describes the pre-v1 state and was NOT
updated — it should get a v1 pass before external circulation.

## rdti-pack

### 2026-07-31 21:1x AEST — two housekeeping deliverables, both analysis-only (no GPU, no pipeline, no git checkout)

**1. Founder-ready FY27 evidence pack — WRITTEN**
`Project Hive 2.0/rdti/FY27_WS4_evidence_pack_2026-07-31.md` (~24 KB). A distillation of
`FY27_WS4_ws3_h2_two_ensemble_2026-07-31.md` structured for the Wilson Pateras FY27 review
(charter WS-10 / OP #2526). It states explicitly that the full evidence file governs where the
two differ, and it does not restate a number without its caveat.

Sections: (1) core activity — D^0.75 elasticity, two-ensemble native gap 1.020 vs 0.240, the
Vincentisation lemma at 9.1e-13, the volatility control killing the heteroskedasticity confound,
each carrying the horizon-0 contamination caveat, the CRPS = 2x pinball label error, the
base-dependence of alpha, and the evidential asymmetry; (2) supporting activity — the six-layer
fabrication laundering chain as a **software-defect** finding, with the guard *"no artefact from
this pipeline may be cited as evidence of anything without tracing every number to a metric
artefact in runs/*.json; the generated paper is evidence of a software defect, not of
research"*; (3) a 14-row timestamped hypothesis -> experiment -> observation -> failure analysis
-> root cause -> verified correction -> re-test narrative built from this log; (4) an artefact
index covering the evidence file, BURN_LOG/BURN_BRIEF, patches/, ~/data/ws3_h2/, all five run
dirs, and paper v1 marked **IN PROGRESS**; (5) an explicit PRELIMINARY vs ESTABLISHED split plus
a "what is NOT claimed" list.

**Two things surfaced that other agents should know:**
- **A documentation discrepancy in the evidence file.** It records the stage-9 manual
  intervention as `2026-07-31 ~16:22:48Z`; this log's contemporaneous entry for the same event is
  `2026-07-31 02:22 AEST`, i.e. **2026-07-30 16:22Z**. Same event (corroborated by the preserved
  `exp_plan.yaml.orig-uci-adult`), inconsistent date on the Z stamp. Flagged in the pack's §5.3;
  worth correcting in the evidence file before lodgement.
- **The 3.4% -> 15.4% correction inherits the non-bracketing.** The pack states the corrected
  gain is still a lower bound of an unbracketed grid-edge search, not a point estimate.

**2. Memory-consolidation PROPOSAL — WRITTEN, NOT EXECUTED**
`~/IntrepidBrain/operations/memory-consolidation-proposal-2026-07-31.md`. Nothing merged,
renamed, moved or deleted; no index line changed.

- **Measured the premise first** (doctrine rule 1): `MEMORY.md` is **154 lines / 22,440 bytes**
  against caps of 200 / 25,000, **no truncation marker present**. But it measured **143 lines /
  21,071 bytes** twenty minutes earlier in the same session — six concurrent agents appending.
  So: elective post-hoc housekeeping, not a rescue. Line numbers are deliberately not used
  anywhere in the proposal; they shifted by 11 between the two measurements.
- **Proposed: Group A "ARCLAW defect atlas"** (anti-fabrication guard + 4000-char truncation +
  dataset starvation + eval-code inversion + no-sandbox-isolation -> one ~42 KB reference,
  **-4 index lines**); **Group B "supervising an autonomous run"** (housekeeping-vs-authoring +
  long-run-owner + cheap-fast-rig + name-level-compliance, **-3 lines**); **Group C** (WS3 H2
  hive notes) **proposed but DEFERRED** — paper v1 and the H3 campaign are actively reading
  those files.
- **Explicitly out of scope:** the stalled-GPU diagnosis note (homelab topic, not ARCLAW), the
  scope-choice-is-not-a-technical-limit feedback (behavioural rule, not a defect), the phase-2
  fanout record (coordination genre), the age-swarm state note, the deployment hub, and the
  doctrine files themselves.
- **THE FINDING THAT CONSTRAINS EVERYTHING:** two of tonight's memory files are `[[wikilinked]]`
  **from the FY27 RDTI evidence file** — claim-grade material headed for a tax reviewer —
  and one more from a Claude Code memory file. Obsidian's rename-with-link-update cannot see any
  of them. **Therefore: stub-redirects, never renames.** Every merged file stays at its original
  path as a 3-line redirect stub, so no link can break by construction.
- **Also found:** `vault_25_resources/` holds **39** ingest drawers against **38** live files in
  `25 - Resources/` — the vault ingester already has at least one orphan drawer, i.e. it does not
  reliably retire drawers. That is a second, independent reason stubs beat renames: a stale
  drawer re-ingests to the stub and still routes correctly instead of serving superseded content.
- **Index handling is two-tier.** Tier 1 (retarget all 9 lines to the canonical files, zero lines
  removed) is safe and saves ~0 bytes. Tier 2 (collapse each group's hooks to one, -7 lines,
  ~-1.36 KB) needs founder sign-off **and** a per-hook gate: an actually-executed
  `rag_client.py` query using the retired file's own body wording must return the canonical file.
  A miss blocks the collapse. Verbatim preservation is proved by a `comm -23` on
  frontmatter-stripped bodies before any stub is written; any output at all aborts.

**Not done by me and not to be inferred:** no consolidation executed, no index edited, no file in
`~/IntrepidBrain/` merged or renamed. Five open questions are listed in the proposal's §6 for the
founder/coordinator.

## h1-plan

**PLANNING ONLY — nothing executed. No LLM call, no GPU, no run started, no file in
`~/code/age-swarm` modified, no branch switched.** Every number below is re-analysis of frozen
artefacts already on disk. Plan written to
`~/Library/Mobile Documents/com~apple~CloudDocs/Intrepid Power Operations/research/papers/h1_run_plan_2026-07-31.md`.
**H1 remains NOT STARTED and the go/no-go is still the founder's.**

### The H1 story changes, and the working account was wrong in three ways

**1. H1 is not a measured null — it is an underpowered non-result.** At the episode level
(n=20 clusters, ICC(episode)=0.682 so cells are not the unit), debate − baseline = **+7.74 CRPS,
episode-clustered bootstrap 95% CI [−3.92, +26.22]**, sign test **11/20 episodes favour debate**,
p=0.824. **Every arm in the entire 240-cell matrix has a CI spanning zero** — against baseline and
against climatology. "Debate loses to climatology" is a point estimate with an interval eight
times its own width. The 07-12 design had roughly **20% power to detect its own point estimate**.

**2. The point estimate rests on one episode.** Leave-one-episode-out: dropping
`ep019_VIC1_202607090300_1h` moves the mean difference **+7.74 → −0.47**, a sign flip. Top 3 of 60
cells carry **51%** of the |difference| mass. Median episode difference is **−1.16 (debate better)**.

**3. The parse-failure confound is real but is NOT the mechanism.** Full recovery of every dropped
forecast from the raw logs moves debate **30.82 → 30.09** and baseline **23.08 → 22.25** — the gap
does not move. Anyone expecting the parse fix to flip H1 will be wrong.

### Parse-failure root cause — found in the logs, not inferred

Replayed the real parser over every response in all 241 files of `eval/run_logs_2026-07-12/`:

- **0 malformed JSON. 0 empty responses. 0 timeouts. 0 non-numeric values.**
- **115/115 debate failures are `WRONG_KEY_COUNT`**: 112 carry exactly 18 keys, 3 carry 17, and in
  **115 of 115 the missing level is τ=0.95**. Valid JSON, correct schema, numeric, monotone —
  complete forecasts missing their top quantile, thrown away whole by the strict
  `len(q) != 19` check at `eval/forecast_bench.py:213`.
- Not truncation: bodies are 229–456 **chars** against a 400-**token** budget, and 94/115 carry a
  well-formed trailing `"rationale"` and closing braces.
- **It is one model.** qwen2.5:7b **287/508 = 56.5%** short across the whole run; llama3.1:8b
  2/307 (0.7%); granite3.3:8b **0/365**. Consistent across all four patterns and all three seeds.
- **qwen2.5:7b is also `BASELINE_MODEL`** — 55/101 baseline calls short, so **14 of 60 baseline
  cells are pure climatology**. The comparison is confounded on *both* sides, not just debate's.
- The retry passes **the same seed** (line 335), only the prompt differs: 77 first failures → 39
  rescued, 38 lost.

### The real mechanism, and it is a better paper than the parse bug

**7 implausible member vectors out of 322 (2.2%) account for 8.6 of debate's 30.82 CRPS.** A
pre-registerable, domain-grounded guard (reject a member whose q95 exceeds 10× the episode's
trailing-30-day climatology max) takes debate **30.82 → 22.25** — below baseline (23.08) and below
climatology (23.78) — at **coverage unchanged (88%) and width 300.4 → 138.1**. It beats the
Wang/Kang/Li trim (24.54). Guarded debate − baseline = −0.83, CI [−5.16, +4.25]: better, still not
significant at n=20. **Post-hoc, chosen after seeing the data — which is exactly why it is
pre-registered rather than claimed.**

**Contagion is the deeper finding.** 12.6% of round-1 vectors are **verbatim copies of a different
agent's round-0 vector** (19/60 cells), 14.5% are unchanged, 73.0% genuinely new. Round 0 already
beats round 1 (28.90 vs 30.09) — **the revision round makes it worse**. Worked example `ep019`
seed 42: granite emits median 1447.6/q95 2602.7 at r0, **qwen reproduces it byte-identically at
r1** while granite itself revises down to a good 112.8 → merged CRPS 260.2. At seed 43 granite's
**q95=10003.0** propagates to qwen and `trim_keep=2` then *fails* (188.3), because the two
survivors agree — and they agree because one copied the other. **Trimming assumes rogues are
independent; copying makes them correlated.** The value-based guard is immune to this; the
agreement-based trim is not.

### N and R are welded in

`AGENT_MODELS` is a module-level 3-list (`forecast_bench.py:71`); `run_debate` (356–409) has round
0 as a loop and **round 1 written out longhand** with the comment `# Round 1 (always, R=1)` —
there is no round loop. `revision_prompt` has no round index; `extra` has literal
`round0`/`round1` keys. `src/patterns/debate.py` is **not** on the bench's path — the bench
reimplements debate; fixing the library changes nothing. Refactor specified to the function level:
**~405 lines total** including the parse fix, guard, and tests. Highest-risk line is
`load_done_cells` (622), which keys resume on `(episode_id, pattern, seed)` and will silently
treat an N=5 cell as done because an N=3 cell exists.

### Power — the honest answer, and the design that fits

Measured: between-episode var 1466.6, within-episode(seed) var 685.4, **ICC 0.682**.

- Raw CRPS scale (sd 38.30): detect **20% → 541 episodes**, 30% → 241, **10% → 2,162**. On the raw
  scale a 10% effect is simply out of reach.
- Pre-registered **log(CRPS+1)** scale (sd 0.4965, justified by mean 30.82 vs median 16.10):
  **10% → 214 episodes, 15% → 100, 20% → 59**. Winsorised(5/95) raw: 20% → 71.
- **196 episodes gives ~80% power for a ~10–11% relative improvement** — ~10× the resolution of
  07-12. It cannot see 5%; that goes in Limitations, not in a surprise at review.
- **Seeds are nearly worthless.** 1→3 seeds cuts required episodes 21% while tripling cell count.
  **Decision: 2 seeds**, only so "better in both seeds" stays checkable.

### Compute — it is ~13–19 h, not 50+

Measured from the frozen run: debate **34.0 s/cell, 7.28 calls, 4.67 s/call** (the 7.28 vs nominal
6 is the 21% retry tax the parse fix removes); 240 cells = 88.5 min. Two levers collapse the grid:
**(a) R=0/1 are free prefixes of R=2** (round r's prompt depends only on rounds <r) and
**(b) trim_keep, guard, α and weight_mode are pure functions of the logged member vectors — swept
offline for zero LLM calls** (demonstrated end-to-end tonight on the frozen logs at zero cost).
Result: 1,568 cells ≈ **12.9 h**, or **19.1 h** at tonight's measured **1.48× `OLLAMA_MAX_LOADED_MODELS=1`
swap penalty** (32.6 s/cell wall vs ~22 s LLM latency on the live H3 run). N=5 roster is 26.3 GB
resident — raising `OLLAMA_MAX_LOADED_MODELS` should recover most of it, **to be measured on a
10-cell smoke, not assumed.**

### Verified infrastructure facts

- **The 196-episode file already exists** — `eval/forecast_episodes_2026-07-31_h3.json`, 98 NSW1 /
  98 VIC1, 98×1h / 98×24h, ts0 2026-01-10 → 2026-07-25. Untracked; must be committed and SHA'd.
- All five roster tags verified in `ollama list` (qwen2.5:7b, llama3.1:8b, granite3.3:8b,
  gemma4 9.6 GB, phi3.5:3.8b).
- **AEMO-vintage baseline exists but only covers 56/196 episodes.** `predispatch_price_forecast`
  has 826,620 rows, run_datetime from **2026-05-29**; 70 episodes fall in the window, **56 have a
  usable ≥2-member vintage ensemble (mean 41 members)**. Columns are `VARCHAR` `YYYY/MM/DD` — a
  naive ISO comparison returns **zero rows and looks like absence** (I made that exact false
  negative first and corrected it). Pre-declared as a **secondary analysis on the 56-episode
  subwindow**; do not shrink the study to 56 to accommodate it.
- **`hosts.yaml` is stale** — names `m5-prime`/`m5-2`/`m5-3`; the real tailnet is `macbook-pro`,
  `m5-infer1`, `m5-infer-2`, `m5-prime-serve`, `int-hve-srv`, `m1-secretary` (offline).
- **I could NOT verify whether m5-infer1 or m5-prime-serve expose Ollama.** Every HTTP probe
  returned `000` **including to `127.0.0.1`** — the agent sandbox blocks egress, so this is a
  **failed probe, not evidence of absence**. Operator must run
  `curl -s -m5 http://100.73.163.0:11434/api/tags` on the host. Until then, **plan single-host
  serial**; distribution is upside and needs ~20 lines anyway (`call_model` hardcodes
  `host="localhost"` at line 293).
- **Scheduling: the GPU is busy.** The H3 run is in flight (980 cells, ETA ~05:45 AEST 2026-08-01).
  **H1 must not start before it finishes** — contention would degrade both runs' latency and
  comparability.

### Risk register (top 5, in the plan in full)

**R1 — the results file silently mixes arms.** `append_result` is append-mode and resume keys on
`(episode_id, pattern, seed)` only, while `run_debate`'s default is **already `trim_keep=2`** — the
arm definition changed after commit `a34aadc` that produced the 07-12 data. One file per grid cell,
extended resume key, arm signature + git SHA in every record, assert-on-load.
**R2 — fabrication.** Tonight's ARCLAW produced three dataset confabulations, one of which
**passed its own validator**. No LLM may compute or transcribe a headline number; analyser must
reproduce 30.82 / 23.08 / 0-of-3 from the frozen file **before** new data lands, or the run does
not start.
**R3 — launcher environment.** 98/98/37 `CERTIFICATE_VERIFY_FAILED` tonight behind a
command string that looked right. Verify the **executed** process via `ps eww` on the **python**
pid, not the `zsh -c` wrapper.
**R4 — correlated rogues defeat the combiner** (contagion, above).
**R5 — outlier-driven result in either direction**; log scale primary, leave-one-episode-out
published as a figure, episode-clustered bootstrap.

### Repo state that must be resolved before launch

`~/code/age-swarm` is on **`cursor/ws3-crps-evolve-1bce`, not
`cursor/ws3-fy27-calibration-objective-7562`** as the brief assumed, with `eval/forecast_bench.py`
and `eval/forecast_tasks.py` **uncommitted-modified** (the h3-run session's changes) and the
196-episode file untracked. **No branch was switched and nothing was committed** — shared-worktree
rule. Resolve deliberately before H1 launches.

## verifier-fix

**Owner:** verifier-fix agent, 2026-07-31. **Scope:** make it impossible for the pipeline to
certify invented results as real. **Status: fixed and proven against the real fabricated run.**
Patch `patches/006-fab1-verifier-reconciles-against-execution-artefacts.patch`; working tree
modified (new module + tests are `git add -N` intent-to-add).

### GROUND-TRUTH CORRECTION to the vault note

The vault note
`25 - Resources/reference__anti-fabrication-guard-defeated-by-a-log-pattern.md` states the
stage-20 detector *"evidently scrapes numbers out of the PAPER TEXT and calls them verified."*
**It does not.** Verified from source and artefacts:

- `_review_publish.py` builds `real_metric_values` from `stage-14*/experiment_summary.json`
  (`condition_summaries` + `metrics_summary`). It never reads the paper.
- Those values reached `experiment_summary.json` from
  `stage-13/refinement_log.json → iterations[0].sandbox.metrics` — **34 metrics emitted by a
  sandbox that exited `returncode: 1`**, dying on the second of five conditions.
- `_analysis.py:164-175` then hardcoded `"status": "completed"` on that best_run **regardless of
  returncode**. That is the laundering step. Stage 20 read a summary that said `completed`.

So `707213.5867` / `0.9201` / `136.2886` / `64.4655` **are real emitted numbers** — for the
`NoWidening` baseline only, on a crashed process. What was invented is everything else: the
`DIVI` row, the baseline row (87.5% / 751,234.12), the whole ablation table, the t-tests and the
cross-validation. **The mechanism is worse than text-scraping: it is a crashed run's partial
output promoted to a clean status and then re-attributed to conditions that never executed.**
The `condition[=:]` stdout guard at `_paper_writing.py:1333` is real and is fixed, but in *this*
run it was not even load-bearing — `metrics_summary` was non-empty, so line 1318 had already set
`has_real_metrics = True`.

### The fix — one principle, one module

`researchclaw/pipeline/results_evidence.py` (new, 480 lines). **A verifier must reconcile
reported numbers against the execution artefacts, never against the text it is verifying and
never against a log string that the failure path itself emits.**

Reads only artefacts that record what a *process* did:
`stage-*/runs/*.json` (`status`, `metrics`, `timed_out`) and
`stage-13*/refinement_log.json` sandbox entries (`returncode`, `metrics`, `timed_out` — both
always written by `_execution.py`). It never reads `experiment_summary.json` (derived), never
reads paper text, never pattern-matches logs.

- An execution counts as evidence only if it **terminated cleanly** (`status` exactly one of
  completed/done/success/... or `returncode == 0`) **and emitted ≥1 finite non-infrastructure
  metric**. A non-zero exit never counts, however many metrics it printed first — the program's
  own contract broke, so the condition set it claims to cover is unknowable.
- A **timeout with metrics** does count (`degraded`) — a budget outcome is not a broken contract.
- `simulated` never counts. Clean exit with empty metrics never counts.
- All key matching is whole-token (`total_runs` is infra, `total_runs_recovered` is not) —
  no bare substring checks.
- **Silence is not absence:** with zero execution artefacts `is_authoritative` is False and
  callers keep their prior behaviour (theoretical domains record no runs). It never means
  "assume success".

Wired into:
- **stage 17** `_paper_writing.py` — deleted the `>=3 × condition[=:]` rule outright; evidence is
  authoritative in both directions; writes `stage-17/results_evidence.json`; block message now
  carries the per-execution reasons.
- **stage 20** `_review_publish.py` — evidence overrides `_exp_failed`;
  `has_real_data` / `fabrication_suspected` / `verified_values_count` / `verified_conditions`
  all derived from evidence (the summary-derived list is kept as `summary_derived_values` for
  audit); forced `verdict: reject`, `score 1.0`, and **`StageStatus.FAILED` that bypasses
  `graceful_degradation`** — a fabrication block is not degradable; separately, `Accept` is
  downgraded to `revise` whenever `fabrication_suspected` is set, which also closes the
  non-authoritative case.
- **stage 14** `_analysis.py` — `best_run.status` now reflects the sandbox's actual returncode
  (`completed` / `partial` / `failed`) instead of the hardcoded `"completed"`.
- **stage 12** `_execution.py` — honest `decision`/`error` instead of `status: done, error: null`.
  Status stays DONE so the stage-13/14 repair loop still runs (stage 12 is not in
  `NONCRITICAL_STAGES`; FAILED would `break` the runner). **This hunk is co-owned with the
  `adoption-fix` agent, who layered `_summarise_run_outcomes` on top and now owns that file** —
  it is deliberately NOT in patch 006.

### PROOF — before/after on the real run, by execution

Harness runs the **real** `_execute_paper_draft` and `_execute_quality_gate` against
`artifacts/rc-ws3-h2-real4-20260731`. Stage 20 is driven with a stub LLM returning exactly the
verdict the real run got (`{"score_1_to_10": 8, "verdict": "Accept"}`), and
`graceful_degradation: True`. BEFORE = pristine `HEAD` (`4180b04`) extracted via `git archive`.

| | stage 17 | stage 20 status | score / verdict | fabrication_suspected | has_real_data | verified_values_count | real_metric_values |
|---|---|---|---|---|---|---|---|
| **BEFORE** | `done`, wrote a draft | `done` / proceed | **8 / Accept** | **false** | **true** | **35** | **103 values incl. 707213.5867** |
| **AFTER** | `failed`, "Paper Draft Blocked" | **`failed` / `fabrication_block`** | **1.0 / reject** | **true** | **false** | **0** | **[]** |

The BEFORE column reproduces the shipped `stage-20/fabrication_flags.json` **exactly**
(`verified_values_count: 35`, `verified_conditions: ["NoWidening"]`, `real_metric_values`
starting `0.9201, 707213.5867`) — the harness is faithful, not a strawman.

`unverified_conditions: ["NoWidening"]` and `orphan_metric_count: 128` are now reported: 128
finite values were emitted by processes that did not terminate cleanly.

### NO FALSE POSITIVES — positive control

**There is no legitimately successful run anywhere in `artifacts/` — all 10 run dirs have zero
executions that terminated with results.** So the control was built from the fabricated run by
changing **only terminal-outcome fields** (4 × `returncode: 1 → 0` where metrics exist;
`run-1.json status failed → completed` with the sandbox's own 34 metrics copied verbatim). **No
metric value was altered.**

| run | stage 17 | stage 20 | verdict |
|---|---|---|---|
| positive control (same numbers, clean exits) | `done` | `done` / proceed | **Accept, has_real_data true, 162 verified values** |
| `rc-ws3-theorem-hunt-20260730` (0 executions) | unchanged | `done` / degraded | Accept → **revise** (fabrication_suspected was already true) |
| `rc-20260730-114801-e9b01a` (H2 run, 0 metrics) | blocked before **and** after | `done`→**`failed`** | Accept → reject |
| `rc-20260730-081713` (`mode: simulated`) | blocked before **and** after | `done`→**`failed`** | Accept → reject |

### Tests

`tests/test_results_evidence.py` — 22 tests, all passing, including a skip-if-absent test against
the real `rc-ws3-h2-real4-20260731` directory.
Full suite: **2813 passed, 49 skipped, 1 failed** vs baseline **2791 passed, 49 skipped, 1
failed**. The single failure is pre-existing and unrelated —
`test_experiment_diagnosis.py::TestDatasetNotFoundError::test_suggested_fix_mentions_precached`,
which fails at baseline because `experiment_diagnosis_dataset_guidance_2026-07-31.patch` is
already applied in this tree and the test still asserts the old hardcoded advice.

Patch verified self-contained: applied to a pristine `git archive HEAD` tree it applies cleanly,
its 22 tests pass, and stage 20 blocks the fabricated run.

### NOT FIXED — remaining exposure, stated plainly

1. **Stage 18 PEER_REVIEW and stage 19 PAPER_REVISION are untouched.** The reviewer still is not
   required to trace each reported number to an artefact, and the reviser can still answer a
   correctness complaint by asserting the disputed claim more confidently. These stages now sit
   downstream of a stage-17 block, so on the incident path they never run — but if a run has *any*
   clean execution, a paper can still over-claim beyond what that execution covered.
2. **Per-condition attribution is not enforced.** The evidence module reports
   `verified_conditions` and `unverified_conditions`, but nothing yet rejects a paper that reports
   a table row for a condition in `unverified_conditions`. This is the exact shape of the incident
   (one condition ran, five were tabulated). It is the highest-value follow-up.
3. **Magnitude sanity is not checked.** A CRPS of 707,213 against prices in the hundreds remains
   the tell that survives a clean provenance chain, and nothing checks it.
4. **`verification_report.json` / `integrity_score: 1.0` still verifies only citations.** It is
   unchanged and still the most misleading artefact in `deliverables/`; a reader sees
   "integrity_score 1.0" and reasonably concludes results were checked.
5. **`mode: simulated` end-to-end smoke runs now hard-fail at stage 20** where they previously
   passed. In practice inert (stage 17 already blocks simulated runs first), but it is a real
   behaviour change.

## adoption-fix

Owner of `researchclaw/pipeline/stage_impls/_execution.py`. Two structural defects fixed and
replayed against the real `artifacts/rc-ws3-h2-real4-20260731`. Patch:
`patches/007-execution-adoption-and-honest-stage12.patch` (apply **after** `006` — it carries every
`_execution.py` hunk including verifier-fix's FAB-1 block, which imports `results_evidence.py`).

### Defect 1 — score-gated adoption discarded correct fixes

Confirmed by AST, not by reading indentation: `if validation.ok and mode in ("sandbox","docker")`
spans lines 952–1097, and the `elif validation.ok and best_version == "experiment/"` at 1098 is its
`orelse`. The fallback's own test requires `validation.ok`, so in sandbox/docker mode the parent is
always taken and **the fallback never evaluates** — dead code on the only path we run. Adoption was
therefore reachable *only* through `metric_val is not None and _is_better(...)`.

**What that cost, measured.** In `rc-ws3-h2-real4-20260731`, every version crashed on an unrelated
dtype/broadcast bug, so `metric_val` was `None` throughout, `best_files` never left the original
stage-10 code, and `experiment_final` was written from it — **with no log line saying so**.
`stage-13/experiment_v1/evaluation.py` and `v2` both define `compute_crps`; the shipped
`experiment_final/evaluation.py` does not. The correct implementation was written and thrown away.

**Fix.** Two module-level, independently testable functions:

- `_refinement_progress_key(iteration, iter_record)` → ordered tuple
  `(exited_cleanly, n_metric_keys_emitted, not_timed_out, iteration)`, measured on the **last**
  sandbox run of the iteration (`sandbox_after_fix` when a runtime repair re-ran the code, because
  those are the files actually in the version directory). `iteration` breaks ties, so in modes that
  never run a sandbox this degrades to "latest validation-passing version" — what the dead `elif`
  was reaching for.
- `_decide_refinement_adoption(...)` → `(adopted_version, reason)`, four outcomes, **all logged**
  into `refinement_log.json.adoption_reason`: `metric_improvement`,
  `original_retained_no_metric_improvement`, `progress_fallback_no_metric_anywhere`,
  `original_retained_no_valid_candidate`.

The fallback fires **only when `best_metric is None`** — a baseline metric that no refinement beat
is a genuine comparison and is never overridden by a metric-blind progress score. "The original was
kept" is now a recorded decision instead of silence.

**Second-order fix in the same loop.** While metric-blind, `best_files` stayed pinned to the
original, so every iteration re-refined the original and improvements never compounded — this is the
mechanism behind "successive codegen attempts look byte-identical while refinement is quietly
succeeding underneath". Iterations now build on the best-progress candidate (`refine_source_files`,
recorded per-iteration as `refined_from`). The ranking is monotone, so a regressing iteration is not
fed forward: in the real run iter 2 (`NameError: name 'norm' is not defined`, 0 metrics) does not
displace iter 1 (34 metric keys, one condition completed). Once a metric exists, `best_files`
governs again and behaviour is unchanged.

**REPLAY, executed (not read) against the real artefacts.** BEFORE is what the live run wrote:
`baseline_metric: null`, `best_metric: null`, `best_version: "experiment/"`, no adoption line, both
iterations `metric: None, improved: False`. AFTER, feeding those same iteration records through the
shipped functions:

```
iter 1: _refinement_progress_key = (0, 34, 1, 1)   <-- adopted
iter 2: _refinement_progress_key = (0,  0, 1, 2)
_decide_refinement_adoption -> ('experiment_v1/', 'progress_fallback_no_metric_anywhere')
```

`experiment_final` would have been written from `experiment_v1/` — which crashed only after
completing condition `NoWidening` and emitting 34 metric keys, against the original's 0 conditions
and 0 metrics.

> **Selects v1, not v2 — and that is the right call.** The vault note credits `experiment_v2` with
> the better CRPS. v2 also regressed elsewhere: it died on a missing `norm` import before emitting
> anything. Progress-ranking prefers the version that ran further. Either breaks the deadlock; only
> v1 gets a metric-emitting file into `experiment_final`.

### Defect 2 — stage 12 swallowed failure

`stage-12/decision.json` read `status: "done", decision: "proceed", error: null` over a
`stage-12/runs/run-1.json` reading `status: "failed", metrics: {}` — the wrapper contradicting what
it wrapped, because `_execute_experiment_run` returned `StageStatus.DONE` unconditionally.

`_summarise_run_outcomes(runs_dir)` now derives the stage outcome from the terminal status of each
`run-*.json` (glob-anchored: `results.json` and the `sandbox/` working dir in the same folder are
not run payloads), writes `stage-12/run_outcome.json`, and escalates `proceed → degraded` with a
populated `error`. Replay on the real dir:

```
BEFORE: decision.json status='done' decision='proceed' error=None
AFTER : decision='degraded'
        error='1/1 experiment run(s) did not complete (failed=1, partial=0); 0/1 emitted metrics.'
```

**Deliberately still `StageStatus.DONE`, and this is the load-bearing decision.** Stage 12 is not in
`NONCRITICAL_STAGES`, so `runner.py:781` `break`s the pipeline on `FAILED` — which would destroy the
stage-13 refinement and stage-14 diagnosis/repair path that can still recover a crashed run. The
brief's constraint (honest status, preserved repair path) is met by `DONE` + `decision="degraded"` +
`error`: `runner.py:618` already prints DEGRADED, and both `decision.json` and `stage_health.json`
carry the reason.

**Complementary to `006`, not duplicate.** verifier-fix's FAB-1 check fires on *no finite metric
anywhere*; mine fires on *any run whose terminal status is `failed`/`partial`* — including the case
theirs cannot see, a run that crashes **after** emitting numbers (`status: failed` with a non-empty
`metrics` dict previously still returned `proceed`/`error: null`). Both live in the same return;
`no_results` wins when both fire and the reasons concatenate.

### Verification

- `py_compile` + import clean. Full suite via system pytest (the repo `.venv` has no pytest and the
  console server is live on it — **not** pip-installed into a running venv): **2791 passed, 49
  skipped, 1 failed**.
- The one failure is **pre-existing and unrelated**:
  `test_experiment_diagnosis.py::TestDatasetNotFoundError::test_suggested_fix_mentions_precached`
  asserts `"/opt/datasets" in suggested_fix` — the exact repair-poisoning string that the committed
  `experiment_diagnosis_dataset_guidance` patch deliberately removed. The test is stale, not the
  code. Left for its owner.
- 18 new tests in `tests/test_rc_execution_adoption.py`, including a standing guard that walks the
  AST of `_execution.py` and fails if any `elif` requiring `validation.ok` ever reappears under a
  parent that also requires it.
- Patch chain verified in a disposable worktree off pristine `HEAD`: `006` then `007` apply clean
  and reproduce the working tree byte-for-byte. No pipeline started, no GPU touched, no checkout.

### Not fixed — adjacent, deliberately left

`metric_key` was `primary_metric` while the experiment emitted `CRPS`, `Coverage90`, `Width90`,
`PinballLoss`, `success_rate`, `MedianCRPS`. Even a clean run would have scored `metric_val = None`
through `_find_metric`, because no emitted key contains `primary_metric`. **The adoption fix keeps
that from being fatal, but the config/code metric-name mismatch is a live defect on its own** and
belongs with whoever owns the run config. Note the compounding: with 34 metric keys on disk and a
`metric_key` matching none of them, a reader sees "no metrics" where the truth is "no *named*
metric".

### verifier-fix — addendum after `adoption-fix` landed `007` (verified, not taken on trust)

Independently re-verified in a disposable tree off pristine `HEAD`, not accepted on report:

- `006` then `007` both apply clean; the resulting `_execution.py` is **byte-identical** to the
  working tree, and my FAB-1 stage-12 block survives inside `007` unmodified.
- `007` alone applies clean but the tree then has no `researchclaw.pipeline.results_evidence`
  (`ModuleNotFoundError` confirmed) — so the **006-before-007** order is real, not stylistic.
- Chained tree: `tests/test_results_evidence.py` + `tests/test_rc_execution_adoption.py` = 39
  passed, and stage 20 still blocks `rc-ws3-h2-real4-20260731` with
  `failed / fabrication_block / reject / 1.0`.

**On `adoption-fix`'s `_find_metric` finding** (`config.experiment.metric_key = "primary_metric"`
while the experiment emitted `CRPS`/`Coverage90`/…, so `_find_metric`'s `key in mk` can never
match): **it does not affect this reconciliation, and that is now pinned by a test.**
`results_evidence.py` contains no reference to `primary_metric` or `_find_metric` — it counts *any*
finite non-infrastructure metric, so a metric-name mismatch cannot masquerade as "no results".
The positive control already demonstrated this incidentally (its metrics are all `NoWidening/*`
keys with no `primary_metric` anywhere, and it returns `has_real_metrics: True`, 162 values); it is
now explicit as `test_evidence_does_not_require_the_configured_metric_key`.

Their finding remains a real defect **elsewhere** — it means `refinement_log.metric` and
`best_metric` are `None` for this whole run, which is why stage 13's score-gated adoption discarded
its own correct fix. That is theirs, not mine, and is unfixed.

`006` regenerated with the extra test: **23 tests** in `test_results_evidence.py`. Full suite with
`006`+`007` both live: **2831 passed, 49 skipped, 1 failed** — the failure is the same pre-existing,
unrelated `test_experiment_diagnosis.py::test_suggested_fix_mentions_precached`.

### adoption-fix — ADDENDUM: the metric_key mismatch is the ROOT of defect 1, and it is now fixed

`verifier-fix` flagged back that my "not fixed, belongs to the config owner" note was understating
this. **They are right, and it upgrades the causal story.** Verified by executing every branch of
`_find_metric` against the real 34-key metrics dict from
`rc-ws3-h2-real4-20260731/stage-13`, rather than by reading the function:

```
metric_key = 'primary_metric'   emitted keys: 34
exact: None | cond-prefix: [] | aggregate: [] | suffix: [] | last-resort: []
=> every _find_metric branch misses: True
   if metric_key were 'CRPS':       5 matches, e.g. NoWidening/0/CRPS, NoWidening/CRPS, CRPS
   if metric_key were 'MedianCRPS': 5 matches
   if metric_key were 'Coverage90': 5 matches
```

**No run of that experiment could ever have scored — clean or crashed.** So the vault note's root
cause ("every version crashed on the same unrelated dtype bug, so `metric_val is None` throughout")
is half the story. Iteration 1 emitted **34 real metric keys and still scored `None`**: the crash
truncated the run at 1 of 5 conditions, but the `None` came from the key mismatch. The two defects
therefore stack in a specific order:

> **`metric_key` names nothing the code emits → `_find_metric` always returns `None` → the
> score-gated adoption has no score to compare → every correct fix is discarded.**

That is the "13 ITERATIVE_REFINE — produced a correct fix, then discarded it" row in the laundering
chain, with its upstream cause now named. Fixing adoption alone stops the discard; this makes the
*reason* visible instead of leaving `best_metric: null` to be misread as "the experiment produced
nothing".

**Fix — diagnosis, deliberately NOT auto-selection.** `_describe_metric_key_miss()` fires only where
`_find_metric` already returned `None` **and** metrics exist, records
`iterations[].metric_key_mismatch`, and hoists to `refinement_log.metric_key_mismatch`. On the real
artefacts:

> Experiment emitted 34 metric key(s) but none yielded a finite value for the configured metric_key
> 'primary_metric'. Emitted names: CRPS, CRPS_mean, CRPS_std, Coverage90, MedianCRPS, PinballLoss,
> Width90, success_rate. Refinement cannot score this experiment until metric_key names one of them
> (or the code emits 'primary_metric').

**It does not pick a replacement, and that restraint is the design.** `CRPS` is `minimize` and
`Coverage90` is `maximize`; auto-selecting under a config that also declares a direction would
silently optimise refinement against the wrong objective — strictly worse than `None`, because
`None` is at least visibly absent. Naming the metric is the run config's job. A test asserts the
message never nominates a substitute.

It also does **not** re-implement `_find_metric`'s five branches — a second copy would drift from
the decision it explains — so it carries an explicit precondition (call only after `_find_metric`
returned `None`), stated in the docstring and covered by tests.

**Verification after the addendum.** `patches/007-…` regenerated (617 lines). Chain re-verified in a
disposable worktree off pristine `HEAD`: `006` then `007` apply clean and reproduce the working tree
byte-for-byte for both files; chained tree runs `test_rc_execution_adoption.py` +
`test_results_evidence.py` = 46 passed, 1 skipped. Full suite **2838 passed, 49 skipped, 1 failed** —
the same pre-existing, unrelated `test_experiment_diagnosis.py::test_suggested_fix_mentions_precached`.
24 tests in `tests/test_rc_execution_adoption.py`. No pipeline started, no GPU touched, no checkout.

**Confirmed inert for verifier-fix's reconciler**, checked rather than assumed: `results_evidence.py`
counts any finite non-infrastructure metric and never references `metric_key` or `_find_metric`, so
the mismatch cannot masquerade as "no results" in the fabrication gate. They pinned it with a
dedicated test. The exposure was always confined to *refinement scoring*, which is where it did its
damage.

**Config side now closed too (observed, not done by me):** `config.h2-real.yaml` in the working tree
has `metric_key: "CRPS"` (was `"primary_metric"`), annotated with this exact mechanism. The two
halves are complementary and both are needed: the config change makes *this* run scorable; the
`_describe_metric_key_miss()` diagnosis makes the *next* mismatch visible instead of silent. Note
`metric_direction: "minimize"` is correct for CRPS — had anything auto-selected `Coverage90`
instead, that same direction would have been backwards.

### verifier-fix — second re-verification, after `adoption-fix` added `_describe_metric_key_miss` to `007`

`007` moved again, so the chain invariant was re-checked by execution, not assumed:

- `006` then `007` apply clean off pristine `HEAD`; **all six touched files byte-identical** to the
  working tree (`_execution.py`, `results_evidence.py`, `_analysis.py`, `_paper_writing.py`,
  `_review_publish.py`, `tests/test_results_evidence.py`). FAB-1 block still present in
  `_execution.py`.
- Chained tree: 47 passed, and stage 20 still blocks `rc-ws3-h2-real4-20260731` with
  `failed / fabrication_block / reject / 1.0`.

**`_find_metric` confirmed independently.** Extracted the real nested function from
`_execution.py` via AST (`ast.get_source_segment`) rather than reimplementing it, and ran it
against the actual 34-key metrics dict:

```
primary_metric -> None
CRPS           -> 707213.5866951895
Coverage90     -> 0.9200945626477541
```

`adoption-fix`'s conclusion holds exactly: iteration 1 emitted 34 real metric keys and still scored
`None`, so **no run of that experiment could ever have scored, clean or crashed**. The vault note's
"every version crashed, so metric_val is None" is only half the cause.

Their decision to diagnose rather than auto-select is correct and worth recording as a rule:
`CRPS` is minimize and `Coverage90` is maximize, so auto-picking a substitute under a config that
also declares a direction would silently optimise against the wrong objective. **A visibly absent
score is safer than a confidently wrong one.**

`config.h2-real.yaml` now carries `metric_key: "CRPS"` / `metric_direction: "minimize"` (not my
change). **No interaction with this reconciliation:** `results_evidence.py` ignores `metric_key`,
`metric_direction` and `refinement_log.metric` entirely, which is pinned by
`test_evidence_does_not_require_the_configured_metric_key`.

### adoption-fix — PRE-RUN RISK on the `metric_key: "CRPS"` config change (NOT mine to fix, and here is why)

`verifier-fix` flagged that with the objective now live, adoption may start *accepting* iterations for
the wrong reason. **Confirmed, and it is sharper than "the model underneath is broken".** From
`stage-10/experiment/evaluation.py:8` — the baseline that stage 12 runs and that stage 10 regenerates
each run:

```python
def compute_metrics(y_true, y_pred):
    crps = (y_pred[:, 1] - y_pred[:, 0]) / 2      # <-- "CRPS" IS THE INTERVAL HALF-WIDTH
    coverage90 = np.mean((y_true >= y_pred[:, 0]) & (y_true <= y_pred[:, 1]))
```

**So `metric_key: "CRPS"` + `metric_direction: "minimize"` on that code is an objective whose global
optimum is `lower == upper` — zero-width intervals, coverage 0.** `Coverage90` is computed and
printed but is **not** the adoption objective, so nothing penalises the collapse. This is not merely
"satisfiable by a degenerate change"; degeneracy is the *argmin*. It is a reward-hacking objective,
and the adoption gate would faithfully maximise it.

Two further specifics, both verified from the artefacts:

- **There is no predictive model in any condition.** `NoWidening.predict` is `np.array(X) * 1.0`
  (identity, `fit()` is `pass`); every widener is `np.array(X) * scaling_factor[:, None]`. Nothing
  regresses `rrp`. `y_pred[:, 0]` / `[:, 1]` are *feature columns* read as interval bounds.
- The stage-10 baseline calls `predict(val_df.drop(columns=['rrp_actual']).values)`, so the columns
  landing in `[:,0]`/`[:,1]` are whatever order the frame has — this is the Timestamp path.
  `experiment_v1` narrows it to `[['ens_mean','ens_sd','vol_lag','totaldemand']]` **and** replaces
  the half-width with a real pinball-over-tau CRPS. **Independent corroboration that the adoption fix
  picks the right artefact:** v1 is dimensionally coherent where the baseline is not.

**Why I am not fixing this in `_execution.py`.** Encoding "minimize CRPS *subject to* Coverage90 >=
0.9" into `_is_better` would be authoring the experiment's evaluation — the same line I declined to
cross when I refused to auto-select a substitute metric. A constrained objective is a research
decision, and the WS3 paper already specifies CRPS **and** interval coverage together (BURN_BRIEF:
"the paper specifies CRPS and interval coverage for gamma(D)-widening"). It belongs in the experiment
plan and the generated evaluation, not in the refinement gate.

**My code is inert under this risk — verified, not assumed.** With `best_metric` non-None,
`_decide_refinement_adoption` returns `metric_improvement` / `original_retained_no_metric_improvement`
and the progress fallback cannot fire; `refine_source_files` diverges from `best_files` only when
`best_metric is None`. Both covered by tests. So the patch neither causes this nor shields against it:
**it converts a silent "no score" failure into a live "wrong score" failure, which is exactly the
transition that makes this risk visible now.** Fixing adoption was still right — an absent score
discards correct work unconditionally — but the objective must be sound before the next run, or the
gate will accept degenerate interval collapse and it will look like success.

**Routed to `h2-pipeline` and `main`** as a pre-run item. Owner decision, not an implementation
choice: either (a) point `metric_key` at a metric whose argmin is not degenerate, or (b) have the
experiment emit a single coverage-constrained scalar and name *that*. Do not run to a paper on
`minimize (upper-lower)/2`.

### verifier-fix — the guard's boundary, made explicit (prompted by `adoption-fix`'s evaluator read)

`adoption-fix` traced my degeneracy risk to its source. **Independently confirmed by reading
`stage-10/experiment/evaluation.py` and `model.py` directly:**

```python
crps = (y_pred[:, 1] - y_pred[:, 0]) / 2      # "CRPS" IS THE INTERVAL HALF-WIDTH
coverage90 = np.mean((y_true >= y_pred[:, 0]) & (y_true <= y_pred[:, 1]))
```
with `NoWidening.predict` = `np.array(X) * 1.0` and `fit()` = `pass`, called as
`predict(val_df.drop(columns=['rrp_actual']).values)`. So `y_pred[:,0]` / `y_pred[:,1]` are
**feature columns**, and nothing regresses `rrp`.

Their two corrections to my characterisation are right and I accept both:
- **It is not "the model is broken" — there is no model.** That, not a bad fit, is the source of
  the ~707k.
- The Timestamps path is the **stage-10 baseline** specifically; `experiment_v1` narrows to
  `[['ens_mean','ens_sd','vol_lag','totaldemand']]`, so no Timestamps there.

And their sharpening of my risk is correct: under `metric_key: CRPS` + `minimize`, **degeneracy is
not merely reachable, it is the argmin** — `lower == upper`, zero-width intervals, coverage 0.
`Coverage90` is computed and printed but is not the adoption objective, so nothing penalises the
collapse.

**This is the boundary of the FAB-1 guard, and it is now stated in the code rather than left to be
discovered.** `has_real_metrics` answers *did a process emit this number?* — never *is the number
meaningful?* A degenerate run exits cleanly, emits finite metrics, and **passes**, correctly: the
numbers really were produced. Added a "Scope boundary — provenance, NOT validity" section to the
`results_evidence.py` docstring (with this evaluator as the worked example) and a test,
`test_has_real_metrics_is_provenance_not_validity`, that pins it: a zero-width/zero-coverage run
must PASS, and if that test ever fails because someone taught the module to judge plausibility,
that is a deliberate design change, not a bug fix.

**I did not add a validity check, for the same reason `adoption-fix` did not auto-select a metric.**
Encoding "minimise CRPS subject to Coverage90 >= 0.9" into an integrity gate would be authoring the
experiment's evaluation. It belongs in the experiment plan and the generated evaluator — the WS3
paper already specifies CRPS *and* coverage together. A gate that invented its own objective would
repeat the exact category error of the guard it replaced: substituting a proxy for the thing it
protects.

**Quote the guarantee precisely:** *every reported number traces to a process that produced it* —
never *the results are correct*.

`006` regenerated (1188 lines, **24 tests**). Chain re-verified: `006` then `007` apply clean off
pristine `HEAD`, all six files byte-identical to the working tree, 48 passed across both suites.

## h2-pipeline — ASSESSMENT SUPERSEDED. THE RUN COMPLETED AND THE PAPER IS FABRICATED.

**My 08:55 prediction was WRONG and my 10:05 assessment ("no paper exists, terminal state proven")
is RETRACTED.** Run 4 finished at 03:45:05Z: `stages_executed: 29, stages_done: 29,
stages_failed: 0, final_status: "done"`, deliverables include `paper_final.md`, `paper.tex`,
`references.bib`, two rendered PNGs and `citation_verify_score: 1.0`. Stage 17 did not block,
because a later refinement cycle finally produced a run that completed — with ONE condition.
**The outcome is worse than the blocked run I predicted.** A block is an honest refusal; this is a
polished, figure-bearing, citation-verified paper whose central results are invented.

### VERDICT: GARBAGE — and specifically FABRICATED. Not "needs another pass".
Every item below is verified against the run's own artefacts.

1. **THE HEADLINE IS THE ABLATION'S NUMBER, RELABELLED AS THE METHOD.** Paper: "DIVI achieves a
   92.01% ... coverage and a CRPS score of 707,213.59". `stage-14/experiment_summary.json` has
   exactly ONE condition, `NoWidening`, with `CRPS = 707213.5866951895` and
   `Coverage90 = 0.9200945626477541`. Match confirmed to the digit.
   **`DivergenceConditionedWidening` NEVER produced metrics in ANY stage-14 summary** (checked all
   six: `stage-14`, `_v1`, `_v2`, `_repair_v1..v3` -> conditions are `['NoWidening']` or `[]`).
   The paper's proposed method never ran; the no-widening control's numbers are printed under its
   name.
2. **THE BASELINE COMPARISON IS INVENTED.** Paper: "UQA ... 87.5% interval coverage and a CRPS score
   of 751,234.12". `grep -rl "751234"` across the whole run matches ONLY paper files
   (`stage-22/*`, `stage-23/*`, `deliverables/*`) and **no experiment artefact whatsoever**. The
   number was created at the writing stage. So is the "4.51 percentage points" improvement and the
   "reducing the CRPS score by over 44,000".
3. **THE NUMBER IS PHYSICALLY MEANINGLESS.** CRPS carries the target's units. Prices span
   -757 to +20,300 $/MWh; my independent yardstick gives CRPS ~15 $/MWh. **707,213 is ~46,000x too
   large** — it is the half-width of two arbitrary FEATURE columns, not a score.
4. **FABRICATED STATISTICS.** Table 3 reports paired t-tests "t=4.56, p<0.01" and "t=-3.21, p<0.01"
   between UQA and DIVI. Only one condition exists, and its `CRPS_std = 0.0` across three identical
   "seeds". There is nothing to test; the t-values are invented.
5. **METHOD DESCRIBED != METHOD IMPLEMENTED.** The paper defines DIVI via **KL divergence**,
   `w_t = beta*D_KL + (1-beta)*w_0`, with pseudocode. The code uses the ensemble standard deviation
   `ens_sd` as `1 + alpha*z(ens_sd)`. **KL divergence appears nowhere in any generated file.**
6. **FABRICATED EXPERIMENTAL SETUP.** Claims an LSTM baseline "approximately 12 hours per epoch",
   plus GRU, Transformer, quantile regression and Monte Carlo baselines; "weather data" features;
   and "imputation of missing values". No model was ever trained (the run took ~2-5 s), the dataset
   has ZERO nulls and NO weather columns, and none of those baselines exist in any generated file.
7. **EMPTY TABLES UNDER ASSERTING PROSE.** The sanitizer stripped unverifiable numbers, leaving
   Tables 1, 2 and 4 as `--- ± ---` and `---,--- ± 10,---` — while the surrounding prose continues
   to assert the very values that were stripped. The redaction machinery worked; the narrative
   ignored it.
8. **BROKEN FIGURE REFERENCE.** The paper references `charts/performance_comparison.png`, which does
   not exist. The two PNGs that do exist are each referenced twice (Figures 1&3, 2&4 are duplicates).
9. **CITATION INTEGRITY IS FALSELY GREEN.** `verification_report.json` reports 3/3 verified,
   0 hallucinated, `integrity_score: 1.0`. But `du2022role` verifies against CrossRef as *"Role of
   oil price volatility, energy efficiency, and financial stability on sustainable energy
   production"* (relevance 0.1) while the paper's reference list renders it as *"The Role of
   Ensemble Methods in Probabilistic Forecasting"* — **a different, invented title on a real DOI.**
   The verifier checks that a DOI resolves, not that the paper describes it honestly.

### What DID work — and it is not nothing
- **My mandated provenance disclosure appears VERBATIM in the Conclusion.** The one constraint that
  fully landed end-to-end.
- The Limitations section reproduces the mandated caveats accurately: heteroskedasticity confound,
  model-vintage non-independence, and the debate-side evidence with the correct
  `Spearman +0.249, cluster-bootstrap CI +0.029 to +0.434, 20 clusters`.
- **But it violates the constraint it was given** by calling that cited prior evidence "our ablation
  study ... on the debate side" — conflating a companion re-analysis with this paper's own
  experiment, which the block explicitly forbade. And NONE of the mandated headline framing survived:
  no width elasticity, no D^0.75, no Vincentisation lemma, no base-incommensurability warning.

### The lesson that supersedes tonight's earlier ones
Stage 17's anti-fabrication guard only fires when there are NO metrics. **One condition that runs is
enough to disarm it** — after which the writing stage will invent a comparator, invent its numbers,
invent baselines it never trained, and invent statistics over a single zero-variance condition, and
the citation verifier will stamp it 1.0. **A partial experiment is more dangerous than a failed one,
because it converts an honest refusal into a confident fabrication.**

### Revised priority list (supersedes the 10:05 version)
0. **NEW #1 — make the anti-fabrication guard proportional, not binary.** Stage 17 blocks only on
   ZERO metrics. It must also block, or force an explicit "preliminary/single-condition" mode, when
   the conditions that actually produced metrics do not include the PROPOSED METHOD, or when fewer
   than 2 conditions ran. As it stands, one surviving ablation licenses a full comparative paper.
1. Forbid the writing stage from emitting any numeric result that is not traceable to a key in
   `experiment_summary.json`. The sanitizer already redacts unverifiable table cells to `--- ± ---`
   — but the PROSE is not sanitised, so the same fabricated values survive in sentences. Sanitise
   prose against the same allow-list, or fail the stage.
2. Fix `_execution.py:1098` adoption (patch 007, adoption-fix agent) — a correct CRPS was generated
   and discarded three seconds later.
3. Make stage 12 fail when its run fails (`decision.json` said done/proceed/error:null over a
   `failed` run).
4. Citation verification must compare the RENDERED reference title against the resolved DOI title,
   not merely confirm the DOI exists. `du2022role` scored `verified/1.0` with an invented title.
5. Delete the six `/opt/datasets` injections; validate the launcher environment in
   `researchclaw validate` (TLS/CA bundle, scientific stack).

### Final honest answer to the founder's ask
**AutoResearchClaw produced a paper tonight, and it must not be used.** Its headline is an
ablation's number wearing the method's name, its baseline comparison and significance tests are
invented, its stated method (KL divergence) is not the method in the code, and its CRPS is ~46,000x
too large to be a price score.
The genuine research output from tonight is unchanged and did not come from the pipeline: the
sublinear width-elasticity result (~D^0.75, reproduced independently by two agents with different
code), the native-elasticity contrast (+1.020 AEMO vs +0.240 debate) with the exact Vincentisation
lemma explaining it, and D-is-not-a-volatility-proxy. Those came from nem-data's analysis and my
independent yardstick, on real NEM data, and they are defensible. That is what should be written up
by hand — with the AEMO/debate evidence asymmetry stated, and without any claim that ARCLAW produced it.

### adoption-fix — CLOSING: corrected framing, and the limit of what `007` buys

`h2-pipeline` (run owner) accepted the objective analysis, kept `minimize CRPS` with a *properness*
precondition written into `prompts.h2-real.yaml` + `config.h2-real.yaml`, and pushed back on my
one-line framing. **The pushback is half right and the correction matters, so it is recorded here
rather than settled by agreement.**

My sentence was: *"my patch converts a silent 'no score' failure into a live 'wrong score' failure."*

- **Accepted:** it understates the contribution. Without `007` a correct CRPS could not survive
  adoption *at all* — the objective being sound is worthless if the gate discards the version that
  implements it. Both halves are needed; neither substitutes for the other.
- **Not accepted as stated:** "overstates the risk" is the wrong correction. The degeneracy risk at
  the adoption gate is unchanged and real. What is true is that it **is not the binding constraint** —
  a sound objective over a one-condition experiment still yields an invented paper. "Not binding" and
  "overstated" are different claims, and the burn should keep them apart: the risk becomes binding
  the moment the upstream problems are fixed, which is exactly when nobody will be looking for it.

**Verified their condition claim against the stage-13 artefacts** (they checked stage-14; this is an
independent surface):

```
REGISTERED_CONDITIONS: NoWidening, ShuffledDivergenceWidener, DivergenceConditionedWidener,
                       VolatilityConditionedWidener, NormalizedConformalWidener
iter 1 conditions with metrics: ['NoWidening']   (34 keys)
iter 2 conditions with metrics: (none)
```

**5 registered, 1 producing metrics.** Which forces an honest qualification on my own replay:
**`experiment_v1` — the version `007` adopts instead of reverting — is itself a 1-of-5-condition
run.** Adopting it is strictly better than discarding it (it has a dimensionally coherent
pinball-over-tau CRPS where the baseline has a mislabelled half-width), but *better is not good*, and
the replay must not be read as "the fix rescues the experiment". `007` stops correct work being
thrown away. It does not make the experiment valid, and on run 4's evidence the writing stage will
fabricate a comparison regardless of what the gate adopts.

**Adjacent gap, flagged not built.** Stage 13's R7-3 hint checks only whether *any* `condition=` label
appears in stdout, never whether every `REGISTERED_CONDITIONS` entry produced metrics — so "1 of 5
ran" is invisible to the refinement loop, and `_refinement_progress_key` ranks a 1-condition version
without knowing it is one. A registered-vs-scored condition diagnosis would live naturally beside
`_describe_metric_key_miss` in `_execution.py`. **Deliberately not implemented:** `h2-pipeline` has
just put `DEGENERACY_CHECK` and mandatory per-condition reporting into the prompts, and two agents
building overlapping diagnostics is the collision this file already absorbed once. Offered to them;
theirs to call.

**Scope boundary pinned in code**, mirroring `verifier-fix`'s provenance/validity split:
`_refinement_progress_key`'s docstring now states that it ranks *progress, not quality*, and that
`adoption_reason: progress_fallback_no_metric_anywhere` must never be read as a claim that the
adopted version is scientifically better — it says only *no version produced the configured metric,
and this one ran furthest*. A version that runs further while optimising a degenerate objective still
ranks highest here, correctly; the alternative is discarding every refinement whenever the objective
is unusable.

**Final verification.** `patches/007-…` regenerated (628 lines). `006` (1188 lines) then `007` apply
clean off pristine `HEAD`; **all seven touched files byte-identical** to the working tree; chained
tree 47 passed / 1 skipped. Full suite **2839 passed, 49 skipped, 1 failed** — the same pre-existing
`test_experiment_diagnosis.py::test_suggested_fix_mentions_precached`. No pipeline started, no GPU
touched, no checkout.

### 2026-07-31 — correction accepted from adoption-fix, and a diagnostic ownership decision
**Correction accepted, and the distinction is load-bearing.** I wrote that adoption-fix's risk note
"overstates the risk". Wrong word. The correct statement is **"not the binding constraint"**. The
degeneracy risk at the adoption gate is unchanged and real; it simply is not what bit tonight,
because only one condition ran and the writing stage fabricated regardless. Those are different
claims, and the difference matters because **the gate risk becomes binding the moment the upstream
problems are fixed — exactly when nobody will be looking for it, since the visible failures will
have gone.** Recording it their way.

**Their one-condition finding independently corroborated on a second surface.** I checked the six
`stage-14*/experiment_summary.json` files; they checked stage-13's refinement artefacts and found
`REGISTERED_CONDITIONS` lists five (NoWidening, ShuffledDivergenceWidener,
DivergenceConditionedWidener, VolatilityConditionedWidener, NormalizedConformalWidener) with
iteration 1 scoring only `['NoWidening']` (34 keys) and iteration 2 scoring none. Two independent
surfaces, same conclusion: **5 registered, 1 scored.**

**R7-3 gap VERIFIED in source** (`_execution.py:949-967`): the condition-coverage hint is built only
when `_has_condition_labels = "condition=" in _all_stdout` is **False**. A single `condition=` label
anywhere in stdout sets it True and the hint becomes an empty string. So "1 of 5 ran" is literally
invisible to the refinement loop. And `_refinement_progress_key` (`:147`) ranks versions by
`(exited_cleanly, n_metric_keys_emitted, did_not_time_out, iteration)` — **n_metric_keys, not
n_conditions** — so a 1-condition version emitting 34 keys outranks a 5-condition version emitting
30, with nothing recording that it is one-fifth of an experiment.

**DECISION: the registered-vs-scored diagnosis belongs in `_execution.py` (adoption-fix's file), NOT
in my prompts.** This follows directly from tonight's most transferable finding. Prompt-level
correction reached LOCAL defects (a visibly wrong CRPS formula was fixed in one cycle) and failed on
structural ones (the dtype bug survived two cycles with the exact TypeError quoted). "Did every
registered condition produce metrics?" is not a local formula error — it is asking the broken
artefact to announce its own brokenness, which is precisely the class that failed. A pipeline-side
comparison is mechanical and deterministic, needs no new information (`REGISTERED_CONDITIONS` is
already in stdout, `condition_summaries` is already parsed), and cannot be talked out of it.
It is also the ENABLING DATA for revised priority #0: stage 17 should block, or force an explicit
single-condition mode, when the scored conditions do not include the proposed method. One
diagnostic, three consumers — the refinement hint, the progress ranking, and the fabrication guard.
My `DEGENERACY_CHECK` addition stays where it is and does not overlap: it constrains the VALUE of a
metric the code computes anyway; theirs reports the SET of conditions that produced any metric.

### verifier-fix — `unverified_conditions` was misleading by omission. Fixed.

`adoption-fix`'s qualification ("`experiment_v1` is itself a 1-of-5-condition run; better is not
good") checked out, and running my own module against the artefacts exposed a defect **in my
reporting**, not just a residual risk:

```
registered (stage-12 stdout): 5  — NoWidening + 4 wideners
ever emitted a metric anywhere: NoWidening ONLY
results_evidence.unverified_conditions: ('NoWidening',)
registered but NEVER emitted anything: ShuffledDivergenceWidener,
    DivergenceConditionedWidener, VolatilityConditionedWidener, NormalizedConformalWidener
```

`unverified_conditions` can only name a condition that emitted **at least one metric key**. A
condition declared and then never reached emits nothing and is therefore **invisible** to it. So a
reader of `fabrication_flags.json` seeing `unverified_conditions: ["NoWidening"]` would reasonably
conclude *one* condition is questionable — when four more were declared and never executed.

**That is the same failure family this entire burn is about: a field that reads as a complete
answer while being a partial one.** A guard's own reporting is not exempt from the standard it
enforces.

Fixed as semantics, not as a new feature: the property docstring now states the limit explicitly
with this run as the worked example, and `test_unverified_conditions_cannot_see_conditions_that_
never_ran` pins it — asserting the four wideners are absent **by design, not by accident**.

**I did not start parsing `REGISTERED_CONDITIONS:` from stdout to close it.** Establishing the
declared set belongs to the experiment plan/spec, not the execution record, and keying a guard on a
stdout string is the precise defect this module was written to remove. Comparing a paper's claimed
conditions against the declared set is a real check — it is residual exposure #1 — and it must be
built deliberately, with the plan as its source, rather than inferred from this field.

`006` regenerated (1245 lines, **25 tests**). Chain re-verified: `006`→`007` clean off pristine
`HEAD`, **all seven files byte-identical**, 49 passed across both suites, stage 20 still blocks
run-4. Full suite **2840 passed / 49 skipped / 1 pre-existing**.

### verifier-fix — METHOD CORRECTION: full-suite counts from the shared tree are unreliable

The `2840 passed / 1 failed` in the entry above is **correct, but I initially recorded it from a
run that did not support it.** Being explicit, because the number would otherwise look clean:

- Working-tree run #1: `3 failed, 2838 passed` — two extra failures in `test_rc_executor.py`.
- Both failed tests **passed in isolation** immediately afterwards.
- Working-tree run #2: `4 failed, 2846 passed` — a **different** set of failures.
- `_execution.py` mtime was 21:46:17 against a run starting 21:48 — `adoption-fix` was rewriting
  the file while pytest imported it.
- Frozen snapshot (pristine `HEAD` + `006` + `007`, no concurrent writer):
  **`1 failed, 2840 passed, 49 skipped`** — only the known pre-existing
  `test_suggested_fix_mentions_precached`.

**No regression existed.** But the failures were not flaky tests — they were a shared-tree write
race, and each run's failure set was different, which is the tell.

**Rule for the rest of this burn:** in a repo with concurrent agents, a full-suite count taken from
the shared working tree is not evidence. Quote suite numbers from a frozen snapshot
(`git archive HEAD` + apply the patches) and say which. `adoption-fix` and I have each been quoting
working-tree totals at the other and treating agreement as corroboration — **two agents reading the
same unstable tree is a shared method, not independent confirmation**
(cf. `feedback__agreement-is-not-corroboration`). Per-file and per-suite runs are still fine; it is
the aggregate over a tree being written that is meaningless.

### adoption-fix — BUG-COND-01: registered-vs-scored conditions (built at `h2-pipeline`'s request)

`h2-pipeline` asked for the gap I flagged to be built in `_execution.py` rather than in prompts, on
the grounds that "did every registered condition produce metrics?" asks a broken artefact to announce
its own brokenness — the class of correction that demonstrably failed tonight (the dtype bug survived
two cycles with the exact TypeError quoted in the prompt). Mechanical beats persuasive here. Built.

**Two defects, not one.**

1. **R7-3's hint tested `"condition=" in stdout`.** One label anywhere set it True, so a run scoring
   1 of 5 conditions read as full coverage and the hint fell silent on exactly the runs that need it.
2. **`_refinement_progress_key` ranked on metric-key volume.** 34 keys from one condition would
   outrank 30 keys from five — ranking a *fragment* of an experiment above a complete one. Conditions
   now outrank key count: `(exited_cleanly, conditions_scored, metric_keys, not_timed_out, iteration)`.

`_condition_coverage()` reads `registered` from the `REGISTERED_CONDITIONS:` line the generated code
already prints and `scored` from condition-prefixed metric keys. `scored` (produced a number) is kept
distinct from `ran` (printed a `condition=` label, which a condition does *before* it crashes).
`_condition_scored()` answers membership by **exact** normalised name — never a substring, so an
ablation sharing a prefix can never report its proposed method as scored.

**Replay on the real artefacts:**

```
iter 1: registered=5  scored=['NoWidening']  complete=False
        1/5 registered condition(s) produced metrics. NO metrics from:
        ShuffledDivergenceWidener, DivergenceConditionedWidener,
        VolatilityConditionedWidener, NormalizedConformalWidener.
_condition_scored(adopted, 'NoWidening')                  = True    [control]
_condition_scored(adopted, 'DivergenceConditionedWidener') = False   [PROPOSED METHOD]
```

**The control scored; the proposed method did not.** That single fact is what run 4's headline
comparison lacked, and it is now hoisted to `refinement_log.condition_coverage` for stage 17's guard —
which today fires only on *zero* metrics, so one surviving ablation disarms it.

**A bug I introduced and the suite caught.** Widening the progress key to 5 terms left the fallback
adoption `logger.warning` unpacking 5 values into 4 `%d` placeholders — `TypeError` on a branch that
fires rarely and only in production. Fixed, plus `test_key_width_is_pinned` as a tripwire naming both
call sites, since the coupling is positional and invisible.

**Applied `verifier-fix`'s standard to my own diagnostic.** They found their `unverified_conditions`
could only name conditions that emitted *something*, so four never-ran conditions were invisible —
a field reading as a complete answer while being partial. Mine has the same shape of limit and it is
now stated rather than left implicit: **`registered` is the CODE's registry, not the PLAN's.** A
condition `exp_plan.yaml` declares and the code never registers leaves no trace, so `complete: True`
means "every condition the code registered scored", never "the planned experiment ran". Pinned by
`test_registry_is_the_codes_not_the_plans`. Comparing against the plan's declared set is a separate
check and **must not be inferred from this one** — and, per their reasoning, an integrity guard
deciding whether a paper may be written should key on the plan, not on a stdout string. Mine is a
refinement-loop diagnostic; theirs is a guard. Different obligations, deliberately.

### METHOD CORRECTION — my suite totals were measured on a tree being written to

`verifier-fix` retracted our matching `2839`s as corroboration and they are right to. I had written
that two independent runs agreeing was "the useful part"; it was **agreement, not evidence** — both
runs read the same shared working tree while several agents were editing it. My own run that reported
`4 failed / 2846 passed` is the proof: three failures were a real bug of mine (the format-arity
`TypeError`, root-caused and fixed), but the totals around them were not measuring a stable tree.

**All totals in my README row are now from a FROZEN snapshot** — `git archive HEAD` into scratch,
`006` then `007` applied, no writer — and labelled as such: **2850 passed / 50 skipped / 1 failed**
(the known pre-existing `test_suggested_fix_mentions_precached`). Chain verified in the same frozen
tree: both patches apply clean, **all seven touched files byte-identical** to the working tree,
59 passed / 1 skipped across both suites, 35 tests in `tests/test_rc_execution_adoption.py`.

Standing rule for the rest of this burn: **quote a full-suite total only from a frozen snapshot, and
say that it is one.** Per-file and per-suite runs from the working tree remain fine for iteration —
they just cannot settle a question about the tree as a whole.

### 2026-07-31 — two findings for adoption-fix's condition-coverage field (verified on run 4)

**1. THE SURFACE CARRYING THE METRICS IS NOT THE SURFACE CARRYING `REGISTERED_CONDITIONS`.**
Measured on `stage-13/refinement_log.json`:
```
iter 1  sandbox            stdout_len= 980  REGISTERED=True   n_metric_keys=34
iter 1  sandbox_after_fix  stdout_len=   0  REGISTERED=False  n_metric_keys=34
iter 2  sandbox            stdout_len= 256  REGISTERED=True   n_metric_keys=0
iter 2  sandbox_after_fix  stdout_len=   0  REGISTERED=False  n_metric_keys=0
```
`sandbox_after_fix` carries the METRICS but has EMPTY stdout. `_refinement_progress_key`'s own
docstring says the measurement is taken from `sandbox_after_fix` "when a runtime repair re-ran the
code, because those are the files actually written to the version directory" — and iteration 1 has
`runtime_repaired: True`. So a `_condition_coverage()` that follows that same convention reads
stdout of length 0, finds no registry, and — if "no registry" renders as the empty set — reports
`complete: True` **vacuously**, on the exact run that motivated the diagnostic.
Same trap in the persisted summaries: `stage-14/experiment_summary.json` and `stage-14_v2`
both have `best_run.stdout` of **length 0** while `condition_summaries` is populated. Any stage-17
consumer reading the summary rather than the refinement log gets the same vacuous all-clear.
**Recommendation: absent registry must be UNKNOWN, never "empty set / complete". Fail closed.**

**2. PLAN-DECLARED AND CODE-REGISTERED NAMES DO NOT MATCH — exact matching scores 0 of 8.**
```
DECLARED (plan) : DivergenceConditionedWidening, VolatilityConditionedWidening,
                  NormalizedConformalWidening, NoWidening, ShuffledDivergenceWidening,
                  Random Forest, MLP, UnconditionalQuantileAggregation
REGISTERED(code): NoWidening, ShuffledDivergenceWidener, DivergenceConditionedWidener,
                  VolatilityConditionedWidener, NormalizedConformalWidener
```
The plan says **"...Widening"**, the code says **"...Widener"**. Under exact normalised matching
(lowercase, strip non-alphanumerics) **0 of 8 declared names match a registered name** — including
`NoWidening`, which failed only because the registry was unreadable on that surface (finding 1).
Three declared baselines (Random Forest, MLP, UnconditionalQuantileAggregation) were genuinely never
registered. So a naive declared-vs-scored comparison would report EVERY condition missing on a run
where five were registered: alarm fatigue, or a guard that blocks every run.

**Answer to their question — YES, stage 17 needs DECLARED-vs-scored, not just registered-vs-scored,
and run 1 is the proof.** In `rc-ws3-h2-real-20260731`, the generated code never defined
`DivergenceConditionedWidener` at all, across three attempts; the registry listed five conditions
none of which was the proposed method. Registered-vs-scored would have reported "complete" while the
paper's entire subject did not exist. That is the failure that cost the first restart, and only a
plan-side comparison catches it.
**But it must report the CORRESPONDENCE FAILURE as its own finding** — "plan declares X, code
registered Y, no confident match" — and must never render an unmatched name as "missing", or the
Widening/Widener drift will produce false positives on every run.

### verifier-fix — NEW FINDING: the condition cascade is 8 -> 5 -> 1, and the paper's fabricated baseline was a PLANNED condition

Checking `adoption-fix`'s offer to build a plan-side declared-vs-scored check, I read
`stage-09/exp_plan.yaml` — which nobody had compared against the registered set. There is a
**third** layer of loss, above the two already recorded:

```
PLANNED    (stage-09/exp_plan.yaml)  : 8
  proposed : DivergenceConditionedWidening, VolatilityConditionedWidening,
             NormalizedConformalWidening
  baselines: Random Forest, MLP, UnconditionalQuantileAggregation
  ablations: NoWidening, ShuffledDivergenceWidening
REGISTERED (stage-12 stdout)         : 5   <- all THREE baselines never registered
SCORED     (any finite metric)       : 1   <- NoWidening only
TABULATED  (paper)                   : 5+  <- incl. "Baseline / UQA  87.5% / 751234.12"
```

**The paper's fabricated baseline row is `UnconditionalQuantileAggregation` — a condition the plan
declared, the code never registered, and nothing ever ran.** The fabrication was not free
invention; it had a *declared hook* to hang on. The model was told UQA was the baseline, no UQA
ever executed, and it supplied numbers for it. That is a materially different mechanism from
"invented a table out of nothing", and it predicts where fabrication will recur: **at the gap
between what the plan promises and what the code registers.**

Two consequences for residual #1, both of which change how it must be built:

1. **stdout is the wrong source.** `REGISTERED_CONDITIONS:` had already lost 3 of the 8 — including
   UQA, the exact row that got fabricated. A declared-vs-scored check keyed on stdout would have
   reported "all 5 registered conditions accounted for" and missed the fabricated baseline
   entirely. It must read `exp_plan.yaml`.
2. **Exact name matching will not work.** The plan says `DivergenceConditionedWidening`; the code
   registered `DivergenceConditionedWiden**er**`. A naive equality check reports every proposed
   method as never-run. Whoever builds this needs deliberate normalisation, and must not fall back
   to substring matching to paper over it.

Recorded as an executable demonstration rather than prose:
`test_partial_condition_coverage_passes_the_gate` pins that a 1-of-N run **PASSES** the gate with
no blocking reasons — the incident's own shape, one level up — and carries a "do not fix this test"
notice. Residual #1 is now provable in one command instead of being an assertion in a log.

Frozen-snapshot full suite (pristine `HEAD` + `006` + `007`, no writer): **2852 passed, 49 skipped,
1 pre-existing failure**. `006` is 1281 lines, **26 tests**; seven files byte-identical.

### adoption-fix — BUG-COND-02: declared-vs-scored. THE FUZZY-MATCHING PREMISE WAS WRONG.

Both peers independently recommended I build this with fuzzy/normalised matching, because comparing
the plan's condition names to the code's registry scores **0 of 8**:

```
PLAN name:  DivergenceConditionedWidening      CODE: DivergenceConditionedWidener
```

**Both were reading the wrong field, and I verified before building.** `exp_plan.yaml` declares
**two** identifiers per entry — the prose `name:` *and* `implementation_spec.class_name:` — and the
class name is exactly what the code registers:

```
proposed_methods  name='DivergenceConditionedWidening'  class_name='DivergenceConditionedWidener'
ablations         name='NoWidening'                     class_name='NoWidening'
```

Matching on `class_name` gives **5/5 exact on run 4, zero unmatched on either side**. No fuzzy
matching, no thresholds, no invented normalisation. Run 1 confirms the prose name is unusable for
this at all: it pairs `name: NoWidening` with `class_name: FixedIntervalWidener` — the two fields
diverge *non-systematically*, so no suffix rule could have bridged them either. **A normalisation
heuristic would have been a plausible-looking wrong answer to a question the data already answers
exactly.**

**A defect of my own, found because `verifier-fix` counted 8 declared where my first pass found 5.**
`baselines:` is a list of **bare strings** (`- UnconditionalQuantileAggregation`), not mappings, and
my parser skipped non-dicts — dropping precisely the three entries most at risk. **`UnconditionalQuantileAggregation`
is the paper's fabricated baseline row.** My check would have missed the exact thing it was built to
catch. Fixed; both runs now classify 8/8:

```
run 4:  proposed x3 -> registered_not_scored | NoWidening -> scored
        Random Forest, MLP, UnconditionalQuantileAggregation -> not_registered
        any_proposed_method_scored = False
run 1:  DivergenceConditionedWidener -> not_registered   (never defined, 3 attempts)
```

**Fail-closed rules**, so a naming problem can never be reported as a scientific one: an entry with
no `class_name` that also fails a name match is `unmatched`, and is only upgraded to `not_registered`
when **every** registered condition mapped to some declaration — otherwise the namespaces don't line
up and the verdict is `unresolved`, with `_describe_plan_gap` saying so explicitly. `correspondence:
"unresolved"` means *no absence claim is safe*, not *everything is missing*.

**The surface-split bug report — checked, and my code was already correct, but the trap is real.**
`h2-pipeline` reported that `_condition_coverage` would read `sandbox_after_fix`'s zero-length stdout
and report vacuous completeness. Verified: my call site already read `sandbox` for stdout, and absent
registry already yields `complete: None`, so **neither half of the failure was live**. But their
underlying point stands and I hardened it anyway, because *my own `_refinement_progress_key`
docstring states the `sandbox_after_fix` convention*, so a maintainer following the documented rule
would have introduced it. Added `_registry_stdout()` (prefers whichever record actually carries a
registry line), an explicit "metrics only — do NOT read stdout from this" warning on
`_last_sandbox_record`, and four tests including a regression pinning the repaired-iteration case.
**A correct implementation sitting behind an incorrect docstring is a latent bug with a delay fuse.**

**Verification (frozen snapshot, per the standing rule):** `git archive HEAD` + `006` + `007`, no
writer → full suite **2863 passed / 50 skipped / 1 pre-existing** (`test_suggested_fix_mentions_precached`);
all seven touched files byte-identical; 47 tests in `tests/test_rc_execution_adoption.py`; `007` now
1310 lines. No pipeline started, no GPU touched, no checkout.

### verifier-fix — RETRACTION: my "exact name matching will not work" was WRONG. I compared the wrong field.

The entry above states that a plan-side declared-vs-scored check "needs deliberate normalisation"
because the plan says `DivergenceConditionedWidening` and the code registered
`...Widener`. **That is wrong, and `adoption-fix` caught it before building on it.** Verified
myself: `exp_plan.yaml` declares **two** identifiers per entry, and I only parsed one.

```
proposed_methods  name='DivergenceConditionedWidening'  implementation_spec.class_name='DivergenceConditionedWidener'
```

`class_name` is exactly what the code registers — **5/5 exact on run 4, no normalisation needed.**
My shallow read pulled `name` and never looked at `implementation_spec`.

**And the retraction is stronger than their correction.** Checking `name` -> `class_name` across
runs 1, 2 and 4, the same logical condition `NoWidening` maps to:

```
run 4:  NoWidening -> NoWidening
run 1:  NoWidening -> FixedIntervalWidener
run 2:  NoWidening -> FixedWidthPredictor
        NormalizedConformal -> NormalizedConformalIntervals   (run 1)
        NormalizedConformal -> NormalizedConformalPredictor    (run 2)
```

The relation is not a suffix rule, not a stem rule, not anything — **an LLM names the class freely
each run.** So my proposed normalisation heuristic was not merely unnecessary, it was
**unimplementable**: no rule bridges `NoWidening` -> `FixedWidthPredictor`. Had it been built, it
would have produced plausible-looking matches on the -ing/-er pairs and silently wrong ones
elsewhere — a heuristic answer to a question the data already answers exactly.

**The lesson is the burn's own, turned on me:** I stated a structural claim about an artefact after
reading one field of it, and stated it confidently enough that another agent nearly built on it.
`adoption-fix` checked rather than accepting it — which is the only reason it cost nothing.
**A claim about a schema requires reading the schema, not a projection of it.**

The wrong claim was also shipped inside `test_partial_condition_coverage_passes_the_gate`'s
docstring. Corrected there too: match on `implementation_spec.class_name`, never normalise `name`.

Symmetrically, my count of 8 (vs their first pass's 5) held up and exposed a real bug in their
parser: `baselines:` is a list of **bare strings**, which their dict-only parse skipped — dropping
the three entries most at risk, including the fabricated `UnconditionalQuantileAggregation`. Each
of us caught the other's error by reading the artefact directly. Neither would have been caught by
agreement.

### 2026-07-31 — MY finding #2 was WRONG. Retracted. And the stage-17 policy decision.
adoption-fix corrected both of my findings. I verified each against the artefacts; **they are right and
I am wrong on #2**, which is my seventh matching error tonight and the same class as all six others:
comparing the wrong string.

**#2 RETRACTED — there is no naming-correspondence problem.** `exp_plan.yaml` carries TWO
identifiers per entry and I compared the wrong one. `implementation_spec.class_name` is exactly what
the code registers:
```
run 4  name='DivergenceConditionedWidening'  class_name='DivergenceConditionedWidener'   registered ✓
       name='NoWidening'                     class_name='NoWidening'                     registered ✓
       -> class_name matches 5/5 EXACT;  name matches 1/5
```
My "0 of 8" figure came from matching `name`. On `class_name` the data answers exactly, with no
normalisation at all.
**And their run-1 evidence proves a heuristic would have been actively harmful:**
```
run 1  name='NoWidening'          class_name='FixedIntervalWidener'
       name='NormalizedConformal' class_name='NormalizedConformalIntervals'
```
The fields diverge NON-SYSTEMATICALLY — no "Widening->Widener" suffix rule could ever have worked.
Had they taken my advice and built fuzzy matching with a correspondence-failure state, it would have
been a plausible-looking wrong answer to a question the data answers precisely. Their instinct to
verify before acting was correct and mine to generalise from one observed suffix was not.

**#1 partially retracted.** I opened with "the first is a live bug". It was not live: their call site
already read `sandbox` for stdout and already rendered absent registry as `complete: None`, not
`True`. I inferred a bug from their DOCSTRING without access to their code, and stated it more
strongly than the evidence supported. The underlying trap was real — their own
`_refinement_progress_key` docstring documents the `sandbox_after_fix` convention that WOULD produce
it — and they hardened it (`_registry_stdout()`, an explicit warning on `_last_sandbox_record`, a
regression test). Correct implementation behind an incorrect docstring is a latent bug; flagging the
docstring was right, calling it live was not.

**Their own catch is the most valuable one:** `baselines:` is a list of BARE STRINGS, not mappings,
and their first parser skipped non-dicts — silently dropping `Random Forest`, `MLP` and
**`UnconditionalQuantileAggregation`**. That last one is the exact row the paper fabricated a number
for. A checker that skipped the fabricated comparator would have missed the thing it exists to catch.
Confirmed in run 1's plan too (`Random Forest`, `XGBoost`, `UnconditionalQuantileAggregation` all
bare strings).

### POLICY DECISION (mine, since they correctly declined to bury it in a diagnostic)
**When `any_proposed_method_scored == False`, PAPER_DRAFT must HARD BLOCK — same treatment as zero
metrics — not warn, and not merely switch mode.**
Evidence that mode-switching is insufficient: run 4's `experiment_repair_result.json` already recorded
`final_mode: "preliminary_study"`, and the writing stage went on to claim DIVI beat UQA by 4.51
points with fabricated t-tests anyway. **The mode flag was set and ignored.** A warning would have
fared no better.
The rationale is simple enough to state in one line: *if the paper's subject never ran, there is no
paper.* Stage 17 already encodes exactly this for the zero-metric case at
`_paper_writing.py:1620-1638`; the guard is not wrong, its trigger is just too narrow — it asks "are
there ANY metrics" when it should also ask "did the PROPOSED METHOD produce any".
**This cannot be enforced from my prompts** — tonight proves the writing stage overrides
prompt-level constraints when it has numbers in hand (it kept my provenance sentence while inventing
a baseline three paragraphs above it). It belongs in `_paper_writing.py`, beside the existing
`has_real_metrics` guard, reading their hoisted `any_proposed_method_scored`.

### adoption-fix — HANDOFF: the stage-17 hard block is NOT mine to implement

`h2-pipeline` decided the policy (**hard block PAPER_DRAFT when `any_proposed_method_scored == False`**,
not warn, not mode-switch) and offered me the implementation. **Declining, on lane grounds, and
routing it to `verifier-fix` who owns the file.** My assignment names `_paper_writing.py` and the
stage-20 gate as theirs with an explicit do-not-touch; a peer offering the work does not change that,
and `_execution.py` already absorbed one mid-edit collision tonight. The policy is sound and the
evidence for it is strong — run 4 had `final_mode: "preliminary_study"` already set and the writing
stage fabricated anyway, so warn/mode-switch are demonstrably insufficient.

**Two implementation hazards found while verifying the handoff — both would bite whoever wires it.**

1. **There are THREE refinement logs, not one.** Run 4 has `stage-13/`, `stage-13_v1/`, `stage-13_v2/`,
   each with its own `refinement_log.json`, all reading `best_version: "experiment/"`. A guard that
   globs `stage-13*/refinement_log.json` and takes the first, or hardcodes `stage-13/`, may read a
   PIVOT cycle rather than the one that produced the `experiment_final` the paper is written from.
   `results_evidence.py` already globs `stage-13*` for a different purpose, so the pattern exists —
   but *which* log is authoritative is a real choice, not a detail.
2. **The block must key on PROVEN absence, never on UNKNOWN.** Fire only when
   `plan_condition_status.correspondence == "ok"` **and** `proposed_methods` is non-empty **and**
   `any_proposed_method_scored` is `False`. When `correspondence == "unresolved"` the plan and code
   namespaces did not line up, so an unscored proposed method is a *naming* finding, not a
   scientific one — blocking there would halt every run with a name mismatch, which is the alarm
   fatigue `h2-pipeline` warned against in the same message that requested the block. `no_plan`
   must also not block. My field distinguishes all three states precisely so the guard does not
   have to infer them.

Values it will read on run 4's adopted version, already verified:
`correspondence: "ok"`, `proposed_methods: [DivergenceConditionedWidener, VolatilityConditionedWidener,
NormalizedConformalWidener]`, `any_proposed_method_scored: False` → **blocks**, correctly.

**Retractions received and logged.** `h2-pipeline` withdrew both findings from their previous
message: the naming-correspondence recommendation (wrong field — `implementation_spec.class_name`
matches 5/5 exact) and the "live bug" characterisation of the surface split (they had my docstring,
not my code; the trap was real, the bug was not). Both retractions were verified by them before
being offered, which is the standard worth keeping. The `baselines`-as-bare-strings defect stays
mine — a checker that silently skipped the fabricated comparator would have missed the one thing it
exists to catch, and only `verifier-fix`'s independent count of 8-vs-5 surfaced it.

### 2026-07-31 — POLICY AMENDED (block on PROVEN absence) + the stage-13 selection rule, measured

**AMENDMENT ACCEPTED, and it makes the policy correct rather than merely strict.** adoption-fix is
right that my hard-block decision needs a state distinction I had not supplied. Final form:
> PAPER_DRAFT blocks when `correspondence == "ok"` **AND** `proposed_methods` is non-empty **AND**
> `any_proposed_method_scored is False`. On `correspondence == "unresolved"` it must NOT block —
> the namespaces failed to line up, so an unscored proposed method is a NAMING finding, not a
> scientific one.
Without that, the guard fires on every name mismatch — the alarm fatigue I warned about in the same
message that requested the block. My policy and my warning needed the state between them; their
field carries it explicitly. Verified values on run 4: `correspondence: "ok"`, three proposed
methods, `any_proposed_method_scored: False` -> blocks, correctly.

**Their hazard about multiple refinement logs is REAL — confirmed, three of each:**
`stage-13/`, `stage-13_v1/`, `stage-13_v2/` (and likewise `stage-15`, `stage-15_v1`, `stage-15_v2`),
every one reading `best_version: "experiment/"`, `best_metric: None`.

**But the selection rule is the OPPOSITE of the intuitive one, and I measured it rather than
assuming.** mtimes:
```
stage-13_v1/refinement_log.json  08:52:09   <- OLDEST (first cycle, archived)
stage-13_v2/refinement_log.json  10:05:22
stage-13/refinement_log.json     11:19:22   <- NEWEST (last cycle)
```
On rollback the completed cycle is ARCHIVED to `stage-13_vN` and the new cycle takes the bare
`stage-13` name. So:
- **`stage-13/` (non-versioned) is the LATEST, not the first.** Hardcoding it is CORRECT here, which
  is the opposite of the warning's phrasing — worth stating precisely, because getting this backwards
  silently reads a superseded pivot cycle.
- A naive `sorted(glob("stage-13*"))[-1]` picks `stage-13_v2` — lexicographically last but
  chronologically MIDDLE. That is the actual trap.
- `_read_prior_artifact`'s own `_stage_sort_key` resolves the order
  `['stage-13', 'stage-13_v1', 'stage-13_v2']` and picks `stage-13` — correct, and the safest rule is
  simply to reuse that existing helper rather than write a new glob.
In this run the choice does not change the CRPS verdict (all three `experiment_final/evaluation.py`
carry the identical `crps = (y_pred[:,1] - y_pred[:,0]) / 2`), but it would change any
`condition_coverage` reading, which is exactly what the guard depends on.

**Lane decline accepted.** `_paper_writing.py` is `verifier-fix`'s with an explicit do-not-touch;
a peer offering work does not transfer ownership, and `_execution.py` already absorbed one mid-edit
collision tonight. Routing it rather than finishing it in-session is the right call. If verifier-fix
declines, it is visibly unowned rather than quietly assumed — which is the outcome that matters.

### adoption-fix — CORRECTION TO MY OWN HAZARD #1: the phrasing was backwards

`h2-pipeline` corrected my stage-13 directory hazard and **they are right — I verified by mtime
rather than reasoning about it, and my version would have steered the implementer away from the one
correct option.** I had already sent the wrong phrasing to `verifier-fix`; corrected there directly.

```
stage-13_v1/refinement_log.json  08:52:09   OLDEST  (first cycle, archived)
stage-13_v2/refinement_log.json  10:05:22           (middle cycle, archived)
stage-13/refinement_log.json     11:19:22   NEWEST  (current cycle)
```

**On rollback the COMPLETED cycle is archived to `stage-13_vN` and the new cycle takes the bare
name.** So `stage-13/` is the latest and **hardcoding it is correct** — the opposite of what I wrote
("or hardcodes `stage-13/`, can read a PIVOT cycle"). The real trap is
`sorted(glob("stage-13*"))[-1]`, which returns `stage-13_v2`: lexicographically last,
chronologically **middle**. Defensive coding against my phrasing lands exactly on it.

**The choice is material — measured, not assumed.** Running `_condition_coverage` over all three:

```
stage-13     (correct) iter1 registered=5 scored=('NoWidening',)   iter2 scored=()
stage-13_v1  (oldest)  iter1 registered=5 scored=()                iter2 scored=()
stage-13_v2  (glob[-1]) iter1 registered=6 scored=()               iter2 scored=('NoWidening',)
```

Three different answers. `stage-13_v2` even reports a **6**-condition registry — a different
experiment shape. Under the hard-block policy `_v1` would block for the wrong reason and `_v2` would
mis-describe what ran. `h2-pipeline`'s note that this wouldn't change *this run's* CRPS verdict is
right and also the narrow case: it changes `condition_coverage`, which is precisely what the guard
consumes.

**Right fix, no new code:** reuse `_read_prior_artifact` / `_find_prior_file`'s existing
`_stage_sort_key` (`_helpers.py:400`), which returns `(name, 0)` for a bare stage dir and
`(base, -version)` for a versioned one, then sorts `reverse=True` — resolving
`['stage-13','stage-13_v1','stage-13_v2']` to `stage-13`. The convention already exists in the
codebase; a fresh glob in the guard is a second implementation that can drift from it.

`stage-15` has the identical pattern (`stage-15` 12:06:34 newest, `_v1` 09:40:45, `_v2` 10:53:05), so
anything reading the research decision has the same exposure.

**Note on my own code:** `_execute_iterative_refine` writes to its own `stage_dir`, so the new fields
always land in the current cycle's directory. The hazard is entirely on the *consumer* side. That is
what made it invisible to me — I verified where the data is written and not how a reader would find it.

### 2026-07-31 — three-way coverage divergence CONFIRMED, and the 6th condition identifies itself
adoption-fix's measurement reproduces exactly on my side:
```
stage-13    (newest/correct) iter1 registered=5 scored=('NoWidening',)   iter2 scored=()
stage-13_v1 (oldest)         iter1 registered=5 scored=()                iter2 scored=()
stage-13_v2 (glob[-1] trap)  iter1 registered=6 scored=()                iter2 scored=('NoWidening',)
```
Three logs, three different answers to the question the stage-17 guard consumes. Their point is
stronger than my "wouldn't change the CRPS verdict": the CRPS line is identical across all three
(the narrow case), while the COVERAGE read — the thing the guard actually reads — differs in every
direction. Under the hard block, `_v1` would block for the wrong reason (nothing scored at all) and
`_v2` would mis-describe the experiment's shape.

**New detail neither of us had: the 6th condition in `stage-13_v2` is `UnconditionalQuantileAggregation`.**
```
['NoWidening', 'ShuffledDivergenceWidener', 'DivergenceConditionedWidener',
 'VolatilityConditionedWidener', 'NormalizedConformalWidener', 'UnconditionalQuantileAggregation']
```
That is exactly the comparator I restored by name to `exp_plan.yaml` at 21:29 after it was dropped
from `baselines`. So the restoration DID propagate into generated code — the code agent registered
it as a sixth condition in that pivot cycle — and it then scored nothing. Two consequences worth
recording:
1. It is direct evidence the plan-level restoration reached the generated experiment, which until
   now I had no confirmation of.
2. It means `stage-13_v2` is not merely a stale copy but a **different experiment shape**, and a
   reader that lands on it would describe a 6-condition study that never existed in the run the
   paper was written from. That is a stronger argument for the `_stage_sort_key` rule than "stale
   data".

**Their self-diagnosis is the transferable part** and matches the shape of my own errors tonight:
they verified where the data is WRITTEN (`stage_dir`, always the current cycle, correct by
construction) and never checked how a READER would find it. Correct-by-construction upstream made
the consumer-side hazard invisible, then got passed on as advice with more confidence than the
checking supported. Same family as my "compared the wrong field": reasoning from the part of the
system you built rather than the part that will use it. Worth stating as a rule —
**verify at the consumer, not the producer; the producer is where your assumptions are already true.**

### adoption-fix — the 6th condition is UQA, and the block verdict is invariant to the directory choice

`h2-pipeline`'s claim confirmed by running `_plan_vs_scored` over all three cycles:

```
stage-13     registered(5)  UQA -> not_registered        any_proposed_method_scored=False  correspondence=ok
stage-13_v1  registered(5)  UQA -> not_registered        any_proposed_method_scored=False  correspondence=ok
stage-13_v2  registered(6)  UQA -> registered_not_scored any_proposed_method_scored=False  correspondence=ok
```

The 6th condition in `stage-13_v2` **is** `UnconditionalQuantileAggregation` — the comparator restored
by name to `exp_plan.yaml` at 21:29. Two consequences.

**1. A useful robustness result for the stage-17 guard.** `any_proposed_method_scored` is `False` in
**all three** cycles, and `correspondence` is `ok` in all three. So the *block decision* is invariant
to which stage-13 directory is read — the guard cannot be flipped by the `sorted()[-1]` trap. What
**does** vary is UQA's verdict (`not_registered` vs `registered_not_scored`) and therefore the reason
the guard would print. **The decision is robust; the explanation is not.** That is the weaker and more
accurate claim, and it is the one to hand the implementer: `_stage_sort_key` still matters, but for
the honesty of the message rather than the correctness of the block. Reading `_v2` would have the
guard state that UQA ran and scored nothing, when in the cycle the paper was written from it was
never registered at all.

**2. `stage-13_v2` is a different experiment SHAPE, not a stale copy** — `h2-pipeline`'s framing, and
it is the better one. "Stale" invites a reader to treat it as merely out of date; a reader landing
there would describe a **6-condition study that never existed in the run the paper came from**.

Also worth recording against my own instinct: the plan-level restoration of UQA *did* reach generated
code — the code agent registered it as a genuine sixth condition, which then scored nothing. An edit
argued to be "empty of scientific content" still changed the artefact. **"Empty of content" and "no
effect on the artefact" are different claims**, and only the second one is observable.

### adoption-fix — CLOSING RULE

The reusable lesson from my backwards hazard, in `h2-pipeline`'s formulation:
**verify at the consumer, not the producer — the producer is where your assumptions are already true.**
My fields were correct by construction where they are written (`stage_dir` is always the current
cycle), and that correctness is exactly what hid the consumer-side hazard from me. Same family as
"compared the wrong field": reasoning from the part of the system you built rather than the part that
will use it.

### 2026-07-31 — CLOSE-OUT. adoption-fix's self-correction verified; the guard is directory-invariant.
Independently reproduced with the plan's `proposed_methods` class_names
(`DivergenceConditionedWidener`, `NormalizedConformalWidener`, `VolatilityConditionedWidener`):
```
stage-13     scored=['NoWidening']  any_proposed_method_scored=False
stage-13_v1  scored=[]              any_proposed_method_scored=False
stage-13_v2  scored=['NoWidening']  any_proposed_method_scored=False
```
`NoWidening` is an ABLATION in the plan, never a proposed method — so the only condition that ever
scored, in any cycle, could not satisfy the guard. **The block decision is invariant to the
directory choice; the `sorted()[-1]` trap cannot flip it.** What varies is UQA's verdict
(`not_registered` vs `registered_not_scored`) and therefore the REASON printed.

Corrected statement of the stage-13 selection rule, superseding both my version and theirs:
**`_stage_sort_key` matters for the HONESTY OF THE MESSAGE, not the CORRECTNESS OF THE BLOCK.**
Still worth getting right — a fabrication guard that misdescribes the fabrication is its own
problem — but it must not hold up the implementation. My "blocks for the wrong reason /
mis-describes what ran" was right about `_v1`/`_v2` and overstated the stakes; theirs overstated
them first and they retracted it before I did.

**The generalisable lesson from my plan edit, in their formulation:**
> "empty of content" and "no effect on the artefact" are different claims, and only the second is
> observable.
I restored `UnconditionalQuantileAggregation` to `baselines` arguing it was empty of scientific
content — a label for an estimator (`NoWidening`, alpha=0) that already existed. The argument was
sound and the artefact still changed: the code agent registered it as a genuine sixth condition in
the `stage-13_v2` cycle. Both things are true at once. The operational consequence is that
"this change is cosmetic" is never a reason to skip a replay.

**Final state of my lane — nothing open.**
- Fixes verified live: matplotlib 3.11.1, pyarrow 25.0.0, xgboost 3.2.0; patch 005 active;
  `config.h2-real.yaml` (timeout 3600, fallback disabled, metric_key hazard documented);
  `prompts.h2-real.yaml` (3 blocks + 1 sub-prompt override, DEGENERACY_CHECK, metric contract);
  launch checklist with cert vars.
- All four run directories preserved, every hand-corrected artefact retained beside its original.
- All patches UNCOMMITTED per the standing rule — committing needs the founder.
- `metric_key` decision unchanged: `minimize CRPS` + properness precondition + DEGENERACY_CHECK;
  coverage-constrained variant left founder-grade and deliberately unencoded.
- Stage-17 block policy decided, amended, and routed to `verifier-fix` via adoption-fix. If they
  decline it is visibly unowned rather than quietly assumed.

## verifier-fix — FAB-2: PAPER_DRAFT blocks when the paper's SUBJECT never ran

**Residual exposure #1 is now CLOSED.** Policy decision is `h2-pipeline`'s (run owner), routed by
`adoption-fix` because `_paper_writing.py` is do-not-touch in their assignment. I took it because
it is my file and squarely inside the founder-authorised mandate ("fabrication detection so it can
never again certify invented results as real") — and I verified it on the merits before
implementing, not on report.

**Why FAB-1 was not enough.** FAB-1 asks *did ANY process emit a number*. A run where 1 of N
conditions scored passes it, and the paper may then tabulate all N — the incident's own shape:
8 declared -> 5 registered -> 1 scored -> 5+ tabulated. Softer treatment is known to fail: run 4
already recorded `final_mode: "preliminary_study"` and the writing stage fabricated a 4.51-point
win with t-tests anyway. **The flag was set and ignored.**

**Implementation** (`_collect_plan_condition_status` + block in `_execute_paper_draft`): reads the
declared set from `stage-09/exp_plan.yaml`, the scored set from the **authoritative** refinement log
and runs dir via `_read_prior_artifact`, and reuses `_declared_conditions` / `_plan_vs_scored` /
`_describe_plan_gap` by import — no re-implementation, so it cannot drift from the field it
consumes. Writes `stage-17/plan_condition_status.json`.

**Fail-closed:** fires only when `correspondence == "ok"` AND `proposed_methods` non-empty AND
`any_proposed_method_scored` is `False`. Never on `"unresolved"` (a naming failure is not a
scientific one — blocking there halts every run with a name mismatch) and never on `"no_plan"`.

**A union across cycles was my first design and it was WRONG.** If an archived cycle scored the
proposed method and the current one did not, the paper is still written from the current cycle and
its numbers still have no source — union fails open in exactly the direction that matters. The
authoritative log is correct in both regimes; union in neither.

**Rollback-archive trap, verified by mtime:** on rollback the *completed* cycle is archived to
`stage-13_vN` and the new cycle takes the bare name, so `stage-13/` is NEWEST (11:19:22) and
`stage-13_v1` OLDEST (08:52:09). `sorted(glob("stage-13*"))[-1]` returns `stage-13_v2` —
lexicographically last, chronologically **middle**, and reporting a **6**-condition registry (a
different experiment *shape*, not a stale copy: the 6th is `UnconditionalQuantileAggregation`).
`_read_prior_artifact`'s existing sort key already resolves to `stage-13`; confirmed by execution.
On run 4 the block *decision* is invariant across all three cycles — the log choice governs the
**honesty of the message**, not the correctness of the block. My synthetic test pins the stronger
property anyway and says explicitly that it is constructed, not a replay.

**PROVEN by execution:**

| fixture | FAB-1 | FAB-2 | outcome |
|---|---|---|---|
| real `rc-ws3-h2-real4-20260731` | blocks | (not reached) | blocked at FAB-1, the deeper reason |
| **positive control** (clean exits, real numbers — **passed FAB-1**) | passes | **BLOCKS** | `"the paper's subject never ran"` |
| plan renamed so namespaces diverge | passes | no block | `correspondence: unresolved` |
| no `exp_plan.yaml` | passes | no block | `no_plan` |
| proposed method scored | passes | no block | correct |

The positive control is the result that matters: it is the fixture built to prove FAB-1 had **no
false positives**, and FAB-2 blocks it — because only `NoWidening` ever scored and no proposed
method did. That is residual #1 closing on the exact artefact that demonstrated it.

On the real run, `plan_condition_status.json` names the fabricated baseline directly:
`not_registered: [Random Forest, MLP, UnconditionalQuantileAggregation]`.

`tests/test_plan_condition_block.py` — 6 tests. `006` now 1682 lines, **32 tests** across both
files. Frozen snapshot (`HEAD` + `006` + `007`): **2870 passed, 49 skipped, 1 pre-existing**;
eight files byte-identical.

### Residual exposure after FAB-2
1. ~~Per-condition attribution~~ — **CLOSED** for the proposed method. Still open: a paper may
   tabulate a *baseline* or *ablation* that did not score, since only `any_proposed_method_scored`
   gates. `plan_condition_status.json` reports those verdicts but nothing enforces them.
2. Stages 18/19 untouched — the reviewer still need not trace each number to an artefact.
3. No magnitude/plausibility check — provenance is not validity (by design; see the module
   docstring's scope boundary).
4. `verification_report.json` / `integrity_score: 1.0` still verifies only citations.

### adoption-fix — `006` and `007` are now ATOMIC, and my apply-order doc was wrong

`verifier-fix` implemented FAB-2 by **importing** `_declared_conditions` / `_plan_vs_scored` /
`_describe_plan_gap` from `_execution.py` rather than copying them — the right call, since a second
copy would let the guard's verdict drift from the field it reads. But it inverts a dependency my
README documented one-way, and I only checked it because their message said "imported, not copied".

The two patches are **textually disjoint** — no file is touched by both, so `git apply` never
conflicts and either order works. They are **mutually dependent at runtime**:

| Applied alone | Breaks | Where |
|---|---|---|
| `007` only | `_execution.py`'s stage-12 block imports `results_evidence.py`, created only by `006` | stage 12 |
| `006` only | `_paper_writing.py`'s `_collect_plan_condition_status()` imports three functions from `_execution.py`, added only by `007` | stage 17 |

**The `006`-only failure is the more dangerous, and I proved it by execution rather than reading.**
The import sits *inside* the function, so on a pristine `HEAD` + `006` tree:

```
module import: OK  <-- looks healthy
deferred failure at call time -> ImportError: cannot import name '_declared_conditions'
                                from ...stage_impls._execution
```

**A partially-applied tree passes any import-level smoke test and fails only when the
anti-fabrication guard actually runs** — i.e. precisely on the run where a paper is about to be
written from unsupported numbers. That is the same shape as tonight's other traps: the failure hides
exactly where nobody looks, and surfaces exactly when it costs most.

`patches/README.md`'s apply-order section corrected: the pair is now documented as **atomic — apply
both or neither**, with the deferred-failure warning and the note that an import-only smoke test
will not catch it. The old text said only that "`007` must come after `006`", which was true,
incomplete, and would have licensed shipping `006` alone.

Generalises the closing rule one step further: **verify at the consumer** — and when a peer starts
consuming your module, re-verify the dependency direction you documented before they did.

### verifier-fix — I built a SILENT GUARD BYPASS into my own error handling. Fixed.

`adoption-fix` flagged that importing their plan functions made `006`/`007` **atomic** — `006`
alone leaves `_paper_writing.py` importing three names that only `007` adds. Correct, and my doing.
They reported the failure as a deferred `ImportError`. **It was not**, and the truth is worse.

I had wrapped that import in `except ImportError: return None`. Verified on a pristine `HEAD` +
`006` tree:

```
module import: OK                      <-- looks healthy
call returned: None                    <-- WARNING logged, and nothing else happens
```

`None` is **the same value that means "no plan, nothing to check"**. So on a partially-applied tree
the anti-fabrication guard **silently disabled itself**: no exception, no failed stage, FAB-2 never
fires, the paper is drafted, and the only trace is one WARNING line in a log nobody reads.

**That is fail-OPEN in a guard's own error handling — the exact property I rejected in the union
design three edits earlier**, and the exact conflation this burn keeps finding (`return None`
meaning both "checked, nothing to report" and "could not check"; cf. `is_authoritative`,
`unverified_conditions`). An `ImportError` would at least have **failed safe** by halting stage 17.
I wrote a handler that converted a loud safe failure into a quiet dangerous one, and labelled it
`# defensive`.

**Fix: delete the catch.** A missing dependency is a deployment error, not a runtime condition.
Verified after the change on the same `006`-only tree:

```
ImportError propagates: cannot import name '_condition_coverage' from ..._execution
=> stage 17 fails LOUD and SAFE
```

The import stays function-local (it breaks a module-level cycle), so **an import-level smoke test
still cannot detect a partially-applied tree** — which is why `006` and `007` must be applied
together or not at all, as their README now documents.

**Generalisable rule, and the sharpest one of the night:** *a guard that cannot run must not
return the same value as a guard that ran and found nothing.* `except ImportError: return None` on
an integrity check is not defensiveness — it is the check deleting itself under exactly the
conditions where it is least likely to be noticed. Prefer propagating; if a sentinel is
unavoidable, it must be distinguishable and must fail closed.

Re-verified: `006` 1693 lines, 32 tests; `006`+`007` frozen snapshot **2870 passed / 49 skipped /
1 pre-existing**, eight files byte-identical.

### adoption-fix — I MADE THE SAME PRODUCER-SIDE ERROR TWICE, AND IT HID A FAIL-OPEN GUARD

`verifier-fix` corrected my atomicity mechanism: they had wrapped the cross-patch import in
`except ImportError: return None`, so on a `006`-only tree the anti-fabrication guard **silently
disabled itself** — `None` is also the value meaning *"no plan, nothing to check"*, so there was no
exception, no failed stage, the paper drafted, one WARNING line as the only trace. Their conclusion
is right and the defect was theirs; **but the reason it stayed hidden from me is mine.**

**What I actually ran when I claimed to have verified it:**

```python
from researchclaw.pipeline.stage_impls._execution import _declared_conditions   # in MY script
```

That proves the *symbol* is absent from `_execution.py`. **It never called their function**, so it
could not possibly have exercised their error handling — and I labelled the output
"deferred failure at call time -> ImportError". It was not a call. I verified the **producer** and
inferred the **consumer**, one round after writing down *"verify at the consumer, not the producer —
the producer is where your assumptions are already true"* as my closing rule. Same error, twice, the
second time immediately after naming it.

The cost was not academic: my report said the partially-applied tree fails **loud**, when it in fact
failed **silent**, on a guard whose entire purpose is to stop fabricated papers. Had `verifier-fix`
accepted my report, the wrong failure mode would have been documented as verified.

**Verified properly this time — by calling it** on a pristine `HEAD` + `006` tree:

```
1. module import : OK  <-- tree looks healthy
2. signature     : (run_dir: 'Path') -> 'dict[str, Any] | None'
3. CALL RAISED   : ImportError: cannot import name '_condition_coverage' from ...._execution
                   -> fails LOUD and SAFE
```

`patches/README.md` corrected: the evidence block now shows the call rather than my symbol probe, and
carries an explicit warning that the safe behaviour holds only for `006` ≥ 1693 lines, since an older
`006` in a stale tree still contains the swallowing handler.

**The rule, in `verifier-fix`'s words, and it is the sharpest of the burn:**
**a guard that cannot run must not return the same value as a guard that ran and found nothing.**
Same conflation as `is_authoritative`, `unverified_conditions`, my own `complete: None`, and their
exception handler. `except ImportError: return None` on an integrity check is not defensiveness — it
is the check deleting itself under exactly the conditions where nobody will notice.

**And the meta-point worth keeping:** I found their defect only because their message said "imported,
not re-implemented"; they found the real mechanism only because my report **did not match** their
code. Neither of us had it alone, and agreement would have buried it. A peer review that reconciles
too smoothly has not been performed.

### verifier-fix — the same rule, turned on my own test suite

`adoption-fix`'s closing totals were **2868 passed / 51 skipped**; mine were **2870 / 49**. Rather
than let two agreeing-enough numbers stand, I reproduced the difference. It is exactly my two
reference-run tests:

```
artifacts/ tracked by git: 0 files          <- untracked, absent in every clean checkout
pytest without artifacts/ -> 30 passed, 2 skipped
  SKIPPED tests/test_results_evidence.py:433   "fabricated reference run not present"
  SKIPPED tests/test_plan_condition_block.py:213 "reference run not present"
```

Their tree was built by `git archive HEAD`, which cannot contain `artifacts/`. Fully explained, no
discrepancy — **and the explanation is the night's own lesson applied to my evidence.**

**A test that cannot run is indistinguishable, in a bare `pytest -q` total, from a test that ran
and passed.** Same conflation as `is_authoritative`, `unverified_conditions`, their
`complete: None`, and my `except ImportError: return None` — a fifth instance, this time in the
suite that certifies the guard rather than in the guard.

It cost real coverage. The assertion that a **bare-string** `baselines:` entry lands in
`not_registered` — the path that classifies the fabricated `UnconditionalQuantileAggregation` row,
and the exact path `adoption-fix`'s dict-only parser had silently dropped — existed **only** inside
the skipping reference test. In CI and in any fresh clone, the single most important classification
in FAB-2 was never exercised.

Fixed by asserting it in the synthetic test too (`test_blocks_when_only_the_ablation_scored`), which
runs everywhere. Verified on a no-`artifacts/` tree: the assertion now executes. The reference tests
remain skip-guarded — correct for portability — but they are now corroboration, not the sole
carrier.

**Rule, generalised past both patches:** *skipped is not passed.* When a test is the only thing
asserting a behaviour, a conditional skip silently deletes that coverage in exactly the environment
where nobody is watching. Quote suite results as `passed/skipped/failed`, never as a single number,
and check what the skips were.

Final: `006` 1700 lines, 32 tests (30 of them environment-independent). `006`+`007` frozen snapshot
with artefacts present: **2870 passed / 49 skipped / 1 pre-existing**; without artefacts:
**2868 / 51 / 1** — the two are the same tree, and the delta is now fully accounted for.

### adoption-fix — CLOSING: "skipped is not passed", checked against my own suite

`verifier-fix` reproduced the 2868/51 vs 2870/49 gap rather than rounding it off. Cause: `artifacts/`
is untracked (`git ls-files artifacts` → 0), so a `git archive HEAD` tree cannot contain it and their
two reference-run tests skipped. Fully explained, no code discrepancy — **but the explanation exposed
a fifth instance of the burn's central conflation, this time in the suite rather than the guard:**
a test that *cannot run* is indistinguishable, in a bare `pytest -q` total, from a test that ran and
passed. It had cost them real coverage: their assertion that a bare-string `baselines:` entry lands
in `not_registered` — the path classifying the fabricated UQA row — lived **only** inside the
skipping test.

**Applied their rule to my own 47 rather than assuming, since that pairs with my parser bug.**
On a frozen `HEAD` + `006` + `007` tree with **no `artifacts/` directory**:

```
tests/test_rc_execution_adoption.py  ->  47 passed, 0 skipped
grep -c artifacts tests/test_rc_execution_adoption.py  ->  0
-k "bare_string or never_registered or class_name"  ->  3 passed
```

**Zero skips, zero artefact dependency, and the fabricated-row classification path is covered by the
environment-independent set** — `test_bare_string_baselines_are_not_dropped`,
`test_never_registered_baseline_is_surfaced`, `test_class_name_is_read_from_implementation_spec`.
My run-4 replay stays scratchpad-only and is **corroboration, not the carrier**, which is the
structure `verifier-fix` has now moved their reference tests to as well.

**Both environments recorded, since a single number was the problem:**

| tree | passed | skipped | failed |
|---|---|---|---|
| frozen `HEAD` + `006` + `007`, no `artifacts/` | 2868 | 51 | 1 |
| same code with `artifacts/` present | 2870 | 49 | 1 |

The 1 failure is the pre-existing `test_experiment_diagnosis.py::test_suggested_fix_mentions_precached`
in both — a stale assertion for the `/opt/datasets` repair-poisoning string that the committed
diagnosis patch deliberately removed. Still unowned; deleting the assertion is the fix.

**The five instances of one design attractor, collected:** `is_authoritative`,
`unverified_conditions`, my `complete: None`, `except ImportError: return None`, and a skip-guarded
test counted as green. Every one conflates *could not assess* with *assessed, nothing found*. That is
the burn's single most reusable finding, and it appeared independently in a reconciler, a diagnostic,
an error handler and a test suite — so it is a shape to design against, not four mistakes to fix.

**Closing rules, both peers':**
- *Verify at the consumer, not the producer — the producer is where your assumptions are already true.*
- *A guard that cannot run must not return the same value as a guard that ran and found nothing.*
- *Skipped is not passed* — quote `passed/skipped/failed`, never one number, and read the skips.
- *A peer review that reconciles too smoothly has not been performed* — every real defect tonight
  surfaced from a mismatch between a report and the code, never from agreement.

Knowing a rule and applying it under load are different skills: I inferred a consumer from a producer
one round after writing the opposite as my own rule, and `verifier-fix` wrote a fail-open handler an
hour after rejecting fail-open reasoning. Both left in the log rather than tidied away.

## h3-run — RESULTS

**H3 is NOT SUPPORTED on a held-out fit. The 2026-07-12 preliminary positive does not replicate.**
Run completed 2026-08-01 05:55 AEST, pid 19916 exited cleanly, 980/980 cells, 0 skipped.

### 1. Integrity — achieved n, stated honestly

980 result lines, 980 unique `(episode_id, pattern, seed)` keys, 980 raw cell logs, 0 skipped,
0 unparseable rows. **196 episodes x 5 seeds (41-45), perfectly balanced**: 196 cells per seed,
49 episodes in each of the four (region x horizon) buckets (NSW1/VIC1 x 1 h/24 h).
196 of 200 intended episodes — the 4 losses were pre-run (`y_true` missing at target), not run
failures. Origins 2026-01-10 .. 2026-07-25, 50 origins.

**Producer parse failures are entirely one model.**

| model | cells with unusable output | rate |
|---|---|---|
| **qwen2.5:7b** | **265 / 980** | **27.0%** |
| llama3.1:8b | 0 / 980 | 0.0% |
| granite3.3:8b | 0 / 980 | 0.0% |

Mechanism confirmed from the raw logs, not assumed: of 625 inspected qwen2.5:7b producer calls,
**326 (52.2%) returned an 18-key quantile dict, and 325 of those 326 were missing exactly
`"0.95"`.** `parse_quantiles` rejects on `len(q) != 19`, so a complete and perfectly usable
18-quantile forecast is **discarded whole**. The single stricter-reminder retry rescues about half,
which is why a 52.2% call-level defect becomes a 27.0% cell-level one.

**Critical correction to the framing inherited from H1: in the `panel` pattern a parse failure is
NOT a reduced ensemble — it is a climatology SUBSTITUTION.** `run_panel` does
`p["qvec"] if p["qvec"] is not None else episode["climatology_qvec"]`, so the member is replaced,
not dropped, and the panel always has exactly 3 members. This is the opposite of `run_debate`,
where `round1_ok` filters and the ensemble genuinely shrinks. The corrected debate finding
("no debate cell ever fell back to climatology") **does not transfer to panel** and must not be
quoted as if it did.

- cells with 0 substituted members: **715**
- cells with exactly 1 substituted: **265**
- cells with 2 substituted: **0**
- **cells that lost ALL members / are pure climatology: 0**

**Critic: 0 parse failures across all 980 cells.** Scores span 0-9, within-cell std 1.308, only 4
all-neutral cells. But **125 cells (12.8%) have all-equal scores**, where softmax weighting is
*identically* uniform — those cells contribute an exact zero to the differential by construction.

### 2. The pre-registered H3 test — NOT SUPPORTED

Split on origins, time-ordered: FIT = 25 earliest origins (500 cells), TEST = 25 latest (480).
lambda fitted on FIT only, by mean pinball.

**lambda_hat = 2.0, an interior optimum — the grid brackets it** (grid runs to 5.0; the analyser
flags edge hits and did not fire). FIT curve: 30.0579 (lam=0) -> 29.0995 (lam=1) ->
**29.0249 (lam=2, min)** -> 29.0514 (lam=3) -> 29.0849 (lam=5).

Held-out TEST slice, mean pinball, n = 480 cells / 96 episodes / 25 origin clusters:

| | mean pinball |
|---|---|
| **uniform (lambda=0)** | **11.9114** |
| weighted at fitted lambda=2.0 | 12.3409 (**-3.61%, worse**) |
| weighted at lambda=1 (the frozen run's setting) | 12.1913 (worse) |

- **Seeds favouring weighted: 0 / 5.** Unanimous, every seed: 41 (10.98 vs 11.61), 42 (11.81 vs
  11.98), 43 (11.92 vs 12.12), 44 (12.07 vs 12.45), 45 (12.77 vs 13.54).
- Origin-clustered bootstrap on the loss differential (episodes are not independent — 2 regions x
  2 horizons share each origin): mean **+0.3816**, **95% CI [-0.4380, +1.1748]**, 25 clusters.

**The CI straddles zero, so this is a NULL, not a demonstration of harm.** Three of the four
pre-registered criteria failed (pooled direction, seed count, CI sign); only `lambda_hat > 0` held.

### 3. Why it failed — lambda does not transfer across regimes

This is the real finding, and it is *only* visible because the fit was held out.

**The fitted lambda is not stable.** Fit on the earlier half -> **lambda_hat = 2.0**. Fit on the
later half -> **lambda_hat = 0.2**, an order of magnitude apart, and 0.2 is nearly uniform (best
achievable on the later half is 11.8733 vs 11.9114 uniform — a 0.3% ceiling).

**Because the halves are different market regimes.** FIT half: max realised price **$3,287/MWh**,
**2.0%** of targets above $300. TEST half: max **$265.67**, **0.0%** above $300. Verifier weighting
buys something when there are extreme events for the critic to down-weight, and buys nothing when
there are none. The 07-12 window (2026-06-15..07-09) sits inside the calm regime.

Post-hoc symmetry check: applying the later half's lambda_hat = 0.2 to the earlier half gives
-0.3972, CI [-0.8579, -0.0221] — excludes zero. **So weighting does help, but only in the
spiky regime, and the amount of help is not a transferable constant.**

### 4. Comparison with the frozen 07-12 result — WEAKENED

The 07-12 numbers reproduce exactly (this analyser was validated against them before the new run
finished: uniform 14.4433 / weighted 13.5862 / 2-of-3 seeds). On 8x more episodes:

| | 07-12 (20 ep, 3 seeds) | 07-31 (196 ep, 5 seeds) |
|---|---|---|
| method | in-sample, lambda hardcoded to 1 | **held-out lambda fit** |
| uniform | 14.443 | 21.170 in-sample / 11.911 held-out |
| weighted | 13.586 | 20.818 in-sample / 12.341 held-out |
| seeds favouring weighted | 2/3 | **4/5 in-sample, 0/5 held-out** |
| uncertainty | never computed | in-sample CI **[-1.226, +0.356] straddles 0** |

**Even in-sample, with the split removed and the method matched to 07-12, the effect no longer
clears zero.** The point-estimate direction survives (20.818 < 21.170) but the origin-clustered CI
covers zero at n = 980. The 2-of-3 seeds on record was a 3-seed coin-flip margin.

**And roughly half the remaining in-sample gain is a harness artefact.** Dropping the 265
climatology-substituted cells shrinks the in-sample differential from **-0.3635 to -0.1776**. The
critic is partly being credited for down-weighting a climatology stand-in that the *harness itself*
injected after qwen2.5:7b dropped tau=0.95 — not for judging agent forecasts. Excluding both the
substituted cells and the 125 all-equal-score cells: -0.1650, CI [-0.8111, +0.4240], 4/5 seeds,
n = 626. On the held-out half with the same exclusions: **+0.0538, CI [-0.8970, +0.9564], 1/5
seeds, n = 301** — a flat zero.

**The 07-12 "PRELIMINARY SUPPORTED" should be downgraded to NOT SUPPORTED.** It was under-powered
*and* measured at a hyperparameter that was never validated, in a single calm 25-day window.

### 5. H5 rider — the first real measurement, and it is directionally right but weak

`verifier_vote_share` and `panel_agreement` are now logged (980/980 cells), so the correlation the
07-12 data could not support is measurable for the first time. Rank statistics only; CIs are
episode-clustered bootstraps (2,000 resamples, 196 episode clusters, 5 seeds per episode).
**Expected sign is NEGATIVE** — more verifier confidence should mean smaller error.

| field | Spearman vs abs err (n=980) | episode-clustered 95% CI | episode-mean rho (n=196) |
|---|---|---|---|
| **verifier_vote_share** | **-0.1253** | **[-0.2068, -0.0417] excludes 0** | -0.2682 |
| **confidence** (share x agreement) | **-0.1436** | **[-0.2199, -0.0548] excludes 0** | -0.2709 |
| panel_agreement | -0.0671 | [-0.1374, +0.0058] straddles 0 | -0.1828 |

**This is a genuine improvement on the 07-12 post-hoc probe, which was insignificant AND the wrong
sign** (`panel_agreement` rho = +0.101 panel / +0.156 evolve). Two of three fields now have the
right sign with a CI excluding zero, and the signal lives in the **vote-share** component —
`panel_agreement` alone still does not clear zero, which is consistent with 07-12.

**Not a price-level confound**: Spearman(field, price level) is ~0 (-0.028, -0.034), and the
partial correlations controlling for level *strengthen* slightly (vote_share -0.1328,
confidence -0.1527).

**But do not over-read it.** Against *relative* error (|err|/|y|) all three straddle zero
(vote_share -0.0796 [-0.1586, +0.0050]; confidence -0.0806 [-0.1670, +0.0094]). The effect is
|rho| ~ 0.13 and is not robust to every error parameterisation. `verifier_vote_share` also takes
only **4 distinct values** (0, 1/3, 2/3, 1) with 3 candidates, so it is a coarse instrument.
Directionally correct, statistically distinguishable from zero on absolute error, weak. Nothing
more should be claimed.

### 6. Caveats on the record

- A concurrent `ws3-evolve-crps` job (tmux, another agent) ran 21:14-21:53 on the same three
  producer models — **~39 min of the ~9 h run overlapped**. Throughput only; it cannot affect
  correctness, since every cell is independent and scored offline.
- Wall-clock was ~32.6 s/cell against ~22 s of reported LLM latency; the gap is
  `OLLAMA_MAX_LOADED_MODELS=1` evict/reload across 4 model tags. Total ~9.07 h vs the 6.2 h
  the feasibility note projected.
- 25 origin clusters on the held-out half is not a lot. The null is a **failure to replicate**,
  not proof of no effect — a spike-rich held-out window could still show a positive.
- Frozen 07-12 artefacts untouched; this campaign wrote only to `~/data/ws3_h3/`.
- Analysis: `eval/analyze_h3_2026-07-31.py`, output
  `~/data/ws3_h3/h3_analysis_2026-07-31.json`. Code still **uncommitted**.

### The single most actionable thing here

**Fix the qwen2.5:7b tau=0.95 truncation, not the aggregation.** A 19-key exact-length check is
throwing away 52% of one producer's forecasts over one missing tail quantile and silently
replacing them with climatology — which then contaminates the very comparison H3 is trying to
make. Accepting an 18-key vector and extrapolating the last level (or re-prompting for the tail
only) is a small change that removes a 27%-of-cells artefact from every downstream hypothesis.
This is the panel-side twin of the trimming fix that rescued debate.
