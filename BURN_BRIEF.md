# FULL BURN BRIEF — genuine Hive research output from AutoResearchClaw
Coordinator session: "Fable orchestrator — ARCLAW full burn", started 2026-07-31 01:22 AEST.
All subagents READ THIS FIRST. Append your findings to `BURN_LOG.md` (never overwrite).

> **NOTE FOR SESSION "Deploy AutoResearchClaw + Ollama on fleet"** (`local_460b3498`), if you are
> reopened: this workstream has been taken over at Alexey's direction. **Do not resume it** — you
> would collide with running agents on the shared box. Your deployment record and the NEM DuckDB
> find were both high quality and are the basis of this burn. The one thing you could not have
> known, because you stopped at 14:36Z: **the H2 run FAILED at stage 17** (details below).
> I could not message you directly — `send_message` is unavailable in unattended sessions.

## Founder's actual ask
Genuine Hive research output out of the AutoResearchClaw + Ollama deployment — **properly, not
a synthetic-data proof of concept**. Sustained burn, not one pass.

## GROUND TRUTH as of 2026-07-31 01:22 AEST (verified, not reported)

### The H2 run FAILED
`rc-20260730-114801-e9b01a`, qwen2.5:72b-instruct, mode `sandbox`, host m5-prime-serve.
- `/api/pipeline/status` → `{"status":"failed","stages_done":19,"stages_failed":1}`
- `pipeline_summary.json` → `final_stage: 17`, `final_status: "failed"`, `stages_executed: 20`
- checkpoint/heartbeat → `last_completed_stage: 16 (PAPER_OUTLINE)`, ts `2026-07-30T14:47:47Z`
- **Stage 17 PAPER_DRAFT is where it died.** Died 00:47 local; nobody was watching.
- `experiment_repair_result.json` → 3 repair cycles, all `"score 0.0 -> 0.0"`,
  `final_mode: "technical_report"`, `success: false`
- `deliverables/` contains ONLY `manifest.json` + `neurips_2025.sty`. **There is no paper.**
- Stage 14 was repaired 3× (`stage-14_repair_v1..v3`); 13 and 15 each have a `_v1`.
- The console server has since been restarted (serve.log shows a clean shutdown + new PID),
  so the old run's stdout is GONE from serve.log. Use the per-stage dirs as the record.

### The real-data situation — THIS IS THE CRUX
`~/data/nem_market.duckdb` on m5-prime-serve is **live, 1.01 GB**, fed by
`~/scripts/aemo_nem_scraper.py` under launchd, mtime tracks the current 5-min interval.
**Open READ-ONLY — the scraper holds the write lock, DuckDB is single-writer:**
```python
duckdb.connect('/Users/alexeynikitine/data/nem_market.duckdb', read_only=True)
```
Key table: `p5min_price_forecast(run_datetime, interval_datetime, regionid, rrp, intervention)`
holds **~11.5 forecast vintages per target interval** for VIC1 — that IS a real ensemble whose
dispersion can be scored against realised `dispatch_price.rrp`. No new integration needed.

A 10-minute manual query already tested H2 on **84,575 real matched pairs**:
Pearson r(D,|err|) = 0.638, Spearman 0.672, monotone quintile ladder of mean |err|
2.40 → 4.95 → 6.74 → 9.93 → 44.50 $/MWh. **H2's null is REJECTED on real NEM data.**

Two caveats that MUST travel with that number:
1. It is AEMO's own model-vintage ensemble, **not** the WS3 multi-agent LLM ensemble. It tests
   the statistical mechanism, not the LLM-debate instantiation. Never report it as
   "H2 confirmed for debate ensembles."
2. Heteroskedasticity confound — volatile intervals inflate both D and |err|, so raw correlation
   overstates usable signal. This is exactly why the paper specifies CRPS and interval coverage
   for gamma(D)-widening rather than correlation. The quintile ladder is the defensible artefact.

**But the failed run used SYNTHETIC heterogeneous predictors, not this data.** Closing that gap
is the single highest-value action in this burn.

### Known blocker: figures are dead on BOTH paths
`matplotlib` is declared in the `all` extra, **not `web`** (`pyproject.toml:26`), and the install
of record was `pip install -e ".[web]"`. Result:
1. Docker route → `researchclaw/experiment:latest` is neither on Docker Hub nor built locally.
2. Fallback route → `matplotlib not available - skipping chart generation`.
3. Nano Banana → correctly disabled (needs Gemini).
Fix: `pip install -e ".[all]"` (or just matplotlib). **NEVER pip-install into the venv of a
running job** — matplotlib pulls contourpy/fonttools/kiwisolver and may upgrade numpy/pillow
under a live process.

### Sandbox mode has NO real isolation
`sandbox` mode is a bare `subprocess.run` with a timeout. `max_memory_mb` is dead config.
Generated code runs on the host. `_SANDBOX_SAFE_PACKAGES` = numpy, scipy, torch, sklearn,
matplotlib, pandas, seaborn, tqdm, gymnasium/gym. **`duckdb` is NOT in it and NOT in the venv**,
so generated code must never query DuckDB directly. **Pre-materialise** the joined table to
parquet/CSV in the run's experiment dir and hand the pipeline a path; generated code then needs
only pandas + numpy.

