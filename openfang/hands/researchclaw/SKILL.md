---
name: researchclaw-openfang
description: Domain knowledge for running AutoResearchClaw from OpenFang with a local Ollama backend.
metadata:
  category: tooling
  platform: openfang
  version: "1.0.0"
  author: researchclaw
---

# ResearchClaw × OpenFang × Ollama — Skill Reference

Injected knowledge for the ResearchClaw Hand. Prefer this over inventing CLI flags.

## What AutoResearchClaw Is

A 23-stage autonomous research pipeline: literature → hypotheses → experiments → analysis → paper → peer review → LaTeX export.

Key bootstrap files in the repo:

| File | Purpose |
|------|---------|
| `RESEARCHCLAW_AGENTS.md` | Agent orchestrator brief |
| `config.ollama.example.yaml` | Ready-made local Ollama config |
| `config.researchclaw.example.yaml` | Full template |
| `.claude/skills/researchclaw/SKILL.md` | Generic skill for coding agents |
| `docs/openfang-ollama.md` | Human setup guide |

## Ollama Backend

```yaml
llm:
  provider: "openai-compatible"
  base_url: "http://localhost:11434/v1"
  wire_api: "chat_completions"
  api_key_env: "OPENAI_API_KEY"
  api_key: "ollama"
  primary_model: "qwen2.5:32b"
```

Notes:

- Base URL **must** include `/v1`.
- Ollama ignores the API key; set `OPENAI_API_KEY=ollama` for config validation.
- Strong models (≥14B instruction/code, ideally 32B+) are required for usable papers.
- Small chat models often break JSON/code stages.

Useful checks:

```bash
ollama list
curl -s http://localhost:11434/api/tags
curl -s http://localhost:11434/v1/models \
  -H "Authorization: Bearer ollama"
```

## Essential CLI

```bash
# Install (from repo root, with venv active)
pip install -e .

# Validate config
researchclaw validate --config config.arc.yaml

# Full autonomous run
researchclaw run --config config.arc.yaml --topic "TOPIC" --auto-approve

# Resume / partial
researchclaw run --config config.arc.yaml --resume
researchclaw run --config config.arc.yaml --from-stage PAPER_OUTLINE --auto-approve

# HITL
researchclaw run --config config.arc.yaml --topic "TOPIC" --mode co-pilot
```

## Experiment Modes

| Mode | When to use |
|------|-------------|
| `simulated` | First Ollama smoke test; no local code execution |
| `sandbox` | Default local real experiments via `.venv` Python |
| `docker` | Isolated GPU/CPU containers (needs Docker image) |

For Ollama setups, keep:

```yaml
experiment:
  opencode:
    enabled: false
  figure_agent:
    nano_banana_enabled: false
```

## Pipeline Phases (23 stages)

| Phase | Stages | Notes |
|-------|--------|-------|
| A Scoping | 1–2 | Topic + problem tree |
| B Literature | 3–6 | Needs network; gate @5 |
| C Synthesis | 7–8 | Hypotheses / debate |
| D Design | 9–11 | Gate @9; code gen |
| E Execution | 12–13 | Sandbox/docker runs |
| F Decision | 14–15 | PROCEED / REFINE / PIVOT |
| G Writing | 16–19 | Draft + peer review |
| H Finalize | 20–23 | Gate @20; LaTeX + citation verify |

## Deliverables

Look under `artifacts/rc-YYYYMMDD-HHMMSS-*/`:

- `deliverables/` — compile-ready package when present
- `stage-17/paper_draft.md`
- `stage-22/` charts + export
- `references.bib` / `verification_report.json`
- `pipeline_summary.json`

## OpenFang Integration Pattern

OpenFang does **not** need the `openclaw_bridge` flags. Treat ResearchClaw as a local worker:

1. Hand ensures Ollama + venv + config
2. Hand runs `researchclaw run …`
3. Hand reports artifact paths back via channels/dashboard

Optional schedule example: nightly topic from memory, `experiment_mode=simulated` for cheap monitoring, escalate to sandbox when the user confirms.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Missing `llm.base_url` / `api_key_env` | Use `config.ollama.example.yaml` |
| Connection refused `:11434` | `ollama serve` + pull model |
| Garbage JSON / failed stages | Larger model; lower temperature; simulated dry run |
| Sandbox import errors | `pip install` deps into `.venv`; fix `python_path` |
| Gate stuck | `--auto-approve` or `researchclaw approve <run-dir>` |
| OpenCode timeouts | Keep `opencode.enabled: false` on Ollama |

## Ethics Reminder

Outputs are drafts. Human review is required before any academic submission. Do not fabricate papers, citations, or experimental metrics.
