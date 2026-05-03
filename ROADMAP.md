# allAI OS — Roadmap Maestro

> **Visión**: Una distribución Linux basada en Fedora donde la IA es ciudadano de primera clase del sistema operativo. El usuario habla (texto/voz) y la IA hace: mueve el mouse, abre apps, ejecuta comandos, edita archivos, navega la web — todo lo que haría una persona, con permisos auditables y kill-switch siempre disponible.
>
> **Modelo**: Híbrido. Claude API (Anthropic) como cerebro principal de pago. Ollama (modelos locales: Qwen2.5-VL, Llama3.2-Vision, etc.) como alternativa gratuita y offline. Arquitectura agnóstica para sumar más proveedores.
>
> **Tipo de proyecto**: Opción B — distribuible. ISO descargable, actualizaciones, soporte, comunidad.

---

## Cómo usar este documento

Este archivo es **la fuente de verdad del proyecto**. Está diseñado para que cualquier sesión futura (incluyendo cuando Juan Manuel se quede sin cuota y vuelva mañana o la próxima semana) pueda:

1. Leer el "Estado actual" abajo.
2. Ir a la fase/paso marcado en curso.
3. Continuar sin re-explicar contexto.

**Convención de estado por paso**:
- `[ ]` pendiente
- `[~]` en curso (anota fecha y notas)
- `[x]` completado (anota fecha de cierre)
- `[!]` bloqueado (anota razón)

**Al terminar cualquier paso, actualiza este archivo antes de cerrar la sesión.**

---

## Estado actual

- **Fecha de inicio**: 2026-04-28
- **Fase activa**: L — Link
- **Paso activo**: L.5 — Voz (entrada y salida) `[~]` (en curso).
- **Próxima acción concreta**: implementar `agent/voice/wakeword.py` (openWakeWord para "Hey allAI") o `agent/voice/pipewire.py` (captura/reproducción).
- **Última sesión**: 2026-05-02. **L.4 100% cerrado** con `memory/injector.py` (inyección de contexto en `ChatRequest` con delimitadores fuertes `<allai-memory-context>` y opt-in cloud para sensibles, 16 tests) + bug fix en `retrieval.py` (sanitización FTS5 vía `_to_fts_query` para queries con `?`/`:`/`*`). **L.5 arrancado**: `voice/` con interfaces abstractas `STTProvider`/`TTSProvider` + tipos provider-agnostic + 29 tests. **459 tests pasando**.
- **Pendientes externos del usuario**:
  - [x] Dominio `allai-os.org` registrado.
  - [x] Repo GitHub `git@github.com:allai-os/allai-os.git` creado y push exitoso (rebase con commit inicial de GitHub resuelto a favor de nuestro LICENSE).
  - [ ] Configurar MX/email para `security@allai-os.org` y `conduct@allai-os.org`.
  - [ ] Investigar trademark de "allAI OS" cuando aplique.
  - [ ] (Opcional) Configurar git global con `user.name` y `user.email` para no tener que pasarlos en cada commit.
  - [ ] **Ejecutar prototipo A.5 en VM Fedora** y registrar resultados.

---

## Resumen ejecutivo de fases

| Fase | Nombre | Duración estimada | Resultado entregable |
|------|--------|-------------------|----------------------|
| **A** | Architect | 2 semanas | ADRs, repo inicializado, stack decidido, prototipo de ejecución de comandos |
| **L** | Link | 3-4 semanas | Capa de proveedores (Claude + Ollama) con fallback y enrutamiento |
| **L** | Launch | 4-5 semanas | Agente de escritorio funcional (overlay, hotkey, computer use) |
| **A** | Assemble | 4-6 semanas | ISO de Fedora Remix con allAI preinstalado, branding, kickstart |
| **I** | Ignite | 4-6 semanas | Infra de updates (OSTree/COPR), web, comunidad, beta pública, 1.0 |

**Total estimado a 1.0 estable**: ~5-7 meses de trabajo dedicado de un desarrollador, asumiendo ritmo sostenible (no crunch). Realista: 8-10 meses con vida normal.

---

# FASE A — Architect

> Establecer fundamentos: licencia, gobernanza, arquitectura, prototipos de viabilidad. Sin esto, todo lo demás es deuda técnica desde el día uno.

**Duración estimada: 2 semanas (10 días de trabajo)**

## A.1 — Decisiones fundacionales `[x]` (cerrada 2026-04-28)

