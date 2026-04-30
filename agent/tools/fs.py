"""Tools de filesystem.

Lectura, escritura, listado y glob de archivos. La política de paths
(qué carpetas se pueden tocar) la enforza el sistema de capabilities con
strings tipo `read-fs:~/Documents`, `write-fs:/tmp`. Esta capa sólo expone
las operaciones — el gate vive en el executor.
"""

from __future__ import annotations

import os
from pathlib import Path

from tools.base import RiskLevel, ToolDefinition, ToolResult
from tools.registry import register


_MAX_READ_BYTES = 1_000_000  # 1 MB


def _resolve(path: str) -> Path:
    return Path(os.path.expanduser(path)).resolve()


def _fs_read(path: str, max_bytes: int = _MAX_READ_BYTES) -> ToolResult:
    p = _resolve(path)
    if not p.exists():
        return ToolResult(output=f"no existe: {p}", is_error=True)
    if not p.is_file():
        return ToolResult(output=f"no es archivo: {p}", is_error=True)
    try:
        data = p.read_bytes()
    except OSError as exc:
        return ToolResult(output=f"error leyendo {p}: {exc}", is_error=True)

    truncated = len(data) > max_bytes
    chunk = data[:max_bytes]
    try:
        text = chunk.decode("utf-8")
    except UnicodeDecodeError:
        return ToolResult(
            output=f"archivo binario, {len(data)} bytes",
            structured={"path": str(p), "size_bytes": len(data), "binary": True},
        )

    output = text + (f"\n\n[truncado: leídos {max_bytes} de {len(data)} bytes]" if truncated else "")
    return ToolResult(
        output=output,
        structured={"path": str(p), "size_bytes": len(data), "truncated": truncated},
    )


def _fs_write(path: str, content: str, append: bool = False) -> ToolResult:
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    try:
        with p.open(mode, encoding="utf-8") as f:
            f.write(content)
    except OSError as exc:
        return ToolResult(output=f"error escribiendo {p}: {exc}", is_error=True)
    return ToolResult(
        output=f"{'appended' if append else 'wrote'} {len(content)} chars en {p}",
        structured={"path": str(p), "bytes_written": len(content.encode("utf-8"))},
    )


def _fs_list(path: str) -> ToolResult:
    p = _resolve(path)
    if not p.exists():
        return ToolResult(output=f"no existe: {p}", is_error=True)
    if not p.is_dir():
        return ToolResult(output=f"no es directorio: {p}", is_error=True)
    try:
        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except OSError as exc:
        return ToolResult(output=f"error listando {p}: {exc}", is_error=True)

    items = [
        {
            "name": e.name,
            "is_dir": e.is_dir(),
            "size": e.stat().st_size if e.is_file() else None,
        }
        for e in entries[:500]
    ]
    rendered = "\n".join(
        f"{'d' if it['is_dir'] else 'f'} {it['name']}" for it in items
    )
    return ToolResult(
        output=rendered or "(vacío)",
        structured={"path": str(p), "count": len(items), "entries": items},
    )


def _fs_glob(pattern: str, root: str = ".") -> ToolResult:
    base = _resolve(root)
    if not base.is_dir():
        return ToolResult(output=f"no es directorio: {base}", is_error=True)
    matches = sorted(str(p) for p in base.glob(pattern))[:500]
    return ToolResult(
        output="\n".join(matches) or "(sin matches)",
        structured={"root": str(base), "pattern": pattern, "count": len(matches)},
    )


def _fs_delete(path: str) -> ToolResult:
    p = _resolve(path)
    if not p.exists():
        return ToolResult(output=f"no existe: {p}", is_error=True)
    if p.is_dir():
        return ToolResult(
            output=f"{p} es directorio. fs.delete sólo borra archivos. "
            "Usa shell.run_dangerous con rm -r si realmente lo quieres.",
            is_error=True,
        )
    try:
        p.unlink()
    except OSError as exc:
        return ToolResult(output=f"error borrando {p}: {exc}", is_error=True)
    return ToolResult(output=f"borrado: {p}")


FS_READ_DEFINITION = ToolDefinition(
    name="fs.read",
    description="Lee un archivo de texto. Trunca a 1MB. Devuelve binario flag si no decodifica.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "max_bytes": {"type": "integer"},
        },
        "required": ["path"],
    },
    risk=RiskLevel.SAFE,
    executor=_fs_read,
    capabilities_required=["read-fs:*"],  # el path concreto se chequea aparte
    category="fs",
)

FS_WRITE_DEFINITION = ToolDefinition(
    name="fs.write",
    description="Escribe contenido a un archivo. Crea carpetas padre si faltan. Soporta append.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "append": {"type": "boolean"},
        },
        "required": ["path", "content"],
    },
    risk=RiskLevel.CONFIRM,
    executor=_fs_write,
    capabilities_required=["write-fs:*"],
    category="fs",
)

FS_LIST_DEFINITION = ToolDefinition(
    name="fs.list",
    description="Lista entradas de un directorio (máx 500).",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    risk=RiskLevel.SAFE,
    executor=_fs_list,
    capabilities_required=["read-fs:*"],
    category="fs",
)

FS_GLOB_DEFINITION = ToolDefinition(
    name="fs.glob",
    description="Busca archivos con glob (ej. '**/*.py').",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "root": {"type": "string"},
        },
        "required": ["pattern"],
    },
    risk=RiskLevel.SAFE,
    executor=_fs_glob,
    capabilities_required=["read-fs:*"],
    category="fs",
)

FS_DELETE_DEFINITION = ToolDefinition(
    name="fs.delete",
    description="Borra un archivo individual (no directorios). Confirma humano.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    risk=RiskLevel.DANGEROUS,
    executor=_fs_delete,
    capabilities_required=["write-fs:*"],
    category="fs",
)


def register_all() -> None:
    register(FS_READ_DEFINITION)
    register(FS_WRITE_DEFINITION)
    register(FS_LIST_DEFINITION)
    register(FS_GLOB_DEFINITION)
    register(FS_DELETE_DEFINITION)


__all__ = [
    "FS_DELETE_DEFINITION",
    "FS_GLOB_DEFINITION",
    "FS_LIST_DEFINITION",
    "FS_READ_DEFINITION",
    "FS_WRITE_DEFINITION",
    "register_all",
]