### Fleet
| host | tailnet | role |
|---|---|---|
| m5-prime-serve (March 8TB, serial HFY3PC9VJF) | **`macbook-pro` / 100.95.93.7** | primary, 72B, live DuckDB, OpenFang daemon |
| m5-infer1 (May 4TB, serial PPGH09YFMW) | `m5-infer1.tail3fb853.ts.net` / 100.73.163.0 | second ARCLAW, console :8090, qwen2.5:14b |
| m5-infer-2 | 100.76.152.92 | online, otherwise uncharacterised |
| int-hve-srv | 100.115.235.76 | Coolify NUC, useful as a genuine THIRD host for marker proofs |

> ### DANGER — TAILNET NAME COLLISION (verified 2026-07-31)
> There is an **online tailnet node literally named `m5-prime-serve` at 100.77.102.76 that is
> NOT prime-serve.** The real prime-serve is **`macbook-pro` / 100.95.93.7**, serial HFY3PC9VJF.
> **Anything that resolves "m5-prime-serve" by name reaches the WRONG BOX.** Always address
> prime-serve by IP 100.95.93.7, and confirm identity from `.Self.DNSName` in
> `tailscale status --json` or `ioreg` serial before acting on any host. Never ssh-and-modify a
> host you identified by name alone.

ssh access to m5-infer1: **`ssh a1@100.73.163.0`** (login user `ip-infer1`);
repo at `/Users/ip-infer1/arc-deploy/AutoResearchClaw`.

### CORRECTIONS to this brief (2026-07-31, verified)
- **"figures are dead on BOTH paths" is now STALE for prime-serve.** prime-serve's venv has
  matplotlib (installed during this burn) plus **torch, pandas, sklearn, pyarrow** pre-existing.
  The Docker-image gap remains real. `duckdb` is genuinely absent on BOTH hosts — the
  pre-materialise-to-parquet rule stands unchanged.
- **m5-infer1's venv is MISSING torch, pandas, sklearn, matplotlib, seaborn.** Flipping infer1 to
  `mode: sandbox` without installing those is a guaranteed ImportError.
- `"version":"0.5.0"` from `/api/health` is a **hardcoded literal** (`server/app.py:41,70`), not a
  version signal. Do not use it to verify a deployment.
- "zero parse fallbacks" is **unfalsifiable** — no such emitter reaches serve.log. The defensible
  form is "all N JSON artifacts parse cleanly", which must be checked directly.

Repo `~/code/AutoResearchClaw` @ `cursor/ollama-openfang-setup-dd8b` = `ba6352f`.
Console `./run_console.sh` → `0.0.0.0:8090` (**8080 is OrbStack, do not use**).
`POST /api/pipeline/stop` returns `{"status":"stopped"}` — use it, never kill the server.

### Settled today — DO NOT RE-LITIGATE
Model = qwen2.5:72b-instruct on prime-serve / 14b on infer1. Host choice. Sandbox-mode
isolation caveats. Topic = WS3 H2. These are decided.

## Hard rules for every subagent
- **Never `git checkout`/`git switch` in `/Users/alexeynikitine`** — it is one repo shared by
  every concurrent agent session. Read-only git is fine. To commit, use a disposable worktree
  under your scratchpad based on `origin/main`.
- **Verify EXECUTED, not configured.** "loaded/up/connected" is not proof. Prove from the
  outside with a unique marker where reachability is the claim.
- **Honest timestamps.** Never report a stale heartbeat as liveness. `heartbeat.json.last_stage`
  only updates on stage COMPLETION — it looks frozen during a long stage. Cross-check with
  `ollama ps` (a refreshing `expires` means calls are landing) and a recent-file check.
- **`find -newermt '-N minutes'` IS BROKEN ON THIS HOST — DO NOT USE IT.** `find` here is
  **`bfs`**, not GNU find. `-newermt '-45 minutes'` fails with `bfs: error: Invalid timestamp`,
  prints **nothing**, and **exits 0** — a silently-failing probe that makes a healthy run look
  stalled and can never report liveness. It produced a false STALL warning on a run 2 minutes old.
  Use instead:
  ```sh
  find "$RD" -mmin -45 -type f          # BSD-native, works
  find "$RD" -newermt "$(date -v-45M '+%Y-%m-%d %H:%M:%S')" -type f   # explicit stamp, also works
  ```
  This idiom appears in older notes and in the vault deployment record — it was wrong there too.
  Treat any past conclusion that rested on it as unsupported, not as evidence of a dead run.
- **A weak probe's silence is not absence.** `command -v ollama` returned NONE on a box that was
  already serving on :11434 — it just wasn't on the non-interactive ssh PATH.
- Memory-first: RAG at `~/code/memory-bridge/.venv/bin/python ~/code/memory-bridge/cascade/rag_client.py "<entity>"`
  before asserting any Intrepid-specific fact.
- Report blockers honestly. Stop only for missing auth, a genuine dead end after real effort, or
  a founder DECISION. Do not stop for routine implementation choices.
