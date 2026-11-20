#!/usr/bin/env bash
# Verifica e aplica a atualizacao do programa a partir do GitHub.
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$RAIZ/.venv/bin/python"; [ -x "$PY" ] || PY=python3
cd "$RAIZ/Fontes" || exit 1
"$PY" atualizador.py --verificar
if [ $? -eq 10 ]; then
    read -r -p "Ha atualizacao. Aplicar agora? (s/N) " r
    [ "$r" = "s" ] || [ "$r" = "S" ] && "$PY" atualizador.py --aplicar
fi
