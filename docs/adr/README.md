# Architecture Decision Records (ADR)

Cada decisión arquitectónica significativa del proyecto allAI OS se documenta aquí siguiendo la plantilla [`0000-template.md`](0000-template.md).

## Índice

| ID | Título | Estado |
|----|--------|--------|
| [ADR-001](0001-lenguaje-agente-core.md) | Lenguaje del agente core | Aceptado |
| [ADR-002](0002-base-distro.md) | Base de distro y modelo de imagen | Aceptado |
| [ADR-003](0003-servidor-grafico.md) | Servidor gráfico y automatización | Aceptado |
| [ADR-004](0004-ipc.md) | IPC entre componentes | Aceptado |
| [ADR-005](0005-sandboxing.md) | Sandboxing | Aceptado |
| [ADR-006](0006-modelo-permisos.md) | Modelo de permisos | Aceptado |
| [ADR-007](0007-tooling-empaquetado.md) | Tooling de empaquetado | Aceptado |
| [ADR-008](0008-telemetria.md) | Telemetría | Aceptado |

## Estados posibles

- **Propuesto** — en discusión.
- **Aceptado** — vigente.
- **Reemplazado** — sustituido por otro ADR (referenciar cuál).
- **Obsoleto** — ya no aplica.

## Cómo proponer un ADR

1. Copia `0000-template.md` a `NNNN-titulo-corto.md` con el siguiente número libre.
2. Completa todas las secciones.
3. Abre PR con estado `Propuesto`.
4. Tras revisión y aprobación, cambia estado a `Aceptado` y mergea.
