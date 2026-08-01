# Handoff: AutoResearchClaw × Ollama × OpenFang (local follow-on)

**Date:** 2026-08-01  
**Branch:** `cursor/ollama-openfang-setup-dd8b`  
**PR:** https://github.com/micro-eng/AutoResearchClaw/pull/1  
**Repo:** https://github.com/micro-eng/AutoResearchClaw  
**Prior cloud run:** https://cursor.com/agents/bc-019facf6-af44-73a5-a177-7fe71954dd8b  

Cloud agent could **not** SSH the fleet (`usePrivateWorker: false`, no keys). Continue **on a machine with fleet SSH + Ollama capacity**.

---

## Goal for this local session

1. SSH to a fleet host that can run a **large Ollama model** (~120B or largest that fits).
2. Deploy AutoResearchClaw from the PR branch.
3. Run with **`experiment.mode: sandbox`** (not `simulated`).
4. Produce a real `paper_draft.md` (stage 17+) and report blockers if any.

Do **not** use paid cloud LLM APIs.

---

## What’s already done (don’t redo)

| Item | Location |
|------|----------|
| Ollama example config | `config.ollama.example.yaml` |
| OpenFang Hand | `openfang/hands/researchclaw/` + `scripts/install_openfang_hand.sh` |
| Setup docs | `docs/openfang-ollama.md` |
| Web console UI | `frontend/` (`researchclaw serve` → `:8080`) |
| FastAPI/uvicorn in extras | `pip install -e ".[web]"` |
| README / integration guide wired | Ollama + OpenFang sections |

---

## Why the paper was not written (cloud 3B run)

Run ID: `rc-20260729-083948-3677fb` (artifacts on cloud VM only; may not exist locally).

Root cause chain:

1. Used `qwen2.5:3b` + **`experiment.mode: simulated`**.
2. Stages 1–14 completed; literature APIs worked.
3. Post-14 **repair** loop: 3× `Sandbox execution failed`.
4. Stage 15 decided **REFINE** → rolled back to stage 13.
5. Stage 13 in simulated mode is a **no-op** → refine loop.
6. Even if stage 17 were reached, code **hard-blocks `PAPER_DRAFT`** when all experiment results are `status: "simulated"` (non-survey topics). See `researchclaw/pipeline/stage_impls/_paper_writing.py` (R10 hard block).

**Claude “science app” can write drafts** because it isn’t bound by ARC’s anti-fabrication + 23-stage gates. Bigger Ollama helps JSON/codegen; it does **not** bypass the simulated hard-block — need **sandbox** (or survey-topic exception).

---

## Local bootstrap

```bash
git clone https://github.com/micro-eng/AutoResearchClaw.git
cd AutoResearchClaw
git fetch origin cursor/ollama-openfang-setup-dd8b
git checkout cursor/ollama-openfang-setup-dd8b

# Ollama — prefer largest that fits
ollama serve   # if needed
ollama pull gpt-oss:120b \
  || ollama pull qwen3:235b \
  || ollama pull qwen2.5:72b \
  || ollama pull qwen2.5:32b

python3 -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -e ".[web]"

cp config.ollama.example.yaml config.arc.yaml
# EDIT config.arc.yaml:
#   llm.primary_model: <pulled tag>
#   llm.base_url: http://127.0.0.1:11434/v1
#   experiment.mode: sandbox          # REQUIRED for paper
#   experiment.repair.enabled: false  # first pass; avoid repair death-spiral
#   experiment.opencode.enabled: false
#   figure_agent.nano_banana_enabled: false

export OPENAI_API_KEY=ollama
researchclaw validate --config config.arc.yaml
```

### Run pipeline (preferred for paper)

```bash
researchclaw run --config config.arc.yaml \
  --topic "Sparse attention for efficient transformers" \
  --auto-approve
```

### Or web console

```bash
researchclaw serve --config config.arc.yaml --host 0.0.0.0 --port 8080
# open http://<host>:8080
```

### Optional OpenFang

```bash
./scripts/install_openfang_hand.sh
openfang hand activate researchclaw
openfang hand config researchclaw \
  --set repo_path="$(pwd)" \
  --set primary_model="<pulled tag>" \
  --set experiment_mode="sandbox"
```

---

## Success criteria

- [ ] Ollama model loaded (`ollama ps` / `curl localhost:11434/api/tags`)
- [ ] `researchclaw validate` passes
- [ ] Pipeline reaches **stage 17** with non-empty `artifacts/rc-*/stage-17/paper_draft.md`
- [ ] Ideally `deliverables/` + LaTeX export (stages 22–23)
- [ ] Report: host, model tag, VRAM/RAM, stages completed, artifact paths, any blocker

---

## If it stalls again — check these first

| Symptom | Fix |
|---------|-----|
| REFINE loop / stuck at 13–15 | Ensure `experiment.mode: sandbox`; set `repair.enabled: false` |
| `Paper Draft Blocked` / simulated | Switch off simulated; re-run from experiments or full run |
| Sandbox import/codegen fails | Larger model; fix venv deps; shorten topic |
| Gate pauses | `--auto-approve` or `project.mode: full-auto` |
| Lit stage empty | Need outbound net to OpenAlex / S2 / arXiv |

Resume helpers:

```bash
researchclaw run --config config.arc.yaml --resume --auto-approve
researchclaw run --config config.arc.yaml --from-stage PAPER_OUTLINE --auto-approve
```

(`--from-stage PAPER_OUTLINE` only works if prior artifacts exist and you’re not blocked by simulated data.)

---

## Paste into new local agent (first message)

```
Continue AutoResearchClaw local deployment from handoff file HANDOFF_LOCAL.md
(or docs in repo). Branch: cursor/ollama-openfang-setup-dd8b
PR: https://github.com/micro-eng/AutoResearchClaw/pull/1

You are on a machine with fleet SSH. Pick the best host for a large Ollama
model (~120B or largest that fits). Deploy the branch, use sandbox mode
(NOT simulated), disable experiment.repair for the first pass, run
researchclaw with --auto-approve, and get to stage-17 paper_draft.md.

Do not use paid cloud LLM APIs. Read HANDOFF_LOCAL.md for full context
on why the previous cloud 3B/simulated run never wrote a paper.
```
