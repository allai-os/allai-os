#!/usr/bin/env bash
# Setup del prototipo A.5 en una VM Fedora 41+.
# Idempotente: se puede correr varias veces.

set -euo pipefail

echo "==> Instalando dependencias del sistema..."
sudo dnf install -y \
    python3-pip \
    python3-virtualenv \
    xdotool \
    gnome-screenshot \
    git

if ! command -v ollama >/dev/null 2>&1; then
    echo "==> Instalando Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

echo "==> Creando virtualenv..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -d .venv ]]; then
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cat <<MSG

✅ Setup completo.

Activa el venv con:
    cd $SCRIPT_DIR
    source .venv/bin/activate

Para correr con Claude:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python run.py --provider claude --task "abre Firefox"

Para correr con Ollama:
    ollama pull qwen2.5vl:7b   # primera vez, ~6GB
    ollama serve &              # si no está corriendo
    python run.py --provider ollama --task "abre Firefox"

Para benchmark de las 10 tareas:
    python run.py --provider claude --benchmark
    python run.py --provider ollama --benchmark

⚠️  Recomendación: corre esto en una VM con sesión Xorg.
    En GDM elige "GNOME on Xorg" antes de hacer login.
    Wayland funcionará en la versión final del proyecto pero no aquí.
MSG
