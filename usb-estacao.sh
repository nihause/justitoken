#!/usr/bin/env bash
# Abre a ESTACAO (Linux). Usa o ambiente criado pelo instalar.sh, se existir.
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$RAIZ/.venv/bin/python"; [ -x "$PY" ] || PY=python3
cd "$RAIZ/Fontes" && exec "$PY" usb_estacao.py "$@"