**Tiempo: 1-2 días**

- [x] Licencia: **Apache 2.0** elegida (LICENSE + NOTICE creados). GPLv3 sólo donde Fedora lo exija a nivel de componente.
- [x] Gobernanza: BDFL (Juan Manuel) inicial, transición a steering committee post-1.0. Documentado en `GOVERNANCE.md`.
- [~] Nombre/dominio/trademark: nombre `allAI OS` adoptado. **Pendiente del usuario**: registrar dominio `allai-os.org`, GitHub org `allai-os`, investigar trademark.
- [x] `CODE_OF_CONDUCT.md` creado (Contributor Covenant 2.1, en español).
- [x] `docs/AI_ETHICS.md` creado: principios fundamentales, 12 reglas absolutas, defensas contra prompt injection, bienestar del usuario.
- [x] Documentos adicionales creados en la sesión: `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `.gitignore`, `.editorconfig`, plantilla ADR, esqueleto `docs/architecture.md`, READMEs de subdirectorios (`agent/`, `desktop/`, `system/`, `distro/`, `installer/`, `website/`).

## A.2 — Stack tecnológico y ADRs `[x]` (cerrada 2026-04-28)

**Tiempo: 2 días**

Los 8 ADRs están aceptados y publicados en [`docs/adr/`](docs/adr/):

- [x] [ADR-001](docs/adr/0001-lenguaje-agente-core.md): Python 3.12+ para agente core, Rust para componentes de sistema.
- [x] [ADR-002](docs/adr/0002-base-distro.md): Fedora Silverblue 41+ con imagen OCI estilo Universal Blue/Bluefin.
- [x] [ADR-003](docs/adr/0003-servidor-grafico.md): Wayland primario, libei + portales para automatización; AT-SPI cuando se pueda.
- [x] [ADR-004](docs/adr/0004-ipc.md): D-Bus en el session bus, interfaz `org.allai.Agent1`.
- [x] [ADR-005](docs/adr/0005-sandboxing.md): bubblewrap + SELinux policy custom + seccomp.
- [x] [ADR-006](docs/adr/0006-modelo-permisos.md): polkit + capability system + gates por acción + audit log firmado + kill-switch.
- [x] [ADR-007](docs/adr/0007-tooling-empaquetado.md): RPMs en COPR, imagen OCI en ghcr.io firmada con cosign, ISO con livemedia-creator.
- [x] [ADR-008](docs/adr/0008-telemetria.md): opt-in estricto, granular, anonimizada, autohospedada, sin trackers comerciales.

## A.3 — Inicialización del repositorio `[x]` (cerrada 2026-04-28)

**Tiempo: 1 día**

- [x] `git init` en `c:\JM\PROGRAMMING\allAI-OS`, primer commit con DCO sign-off.
- [x] Push inicial a `git@github.com:allai-os/allai-os.git` exitoso (tras rebase para integrar el commit inicial automático que GitHub crea con el LICENSE template).
- [x] Estructura de carpetas creada según el plan (con README en cada subcarpeta).
- [ ] Push inicial a GitHub (bloqueado por host key SSH — ver `Notas de sesión`).
- [ ] Configurar branch protection en `main` (tras primer push exitoso).
- [ ] Configurar pre-commit con hooks (ruff, gitleaks, etc.) — pendiente cuando llegue código real.

Plan de carpetas (referencia, ya materializada):
  ```
  allAI-OS/
  ├── README.md
  ├── ROADMAP.md            # este archivo
  ├── LICENSE
  ├── CODE_OF_CONDUCT.md
  ├── CONTRIBUTING.md
  ├── GOVERNANCE.md
  ├── docs/
  │   ├── adr/              # decisiones arquitectónicas
  │   ├── architecture.md   # diagrama del sistema
  │   ├── AI_ETHICS.md
  │   └── user-guide/
  ├── agent/                # Python: cerebro de allAI
  │   ├── core/             # provider abstraction, router
  │   ├── tools/            # mouse, keyboard, shell, fs, browser
  │   ├── providers/        # claude.py, ollama.py
  │   ├── sandbox/          # bubblewrap wrapper
  │   ├── permissions/      # capability system
  │   └── tests/
  ├── desktop/              # integración GNOME
  │   ├── gnome-extension/  # JS/TS extension
  │   ├── overlay/          # GTK4 overlay UI
  │   └── tray/
  ├── system/               # Rust: componentes de sistema
  │   ├── allaid/           # daemon systemd
  │   └── allai-ctl/        # CLI
  ├── distro/               # construcción de la distro
  │   ├── kickstart/
  │   ├── ostree/
  │   ├── rpms/             # SPECs personalizados
  │   ├── branding/         # wallpapers, plymouth, gdm
  │   └── ci/
  ├── installer/            # scripts post-install
  ├── website/              # Next.js o Astro
  └── .github/
      └── workflows/
  ```
- [x] `.gitignore` y `.editorconfig` creados.
- [ ] `pre-commit` con hooks (ruff, gitleaks, etc.) — pendiente cuando llegue código real (fase Link).
- [x] Subido a GitHub `allai-os/allai-os`.
- [ ] Configurar branch protection en `main` (requiere PRs, signed commits) — **acción del usuario en GitHub UI**.

## A.4 — Diagrama de arquitectura `[x]` (cerrada 2026-04-28)

**Tiempo: 1-2 días**

- [x] `docs/architecture.md` completo con:
  - Diagrama de sistema en Mermaid (frontends, daemon, agent core, providers, tools, hardware).
  - Diagrama de capas (7 capas, de hardware a interfaces de usuario).
  - Diagrama de secuencia de una tarea típica.
  - Diagrama de pipeline de seguridad por acción.
- [x] 6 flujos paso a paso documentados: abrir Firefox + buscar, leer PDF, instalar paquete, enviar mensaje a tercero (caso sensible), conectar VPN (gate de credenciales), modo offline.
- [x] Modos de operación enumerados (Trust / Always ask / Paranoid / Demo / Offline / Privacy).

## A.5 — Prototipo de viabilidad ("Computer Use Hello World") `[~]` (código listo 2026-04-30, pendiente ejecución)

**Tiempo: 3-4 días**

- [x] Script Python con loop de Computer Use vs Claude (`agent/prototype/claude_loop.py`): screenshot → tool `computer_20250124` → ejecutar acción → repetir.
- [x] Loop equivalente con Ollama + modelo de visión (`agent/prototype/ollama_loop.py`): respuesta JSON estructurada con parser heurístico.
- [x] Loop con **Gemini Computer Use preview** (`agent/prototype/gemini_loop.py`): tool `computer_use` nativo de Google con `environment=ENVIRONMENT_BROWSER`, mapeo de acciones (`click_at`, `type_text_at`, `key_combination`, `scroll_at`, `drag_and_drop`, etc.) a nuestros tools locales.
- [x] Tools compartidos (`agent/prototype/tools.py`): mss para screenshot, pyautogui para input, subprocess para shell/launch.
- [x] Entrypoint `agent/prototype/run.py` con CLI: `--provider claude|ollama|gemini`, `--task "..."`, `--benchmark`.
- [x] 10 tareas de evaluación definidas en `BENCHMARK_TASKS`.
- [x] Script `setup_vm.sh` para instalar dependencias en Fedora (incluye instrucciones para `GOOGLE_API_KEY`).
- [x] Plantilla `docs/prototype-results.md` para registrar corridas.
- [x] `integration_demo.py` registra automáticamente Claude / Gemini / Ollama si las credenciales/servicios están disponibles.
- [ ] **Pendiente del usuario**: ejecutar en VM con cada provider y completar `docs/prototype-results.md`.
- **Criterio de éxito**: completar 7/10 tareas simples sin intervención por al menos un provider. Si falla, replanificar (no es bloqueante para seguir, pero ajusta expectativas).

---

# FASE L — Link (Capa de Proveedores)

> Construir la abstracción híbrida que permite a allAI hablar con cualquier modelo capaz, eligiendo el mejor según tarea, costo y disponibilidad.

**Duración estimada: 3-4 semanas**

## L.1 — Provider abstraction `[x]` (cerrada 2026-04-28, ampliada 2026-04-30 con Gemini)

**Tiempo: 4-5 días**

- [x] `agent/core/messages.py` — tipos provider-agnostic (Message, ContentBlock, ChatRequest/Response, Tool, ComputerUseTool, StreamEvent, Usage).
- [x] `agent/core/provider.py` — interfaz `Provider` (ABC) con `capabilities`, `is_available`, `chat`, `chat_stream`. `ProviderCapabilities` y `ModelInfo` describen qué soporta cada uno.
- [x] `agent/core/errors.py` — `ProviderError`, `AuthenticationError`, `RateLimitError`, `InvalidRequestError`, `ProviderUnavailableError`.
- [x] `agent/providers/claude.py` — los 3 modelos (Opus 4.7, Sonnet 4.6, Haiku 4.5), prompt caching automático en system+tools, Computer Use con beta header, streaming traducido a `StreamEvent`.
- [x] `agent/providers/ollama.py` — detección de modelos via `ollama.list()`, vision por nombre, tool-use nativo (Qwen/Llama 3+) o emulado (parser JSON balanceado), Computer Use emulado.
- [x] `agent/providers/gemini.py` (2026-04-30) — modelos Gemini 2.5 Pro / Flash / Flash-Lite + Computer Use preview, function calling nativo, vision en cualquier modelo 2.5, streaming traducido a `StreamEvent`, traducción de `ToolUseBlock` ↔ `function_call/function_response`.
- [x] `agent/pyproject.toml` — ruff + mypy strict + pytest configurados (ADR-001), `google-genai` añadido como dependencia.
- [x] **51 tests unitarios pasando** con mocks (sin red): codificación de blocks, traducción de responses, prompt caching, beta de Computer Use, fallbacks, parser JSON anidado, function_call de Gemini, ruteo automático al modelo Computer Use cuando hay `ComputerUseTool`.
- [ ] Tests de integración con red real — pendiente para cuando Juan Manuel ejecute en VM con `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` y `ollama serve`.

## L.2 — Router inteligente `[x]` (cerrada 2026-04-28, refactor 2026-04-30 para multi-provider)

**Tiempo: 3-4 días**

- [x] `agent/core/policy.py` — `RoutingMode` (auto/cloud_first/local_first/cloud_only/local_only), `RoutingPolicy` con flags de PII/visión/computer_use/preferencias por sesión, `CostBudget` con tope mensual/sesión.
- [x] `agent/core/privacy.py` — detector de PII (email, teléfono, tarjeta con Luhn, claves API conocidas, claves PEM, password fields, IDs nacionales). Snippets redactados.
- [x] `agent/core/task_classifier.py` — `TaskKind` (computer_use, vision, tool_chain, plain_chat) inferido de la forma de la `ChatRequest`. `TaskHints` para overrides por mensaje.
- [x] `agent/core/router.py` — `Router` con `route()` (decisión pura) y `chat()` / `chat_stream()` con fallback automático. PII y hints fuerzan local. Errores de auth/rate-limit propagan inmediatamente; sólo `ProviderUnavailableError` activa fallback. Selección de modelo por capabilities + costo (Haiku > Opus para tareas simples, Opus para Computer Use).
- [x] **Refactor 2026-04-30**: `_cloud_provider()` / `_local_provider()` → `_cloud_providers()` / `_local_providers()` (lista). Ahora la cadena de fallback puede tener varios cloud (Claude → Gemini) y varios local en orden, en lugar de un único provider por categoría.
- [x] **42 tests** (77 totales tras L.2): privacidad, clasificación, fallback, presupuesto agotado, modelo preferido respetado o saltado por capabilities, no fallback en errores de auth.
- [ ] Telemetría local de decisiones — pendiente (audit log de fase Launch lo cubrirá).

## L.3 — Tool registry `[x]` (cerrada 2026-04-28)

**Tiempo: 1 semana**

Implementar tools en `agent/tools/`. Cada tool: schema JSON + ejecutor + tests + nivel de riesgo (`safe` / `confirm` / `dangerous`).

- [x] `tools/base.py` — `RiskLevel`, `ToolDefinition`, `ToolResult`, errores tipados.
- [x] `tools/registry.py` — `ToolRegistry` central + global default + filtros por riesgo/categoría + conversión a `core.Tool` para el provider.
- [x] `tools/executor.py` — `ToolExecutor` con dispatcher, `ConfirmationProtocol` y `CapabilityCheckerProtocol` inyectables, `GatePolicy` con modos (always_ask, trust_after_first), validación mínima de schema, captura de excepciones.
- [x] `screen.screenshot` (mss, multi-monitor).
- [x] `mouse.move`, `mouse.click`, `mouse.drag`, `mouse.scroll` (pyautogui — wayland/libei en fase Launch).
- [x] `keyboard.type`, `keyboard.key`, `keyboard.shortcut`.
- [x] `shell.run` (filtra patrones destructivos: rm -rf, sudo, dd, mkfs, force-push, fork-bomb) + `shell.run_dangerous` (DANGEROUS, sin filtro pero confirma siempre).
- [x] `fs.read`, `fs.write`, `fs.list`, `fs.glob`, `fs.delete` (con expansión `~`, truncado a 1MB, refusal a borrar directorios).
- [x] `app.launch` (gtk-launch o ejecutable en PATH).
- [x] `browser.open` real + `browser.navigate`, `browser.dom` stubs (CDP en fase Launch).
- [x] `clipboard.read`, `clipboard.write` (pyperclip).
- [x] `notify.send` (notify-send).
- [x] Schema declarativo embebido en cada `ToolDefinition` (manifest YAML separado innecesario — la fuente de verdad es Python tipado).
- [x] **61 tests nuevos** (138 totales): registry, executor con todos los gates (capability denied, confirm denied, validation, exception catching, riesgos), filtro de patrones destructivos, fs end-to-end con tmp_path.

## L.4 — Memoria del agente `[x]` (completado 2026-05-01)

**Tiempo: 6-9 días** (ampliado por defensa en profundidad — ver decisión del usuario "todos los pasos lo más seguros posibles aunque tomen más tiempo").

### Sub-pasos
- [x] `agent/memory/crypto.py` — Argon2id KDF, salt 32B random, ChaCha20Poly1305 AEAD para sealed exports. Hex export para SQLCipher.
- [x] `agent/memory/permissions.py` — chmod 0700/0600 enforced; refuse-to-open si están mal en POSIX (skip xfail en Windows).
- [x] `agent/memory/store.py` — SQLCipher con AES-256 + HMAC-SHA512; refuse-open sin passphrase / mala / sin salt.
- [x] `agent/memory/audit.py` — append-only JSONL con hash-chain (cada línea referencia hmac de la anterior); `verify` detecta tampering.
- [x] `agent/memory/pii.py` — wrapper de `core/privacy.py`; flag `sensitive=True` bloquea inyección a cloud.
- [x] `agent/memory/injection_guard.py` — 9 familias de patrones de prompt injection; BLOCK/WRAP/ALLOW policy.
- [x] `agent/memory/embeddings.py` — `sentence-transformers` 100% local (`BAAI/bge-m3` GPU≥sm_75, `paraphrase-multilingual-MiniLM-L12-v2` CPU/fallback). NUNCA APIs remotas.
- [x] `agent/memory/retrieval.py` — híbrido FTS5 + semántica; sanitización antes de devolver.
- [x] `agent/memory/session.py` — short-term in-memory; `context_snippet()` para inyectar en prompt.
- [x] `agent/memory/commands.py` — parser "recuerda X / olvida Y / qué sabes de mí / exporta / borra todo".
- [x] `agent/tools/memory.py` — `recall` (SAFE), `memory.list` (SAFE), `remember` (CONFIRM), `forget` (DANGEROUS), `export` (DANGEROUS), `rotate_key` (DANGEROUS).
- [x] Integración via `memory/injector.py` — inyección opcional con delimitadores fuertes (`<allai-memory-context>`); opt-in `allow_sensitive_in_cloud` para entradas sensibles. Capa pura sobre `Router`, no lo modifica.
- [x] ADR-009 — política de memoria local cifrada (`docs/adr/0009-memoria-local-cifrada.md`).
- [x] **Tests de seguridad explícitos**: no abre sin passphrase, mala passphrase rechazada, permisos malos rechazados, audit-log tampering detectado, PII bloquea export sin opt-in, injection patterns detectados, 32 tests de `tools.memory`.

## L.5 — Voz (entrada y salida) `[~]` (en curso 2026-05-02)

**Tiempo: 4-5 días**

- [x] Capa de abstracción `agent/voice/` — `STTProvider`/`TTSProvider`, tipos `AudioBuffer`/`Transcript`/`SynthesizeRequest`/`VoiceInfo` provider-agnostic, jerarquía de errores. 29 tests.
- [x] STT local: **Whisper** (faster-whisper) — `WhisperSTTProvider` con modelos tiny/base/small/medium/large-v3, auto-detección CPU/GPU (int8/float16), resampling lineal a 16kHz, downmix mono, soporte WAV+PCM, traducción a inglés. 22 tests + 1 slow con modelo real.
- [x] TTS local: **Piper** — `PiperTTSProvider`, una voz por instancia (.onnx + .json), inferencia ONNX en CPU/GPU, output WAV o PCM s16le, control de velocidad vía length_scale invertido, voice_id e idioma auto-inferidos del nombre del modelo. 27 tests con mocks (sin descarga de voces reales).
- [x] Wake word opcional: "Hey allAI" con `openWakeWord` — `WakewordDetector` con threshold por modelo, cooldown_seconds para evitar spam, validación estricta del input (PCM s16le 16kHz mono), múltiples modelos cargados en paralelo, reset() para sesiones limpias. 22 tests con mocks.
- [ ] Integración con PipeWire.

---

# FASE L — Launch (Agente de Escritorio)

> Convertir el agente CLI en una experiencia de escritorio fluida e invisible-cuando-debe-serlo.

**Duración estimada: 4-5 semanas**

## L.1 — Daemon `allaid` (Rust) `[ ]`

**Tiempo: 1 semana**

- [ ] `system/allaid` en Rust. Funciones:
  - Servicio systemd `--user`.
  - Expone interfaz D-Bus `org.allai.Agent1`.
  - Spawn del agente Python en sandbox.
  - Gestión de sesiones, kill-switch (señal global con `Ctrl+Alt+Esc`).
  - Audit log estructurado en `~/.local/share/allai/audit.jsonl` (append-only, firmado).
- [ ] CLI `allai-ctl`: status, stop, start, logs, permissions, history.

## L.2 — Overlay UI (GTK4) `[ ]`

**Tiempo: 1.5 semanas**

- [ ] GTK4 + libadwaita, escrito en Python (PyGObject) o Rust (gtk-rs).
- [ ] Hotkey global (`Super+Space` configurable) → invoca overlay tipo Spotlight.
- [ ] Input multimodal: texto, imagen pegada, archivo arrastrado, micrófono.
- [ ] Vista de "lo que está haciendo allAI ahora" con live preview, capacidad de pausar/cancelar.
- [ ] Confirmaciones inline para acciones de riesgo.

## L.3 — Extensión GNOME Shell `[ ]`

**Tiempo: 1 semana**

- [ ] `desktop/gnome-extension/` (GJS).
- [ ] Indicador en panel superior (estado: idle / pensando / actuando).
- [ ] Atajo de teclado registrado a nivel shell.
- [ ] Indicador visual cuando la IA está controlando el mouse/teclado (borde de pantalla animado).
- [ ] Publicable en `extensions.gnome.org`.

## L.4 — Sistema de permisos y consentimiento `[ ]`

**Tiempo: 1 semana**

- [ ] Capabilities por sesión: `read-fs:~/Documents`, `network:any`, `sudo:never`, etc.
- [ ] Promp de consentimiento granular antes de primera vez.
- [ ] Modo "Trust"/"Always ask"/"Never" por capability.
- [ ] Polkit rules para acciones que requieren root.
- [ ] Vista "Activity Center" con todo lo que la IA ha hecho hoy.

## L.5 — Sandboxing y seguridad `[ ]`

**Tiempo: 1 semana**

- [ ] bubblewrap perfil por defecto: bind read-only de sistema, escritura sólo en `~`, sin red salvo lista blanca.
- [ ] SELinux policy custom para `allaid`.
- [ ] Detección de "prompt injection" en contenido de pantalla/web (heurísticas + clasificador).
- [ ] Modo paranoid: cada acción confirmada.
- [ ] Modo demo: dry-run, sólo simula.

---

# FASE A — Assemble (Distro)

> Empaquetar todo en una imagen instalable y reproducible.

**Duración estimada: 4-6 semanas**

## A.1 — RPMs propios `[ ]`

**Tiempo: 1 semana**

- [ ] `distro/rpms/allai-agent.spec`
- [ ] `distro/rpms/allai-daemon.spec`
- [ ] `distro/rpms/allai-overlay.spec`
- [ ] `distro/rpms/allai-gnome-extension.spec`
- [ ] `distro/rpms/allai-branding.spec`
- [ ] Firmar con clave GPG propia.
- [ ] Publicar en **Fedora COPR** (`copr.fedorainfracloud.org/coprs/allai/stable/`).

## A.2 — Imagen base atómica (rpm-ostree) `[ ]`

**Tiempo: 1.5 semanas**

- [ ] Adoptar enfoque tipo **Universal Blue / Bluefin**: imagen OCI construida con `Containerfile` que extiende Fedora Silverblue.
- [ ] `distro/ostree/Containerfile`:
  ```dockerfile
  FROM quay.io/fedora-ostree-desktops/silverblue:41
  COPY rpms/ /tmp/rpms/
  RUN rpm-ostree install /tmp/rpms/*.rpm \
      && rpm-ostree install ollama python3-anthropic ydotool ...
  RUN systemctl enable allaid.service
  ```
- [ ] Build con `rpm-ostree compose image`.
- [ ] Push a `ghcr.io/allai-os/allai:stable`.
- [ ] Probar rebase desde Silverblue: `rpm-ostree rebase ostree-unverified-registry:ghcr.io/allai-os/allai:stable`.

## A.3 — ISO instalable `[ ]`

**Tiempo: 1-2 semanas**

- [ ] Kickstart `distro/kickstart/allai-os.ks` (basado en Workstation, instala imagen ostree).
- [ ] Build con `lorax` / `livemedia-creator` o **`isogenerator`** de Universal Blue.
- [ ] Anaconda con branding personalizado.
- [ ] Probar instalación en VM (UEFI + BIOS, x86_64 inicialmente; aarch64 fase Ignite).
- [ ] Checksum y firma de la ISO.

## A.4 — Branding y experiencia primera-corrida `[ ]`

**Tiempo: 1 semana**

- [ ] Logo y mascota (¿IA con personalidad?). Encargar a diseñador o usar herramientas IA generativas.
- [ ] Wallpaper(s).
- [ ] Plymouth boot splash.
- [ ] GDM theme.
- [ ] Sonidos de sistema sutiles.
- [ ] **First-run wizard**: idioma, cuenta, ¿tienes API key de Claude?, ¿descargar modelo Ollama recomendado?, tour de capacidades, configuración de privacidad.
- [ ] App de bienvenida con tutoriales interactivos donde la propia IA enseña a usarla.

## A.5 — Aplicaciones por defecto `[ ]`

**Tiempo: 3-4 días**

Decidir set de apps preinstaladas. Sugerencia minimalista + IA-friendly:
- [ ] Firefox (con extensión companion para CDP).
- [ ] Files (Nautilus).
- [ ] Terminal (Ptyxis).
- [ ] Text editor (gnome-text-editor).
- [ ] Ollama preinstalado, modelo `qwen2.5vl:7b` descargable opt-in.
- [ ] Flatpak habilitado (Flathub).
- [ ] Eliminar bloatware de Workstation que no aplique.

## A.6 — Hardware compatibility `[ ]`

**Tiempo: 1 semana**

- [ ] Probar en al menos 5 hardware diferentes (laptops Intel/AMD, GPU NVIDIA con drivers, AMD, integradas).
- [ ] Detección automática de GPU para Ollama (CUDA/ROCm).
- [ ] Documentar hardware soportado.

---

# FASE I — Ignite (Lanzamiento, Updates, Comunidad)

> Pasar de "funciona en mi máquina" a "lo usan miles de personas y reciben actualizaciones".

**Duración estimada: 4-6 semanas hasta 1.0, luego ongoing**

## I.1 — Infraestructura de updates `[ ]`

**Tiempo: 1.5 semanas**

- [ ] Cadena de releases: `nightly` → `testing` → `stable`.
- [ ] OSTree push automatizado en CI (GitHub Actions).
- [ ] `rpm-ostree upgrade` automático con notificación al usuario.
- [ ] Rollback transparente con `rpm-ostree rollback` accesible desde overlay.
- [ ] Mirror CDN (Cloudflare R2 o similar).

## I.2 — CI/CD `[ ]`

**Tiempo: 1 semana**

- [ ] GitHub Actions: lint, tests, build RPMs, build imagen OCI, build ISO en releases.
- [ ] Tests E2E en VM headless (qemu + scripts).
- [ ] Security scanning: `cargo audit`, `pip-audit`, Trivy en imágenes.
- [ ] Reproducible builds (objetivo a mediano plazo).

## I.3 — Sitio web y documentación `[ ]`

**Tiempo: 1 semana**

- [ ] `allai-os.org` con Astro o Next.js.
- [ ] Páginas: home (descarga), docs, blog, comunidad, sobre el proyecto, ética.
- [ ] Docs como sitio separado (Docusaurus o Starlight).
- [ ] Demos en video.

## I.4 — Comunidad `[ ]`

**Tiempo: ongoing desde semana 1 de Ignite**

- [ ] Discord o Matrix (preferido Matrix por valores).
- [ ] Foro: Discourse autohospedado.
- [ ] GitHub Discussions activas.
- [ ] Blog técnico semanal durante el desarrollo.
- [ ] Cuentas en Mastodon, X, YouTube.

## I.5 — Beta cerrada → Beta pública → 1.0 `[ ]`

**Tiempo: 4-6 semanas**

- [ ] Beta cerrada con 20-50 personas (amigos, comunidad Fedora, gente curiosa).
- [ ] Iterar 2-3 semanas sobre feedback.
- [ ] Beta pública anunciada en Hacker News, r/linux, r/fedora, blog Fedora Magazine.
- [ ] Bug bash dedicado.
- [ ] **1.0**: cuando se cumplan los criterios de release definidos en `docs/release-criteria.md`.

## I.6 — Modelo económico sostenible `[ ]`

**Tiempo: 1 semana decidirlo, ongoing operarlo**

- [ ] Decisión: ¿donaciones (GitHub Sponsors, Open Collective)? ¿Tier de pago con créditos de Claude incluidos? ¿Soporte enterprise?
- [ ] BYOK (Bring Your Own Key) por defecto — el usuario paga directamente a Anthropic.
- [ ] Opcional: proxy gestionado de allAI con margen para sostener el proyecto.

---

# Pasos adicionales / consideraciones transversales

> Cosas que no caben en una fase pero hay que llevar todo el tiempo.

## Seguridad

- [ ] Threat model documentado (`docs/threat-model.md`).
- [ ] Bug bounty (al menos `SECURITY.md` con disclosure responsable).
- [ ] Auditoría externa antes de 1.0 (objetivo, ideal pero costoso).
- [ ] Firma reproducible de releases con Sigstore/cosign.
- [ ] Defender contra prompt injection en cada superficie (web, archivos, OCR de pantalla).

## Internacionalización

- [ ] i18n desde día uno (gettext). Idiomas iniciales: **español, inglés, portugués**.
- [ ] El agente Claude/Ollama ya es multilenguaje, pero la UI necesita traducción.

## Accesibilidad

- [ ] Cumplir AT-SPI (lectores de pantalla).
- [ ] Alto contraste, tamaños de fuente.
- [ ] Voz como interfaz primaria opcional — gran win para accesibilidad.

## Legal

- [ ] Términos de uso y política de privacidad.
- [ ] Cumplimiento GDPR (datos de usuarios europeos).
- [ ] Disclaimer claro: el usuario es responsable de las acciones que la IA ejecute.
- [ ] Auditoría de licencias de dependencias (FOSSA o similar).

## Riesgos identificados

| Riesgo | Mitigación |
|--------|------------|
| Wayland no permite control global por diseño | Usar `libei` + portales; documentar limitaciones; soporte X11 opcional |
| Costo de Claude API elevado para usuarios | BYOK + Ollama como default funcional; router prefiere local cuando alcanza |
| Computer Use falla en tareas complejas | UX que muestra plan paso a paso, permite editar, pausar; expectativas claras |
| Vulnerabilidad de IA con privilegios | Sandbox estricto, audit log, kill-switch, jamás root sin polkit prompt |
| Mantener una distro es trabajo enorme | Basarse en upstream Silverblue, no fork — sólo capa encima |
| Burnout del desarrollador | Cadencia sostenible, comunidad temprano, no prometer fechas en piedra |

---

## Anexo: comandos rápidos para retomar el trabajo

```bash
# Estado del repo
cd /c/JM/PROGRAMMING/allAI-OS
git status
git log --oneline -10

# Buscar el próximo paso
grep -n "\[~\]" ROADMAP.md  # paso en curso
grep -n "\[!\]" ROADMAP.md  # bloqueos
grep -n "\[ \]" ROADMAP.md | head -5  # próximos pendientes

# Trabajar sobre un paso: marcarlo [~], hacer, marcarlo [x], commit.
```

## Anexo: cómo Claude Code retoma desde aquí

Cuando vuelvas en una nueva sesión, di simplemente:
> "Continúa con el roadmap de allAI OS"

Yo (Claude) leeré este archivo, identificaré el paso `[~]` activo o el primer `[ ]` pendiente, y propondré las siguientes acciones concretas. La memoria del proyecto apunta a este archivo, así que el contexto se reconstruye en segundos.

---

**Última actualización**: 2026-04-30 — Tercer provider añadido (Gemini, Google). Router refactorizado a multi-provider. A.5 ahora cubre Claude + Gemini + Ollama. 154 tests pasando.
