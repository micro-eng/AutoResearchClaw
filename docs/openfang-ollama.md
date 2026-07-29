# Local Ollama + OpenFang Setup

Run [AutoResearchClaw](https://github.com/aiming-lab/AutoResearchClaw) entirely on your machine: **Ollama** as the LLM backend, **OpenFang** agents/Hands as the orchestrator.

## Architecture

```
You / Telegram / Discord / …
        │
        ▼
   OpenFang Hand (researchclaw)
        │  shell + files
        ▼
   researchclaw CLI  ──►  Ollama (:11434/v1)
        │
        ▼
   artifacts/rc-*/deliverables/
```

- **Ollama** serves an OpenAI-compatible API — no cloud LLM key required.
- **OpenFang** reads `openfang/hands/researchclaw/` (`HAND.toml` + `SKILL.md`) and drives install/config/run.
- Literature stages still need outbound network (OpenAlex, Semantic Scholar, arXiv).

## 1. Prerequisites

| Tool | Why |
|------|-----|
| Python 3.11+ | Pipeline runtime |
| [Ollama](https://ollama.com) | Local LLM server |
| Strong local model | e.g. `qwen2.5:32b` (14B minimum for smoke tests) |
| [OpenFang](https://openfang.sh) (optional) | Agent OS to orchestrate runs |
| Docker (optional) | Only if `experiment.mode: docker` |

```bash
# Ollama
curl -fsSL https://ollama.com/install.sh | sh   # or brew install ollama
ollama serve
ollama pull qwen2.5:32b

# OpenFang (optional)
curl -fsSL https://openfang.sh/install | sh
openfang init && openfang start
```

## 2. Install AutoResearchClaw

```bash
git clone https://github.com/aiming-lab/AutoResearchClaw.git
cd AutoResearchClaw
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
```

## 3. Configure for Ollama

```bash
cp config.ollama.example.yaml config.arc.yaml
# Edit primary_model if you pulled a different tag
export OPENAI_API_KEY=ollama
researchclaw validate --config config.arc.yaml
```

Critical `llm` fields:

```yaml
llm:
  provider: "openai-compatible"
  base_url: "http://localhost:11434/v1"   # /v1 required
  wire_api: "chat_completions"
  api_key_env: "OPENAI_API_KEY"
  api_key: "ollama"
  primary_model: "qwen2.5:32b"
```

The example disables OpenCode beast mode and Gemini Nano Banana so the stack stays local.

### Smoke test vs real experiments

| Goal | Setting |
|------|---------|
| Validate Ollama connectivity / JSON stability | `experiment.mode: simulated` |
| Real local code execution | `experiment.mode: sandbox` (default in the example) |
| Isolated / GPU container runs | `experiment.mode: docker` |

## 4. Run standalone (no OpenFang)

```bash
export OPENAI_API_KEY=ollama
researchclaw run --config config.arc.yaml \
  --topic "Graph neural networks for molecular property prediction" \
  --auto-approve
```

Outputs land in `artifacts/rc-YYYYMMDD-HHMMSS-*/` (see `deliverables/` when export succeeds).

Resume after interruption:

```bash
researchclaw run --config config.arc.yaml --resume
```

## 5. Run with OpenFang

### Install the Hand

From the AutoResearchClaw repo:

```bash
./scripts/install_openfang_hand.sh
# equivalent:
# mkdir -p ~/.openfang/hands
# cp -R openfang/hands/researchclaw ~/.openfang/hands/
openfang hand activate researchclaw
```

Configure settings (dashboard or CLI):

```bash
openfang hand config researchclaw \
  --set repo_path="$(pwd)" \
  --set ollama_base_url="http://localhost:11434/v1" \
  --set primary_model="qwen2.5:32b" \
  --set experiment_mode="sandbox" \
  --set auto_approve="true"
```

Point OpenFang’s own LLM provider at Ollama as well if you want the Hand’s reasoning local (see OpenFang provider docs). The Hand still configures ResearchClaw’s `config.arc.yaml` to call Ollama for the 23 pipeline stages.

### Trigger a run

In the OpenFang dashboard / chat:

```
Research sparse attention for long-context transformers
```

or:

```
Use ResearchClaw with Ollama to investigate continual learning for vision transformers
```

The Hand will:

1. Verify Ollama + model  
2. Ensure the venv / `pip install -e .`  
3. Materialize `config.arc.yaml` from `config.ollama.example.yaml`  
4. Run `researchclaw run …`  
5. Report artifact paths and update dashboard metrics  

### Without activating the Hand

Any OpenFang agent with shell/file tools can follow `RESEARCHCLAW_AGENTS.md` and this guide the same way OpenClaw does.

## 6. Quality tips for local models

- Prefer **32B+** instruction models with good code performance.
- If stages fail on JSON parsing, drop to `simulated`, fix the model, then re-enable `sandbox`.
- Reduce `research.daily_paper_count` and `experiment.max_iterations` on small GPUs/CPUs.
- Keep `opencode.enabled: false` unless OpenCode is installed and pointed at a capable model.
- Literature APIs are remote even when the LLM is local — offline mode is not supported for Stage 4.

## 7. Troubleshooting

| Problem | Fix |
|---------|-----|
| `Connection refused` on 11434 | Start `ollama serve`; check firewall |
| Validate wants API key | `export OPENAI_API_KEY=ollama` |
| Model not found | `ollama pull <tag>` must match `primary_model` |
| Windows Python path | Set `experiment.sandbox.python_path: ".venv/Scripts/python.exe"` |
| Remote Ollama | Set `base_url: "http://<host>:11434/v1"` (OpenFang host must reach it) |
| OpenFang Hand missing | Re-run `./scripts/install_openfang_hand.sh` and `openfang hand activate researchclaw` |

## Related

- [Integration guide](integration-guide.md) — OpenClaw, ACP, Python API  
- [Tester guide](TESTER_GUIDE.md) — feedback runs  
- [HITL co-pilot](HITL_GUIDE.md) — human gates instead of `--auto-approve`  
- OpenFang Hands: <https://openfang.sh> / <https://github.com/RightNow-AI/openfang>
