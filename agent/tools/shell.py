"""Tool de shell.

⚠️ En esta versión NO hay sandbox real. La versión productiva (fase Launch)
ejecutará dentro de bubblewrap con seccomp (ADR-005). Aquí el riesgo se
expresa al menos vía RiskLevel y filtros de patrones obvios.

Distinguimos dos tools por riesgo: `shell.run_safe` y `shell.run_dangerous`.
El primero rechaza patrones destructivos conocidos; el segundo los permite
pero pide confirmación humana siempre (DANGEROUS).
"""

from __future__ import annotations

import re
import subprocess

from tools.base import RiskLevel, ToolDefinition, ToolResult
from tools.registry import register


# Patrones que un humano DEBERÍA confirmar en cualquier circunstancia.
# Lista pragmática, no exhaustiva.
_DESTRUCTIVE_PATTERNS = [
    re.compile(r"\brm\s+-[rfRF]+"),
    re.compile(r"\bmkfs(\.|\s)"),
    re.compile(r"\bdd\s+if=.*of=/dev/"),
    re.compile(r":\(\)\{.*\};:"),  # fork bomb
    re.compile(r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b"),
    re.compile(r"\bsudo\b"),
    re.compile(r">\s*/dev/sd[a-z]"),
    re.compile(r"\bgit\s+push\s+--force\b|\bgit\s+push\s+-f\b"),
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bchmod\s+(?:-R\s+)?[0-7]*[0-7]?7"),
]


def _looks_destructive(cmd: str) -> str | None:
    """Si `cmd` matchea un patrón destructivo, devuelve la regex matched."""
    for pattern in _DESTRUCTIVE_PATTERNS:
        if pattern.search(cmd):
            return pattern.pattern
    return None


def _run(cmd: str, timeout: float = 30.0, allow_destructive: bool = False) -> ToolResult:
    if not allow_destructive:
        suspicious = _looks_destructive(cmd)
        if suspicious:
            return ToolResult(
                output=(
                    f"comando rechazado: matchea patrón destructivo {suspicious!r}. "
                    "Usa shell.run_dangerous si realmente lo quieres."
                ),
                is_error=True,
            )
    try:
        result = subprocess.run(  # noqa: S602 - cmd llega del modelo + gates aplicados
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return ToolResult(
            output=_format_result(result),
            structured={
                "exit_code": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-2000:],
            },
            is_error=result.returncode != 0,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            output=f"comando excedió timeout ({timeout}s)", is_error=True
        )


def _format_result(r: subprocess.CompletedProcess[str]) -> str:
    parts = [f"exit_code={r.returncode}"]
    if r.stdout:
        parts.append(f"stdout:\n{r.stdout[-2000:]}")
    if r.stderr:
        parts.append(f"stderr:\n{r.stderr[-1000:]}")
    return "\n".join(parts)


def _run_safe(cmd: str, timeout: float = 30.0) -> ToolResult:
    return _run(cmd, timeout=timeout, allow_destructive=False)


def _run_dangerous(cmd: str, timeout: float = 30.0) -> ToolResult:
    return _run(cmd, timeout=timeout, allow_destructive=True)


SHELL_RUN_DEFINITION = ToolDefinition(
    name="shell.run",
    description=(
        "Ejecuta un comando shell. Rechaza patrones obviamente destructivos. "
        "Para rm -rf, mkfs, dd, sudo, force-push, etc., usa shell.run_dangerous."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cmd": {"type": "string"},
            "timeout": {"type": "number"},
        },
        "required": ["cmd"],
    },
    risk=RiskLevel.CONFIRM,
    executor=_run_safe,
    capabilities_required=["shell:safe"],
    category="shell",
)

SHELL_RUN_DANGEROUS_DEFINITION = ToolDefinition(
    name="shell.run_dangerous",
    description=(
        "Ejecuta un comando shell sin filtros de patrones destructivos. "
        "Confirmación humana obligatoria por uso (riesgo: dangerous)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cmd": {"type": "string"},
            "timeout": {"type": "number"},
        },
        "required": ["cmd"],
    },
    risk=RiskLevel.DANGEROUS,
    executor=_run_dangerous,
    capabilities_required=["shell:any"],
    category="shell",
)


def register_all() -> None:
    register(SHELL_RUN_DEFINITION)
    register(SHELL_RUN_DANGEROUS_DEFINITION)


__all__ = [
    "SHELL_RUN_DANGEROUS_DEFINITION",
    "SHELL_RUN_DEFINITION",
    "register_all",
]
