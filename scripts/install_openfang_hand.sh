#!/usr/bin/env bash
# Install the AutoResearchClaw OpenFang Hand into ~/.openfang/hands/researchclaw
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${ROOT}/openfang/hands/researchclaw"
DEST_DIR="${OPENFANG_HANDS_DIR:-${HOME}/.openfang/hands}"
DEST="${DEST_DIR}/researchclaw"

if [[ ! -f "${SRC}/HAND.toml" ]]; then
  echo "error: missing ${SRC}/HAND.toml" >&2
  exit 1
fi

mkdir -p "${DEST_DIR}"
rm -rf "${DEST}"
mkdir -p "${DEST}"
cp -R "${SRC}/." "${DEST}/"

echo "Installed OpenFang Hand → ${DEST}"
echo
echo "Next:"
echo "  openfang hand activate researchclaw"
echo "  openfang hand config researchclaw --set repo_path=\"${ROOT}\""
echo "  openfang hand config researchclaw --set primary_model=\"qwen2.5:32b\""
echo
echo "Docs: ${ROOT}/docs/openfang-ollama.md"
