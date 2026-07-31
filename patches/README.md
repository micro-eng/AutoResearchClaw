# AutoResearchClaw patches — 2026-07-31 ARCLAW burn

Four fixes for real defects found while driving WS3 hypothesis H2 to a paper on real NEM data.
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

## Apply order

`004` supersedes `003` (cumulative). On a clean tree the minimal complete set is:

```sh
git apply patches/experiment_diagnosis_dataset_guidance_2026-07-31.patch
git apply patches/004-regen-prompt-keeps-dataset-guidance.patch
git apply patches/005-code-agent-prioritise-plan-before-truncate.patch
```

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
