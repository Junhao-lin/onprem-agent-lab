#!/bin/sh
# Pull the models listed in OLLAMA_MODELS (space-separated) into the
# ollama service. Idempotent: models already present are skipped.
# Runs inside the ollama-init container (ollama/ollama image).
set -eu

: "${OLLAMA_HOST:?OLLAMA_HOST must be set (e.g. http://ollama:11434)}"
: "${OLLAMA_MODELS:?OLLAMA_MODELS must be set}"

for model in $OLLAMA_MODELS; do
  if ollama show "$model" >/dev/null 2>&1; then
    echo "[ollama-init] $model already present, skipping"
  else
    echo "[ollama-init] pulling $model ..."
    ollama pull "$model"
  fi
done

echo "[ollama-init] installed models:"
ollama list
echo "[ollama-init] done"
