"""Configuración pytest común."""

from __future__ import annotations

import sys
from pathlib import Path

# Permite importar `core`, `providers`, `tools` directamente desde los tests.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
