"""Parser de comandos de memoria en lenguaje natural.

Detecta en el texto del usuario intenciones como:
  "recuerda que mi nombre es Juan"  →  RememberCommand
  "olvida mi dirección"             →  ForgetCommand
  "qué sabes de mí"                 →  QueryCommand
  "exportar memoria"                →  ExportCommand  (peligroso, requiere confirm)

Diseño:
- Sin LLM: regex deterministicos, bilingüe (ES/EN).
- Devuelve None si no hay comando de memoria en el texto.
- El caller decide si ejecutar; este módulo sólo parsea.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Union


class CommandKind(str, Enum):
    REMEMBER = "remember"
    FORGET = "forget"
    QUERY = "query"
    EXPORT = "export"
    CLEAR = "clear"


@dataclass(frozen=True, slots=True)
class RememberCommand:
    kind: CommandKind = CommandKind.REMEMBER
    content: str = ""


@dataclass(frozen=True, slots=True)
class ForgetCommand:
    kind: CommandKind = CommandKind.FORGET
    topic: str = ""


@dataclass(frozen=True, slots=True)
class QueryCommand:
    kind: CommandKind = CommandKind.QUERY
    topic: str = ""


@dataclass(frozen=True, slots=True)
class ExportCommand:
    """Peligroso: requiere confirmación explícita del usuario."""
    kind: CommandKind = CommandKind.EXPORT


@dataclass(frozen=True, slots=True)
class ClearCommand:
    """Peligroso: borra toda la sesión en RAM."""
    kind: CommandKind = CommandKind.CLEAR


MemoryCommand = Union[RememberCommand, ForgetCommand, QueryCommand, ExportCommand, ClearCommand]


# ─── Patrones ────────────────────────────────────────────────────────────────

# REMEMBER: "recuerda [que] X", "remember [that] X", "guarda [que] X",
#           "anota [que] X", "nota: X", "keep in mind X"
_REMEMBER_RE = re.compile(
    r"(?i)^(?:"
    r"recuerda(?:r)?(?: que)?\s+(?P<es>.+)"
    r"|guarda(?:r)?(?: en memoria)?(?: que)?\s+(?P<es2>.+)"
    r"|anota(?:r)?(?: que)?\s+(?P<es3>.+)"
    r"|nota:\s*(?P<es4>.+)"
    r"|remember(?: that)?\s+(?P<en>.+)"
    r"|keep in mind(?: that)?\s+(?P<en2>.+)"
    r"|note(?: down)?:\s*(?P<en3>.+)"
    r")$",
    re.DOTALL,
)

# FORGET: "olvida [mi/tu/el] X", "forget [my] X", "borra X de tu memoria"
_FORGET_RE = re.compile(
    r"(?i)^(?:"
    r"olvida(?:r)?(?: (?:mi|tu|el|la|los|las|esto|eso))?\s+(?P<es>.+)"
    r"|borra(?:r)?(?: (?:mi|tu))?(?: de (?:tu |la )?memoria)?\s+(?P<es2>.+)"
    r"|forget(?: (?:my|the|about))?\s+(?P<en>.+)"
    r"|delete(?: from memory)?\s+(?P<en2>.+)"
    r")$",
    re.DOTALL,
)

# QUERY: "qué sabes de mí", "what do you know about me", "muéstrame la memoria"
_QUERY_RE = re.compile(
    r"(?i)^(?:"
    r"(?:qué|que)(?: es lo que)? sabes(?: de\s+(?P<es_topic>\w+))?"
    r"|(?:qué|que) recuerdas(?: de\s+(?P<es_topic2>\w+))?"
    r"|muéstrame(?: la)? memoria"
    r"|lista(?:r)? (?:la )?memoria"
    r"|what do you know(?: about\s+(?P<en_topic>\w+))?"
    r"|show(?: me)?(?: your)? memory"
    r"|list(?: my)? memories?"
    r").*$",
    re.DOTALL,
)

# EXPORT: "exporta(?:r)? (la )?memoria", "export memory"
_EXPORT_RE = re.compile(
    r"(?i)^(?:exporta(?:r)?(?: la)? memoria|export(?: my)? memor(?:y|ies)).*$"
)

# CLEAR: "borra(r)? (toda )?(la )?memoria", "clear (all )?(my )?memory"
_CLEAR_RE = re.compile(
    r"(?i)^(?:"
    r"borra(?:r)?(?: toda)?(?: la)? memoria"
    r"|limpia(?:r)?(?: la)? memoria"
    r"|clear(?: all)?(?: my)? memory"
    r"|wipe(?: all)?(?: my)? memories?"
    r").*$"
)


# ─── Parser público ──────────────────────────────────────────────────────────

def parse(text: str) -> MemoryCommand | None:
    """Parsea `text` y devuelve el comando de memoria detectado o None."""
    text = text.strip()
    if not text:
        return None

    m = _REMEMBER_RE.match(text)
    if m:
        content = next(
            (v for v in m.groupdict().values() if v is not None), ""
        ).strip()
        return RememberCommand(content=content) if content else None

    if _EXPORT_RE.match(text):
        return ExportCommand()

    if _CLEAR_RE.match(text):
        return ClearCommand()

    m = _FORGET_RE.match(text)
    if m:
        topic = next(
            (v for v in m.groupdict().values() if v is not None), ""
        ).strip()
        return ForgetCommand(topic=topic) if topic else None

    m = _QUERY_RE.match(text)
    if m:
        gd = m.groupdict()
        topic = next((v for v in gd.values() if v is not None), "") or ""
        return QueryCommand(topic=topic.strip())

    return None


def is_memory_command(text: str) -> bool:
    """Atajo: True si el texto contiene un comando de memoria."""
    return parse(text) is not None
