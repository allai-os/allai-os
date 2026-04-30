# ADR-001: Lenguaje del agente core

- **Estado**: Aceptado
- **Fecha**: 2026-04-28
- **Decididores**: Juan Manuel Castellanos (BDFL)

## Contexto

El "agente core" es el componente que recibe la intención del usuario, decide qué hacer, llama a un proveedor de IA (Claude API u Ollama), parsea la respuesta, ejecuta herramientas (mouse, teclado, shell, fs, navegador) y mantiene el bucle de conversación. Es el cerebro de allAI OS.

Las fuerzas en juego:

- Necesitamos integración fluida con SDKs de IA (Anthropic, Ollama, futuros proveedores) que tienen primera-clase en Python.
- Bibliotecas maduras de automatización de escritorio (`pyautogui`, `pynput`, `python-uinput`).
- Productividad alta para iteración rápida en el roadmap.
- Por contrapartida: componentes con requisitos de seguridad o rendimiento (daemon de sistema, audit log firmado, kill-switch en kernel-space) necesitan un lenguaje compilado, type-safe y sin GC pausas.

## Decisión

Usaremos **Python 3.12+** para el agente core y **Rust (edición 2024)** para los componentes de sistema críticos en seguridad/rendimiento.

División concreta:

| Componente | Lenguaje |
|------------|----------|
| Agent core (router, providers, tools) | Python 3.12+ |
| `allaid` (daemon systemd-user) | Rust |
| `allai-ctl` (CLI) | Rust |
| Audit log signer | Rust |
| Overlay UI | Python (PyGObject/GTK4) inicialmente; reescribir a Rust si la latencia lo exige |
| GNOME Shell extension | GJS (JavaScript, requerido por GNOME) |

## Alternativas consideradas

- **Todo en Rust**: máxima coherencia y rendimiento, pero el ecosistema de IA en Rust todavía es inmaduro. Re-implementar bindings de Anthropic/Ollama añade meses de trabajo sin valor diferencial.
- **Todo en Python**: rápido de iterar, pero el daemon de sistema con responsabilidades de seguridad no debe correr sobre un runtime con GC pausas, GIL y dependencias dinámicas.
- **Go**: punto medio razonable, pero menos rico que Rust en garantías de seguridad y peor en interop con bibliotecas de sistema (libei, polkit).
- **TypeScript con Bun/Deno**: descartado por ecosistema de IA menos profundo que Python.

## Consecuencias

### Positivas

- Integración inmediata con SDKs oficiales de Anthropic y Ollama.
- Iteración rápida en la lógica de agente, donde más experimentación habrá.
- Componentes de sistema en Rust dan garantías reales de seguridad de memoria y rendimiento predecible.
- Comunidad Python e IA grande → más contribuidores potenciales.

### Negativas

- Frontera Python ↔ Rust requiere IPC bien diseñada (D-Bus, ver ADR-004).
- Distribuir Python en una imagen atómica añade peso (~80MB de runtime + libs); aceptable.
- GIL puede ser cuello de botella si concurrencia se vuelve crítica → entonces se evalúa migrar parte a Rust.

### Neutras

- Dos lenguajes en el repo significa dos toolchains, dos linters, dos test runners.

## Plan de implementación

1. Estructura `agent/` en Python con `pyproject.toml`, `ruff`, `black`, `mypy --strict`.
2. Estructura `system/` con workspace de Cargo (`allaid`, `allai-ctl`).
3. CI valida ambos toolchains en cada PR.
4. Empaquetar Python como wheel firmada para el RPM final.

## Revisión

Reevaluar si:

- El ecosistema Rust de IA madura al punto de igualar a Python (anthropic-rs, ollama-rs estables, herramientas de tool-use idiomáticas).
- Aparece un cuello de botella de rendimiento del agente core medible y sostenido.

Plazo de revisión por defecto: tras 1.0 estable.

## Referencias

- [ROADMAP.md](../../ROADMAP.md) fases L y A.
- [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python)
- [ollama-python](https://github.com/ollama/ollama-python)
