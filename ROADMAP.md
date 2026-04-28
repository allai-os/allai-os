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
- **Fase activa**: A — Architect
- **Paso activo**: A.4 — Diagrama de arquitectura (esqueleto ya en `docs/architecture.md`, falta diagrama formal y flujos)
- **Próxima acción concreta**: completar `docs/architecture.md` con flujos paso a paso de tareas tipo, y opcionalmente comenzar A.5 (prototipo Computer Use).
- **Última sesión**: 2026-04-28, cierre de A.1, A.2 y A.3 — repo `allai-os/allai-os` registrado, dominio `allai-os.org` registrado, 8 ADRs aceptados, commit inicial creado localmente. Push pendiente por verificación SSH de GitHub.
- **Pendientes externos del usuario**:
  - [x] Dominio `allai-os.org` registrado.
  - [x] Repo GitHub `git@github.com:allai-os/allai-os.git` creado.
  - [ ] Resolver host key SSH para que push funcione (ver `Notas de sesión` abajo).
  - [ ] Configurar MX/email para `security@allai-os.org` y `conduct@allai-os.org`.
  - [ ] Investigar trademark de "allAI OS" cuando aplique.
  - [ ] (Opcional) Configurar git global con `user.name` y `user.email` para no tener que pasarlos en cada commit.

## Notas de sesión 2026-04-28

- Commit inicial creado: `36bd0f2 chore: estructura inicial del proyecto allAI OS` en branch `main`. DCO sign-off con email del autor.
- `git push -u origin main` falla con `Host key verification failed`. Causas posibles: la máquina nunca ha conectado a `github.com` por SSH, o el `~/.ssh/known_hosts` no contiene su fingerprint.
- Soluciones (Juan Manuel decide):
  1. **Aceptar la fingerprint manualmente**: `ssh -T git@github.com` y responder `yes`.
  2. **Agregar la fingerprint oficial conocida de GitHub** a `~/.ssh/known_hosts` (Claude puede hacerlo si autorizas).
  3. **Cambiar el remote a HTTPS** con un Personal Access Token: `git remote set-url origin https://github.com/allai-os/allai-os.git`.

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

## A.3 — Inicialización del repositorio `[~]` (en curso 2026-04-28)

**Tiempo: 1 día**

- [x] `git init` en `c:\JM\PROGRAMMING\allAI-OS` y primer commit (`36bd0f2`, branch `main`, DCO sign-off).
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
- [ ] Configurar `.gitignore`, `.editorconfig`, `pre-commit` con hooks (ruff, black, gitleaks).
- [ ] Subir a GitHub bajo `allai-os/allai-os`.
- [ ] Configurar branch protection en `main`, requerir PRs, signed commits.

## A.4 — Diagrama de arquitectura `[ ]`

**Tiempo: 1-2 días**

- [ ] Crear `docs/architecture.md` con diagrama (Mermaid o Excalidraw exportado) de los componentes:
  - Usuario → Overlay UI / Voz / CLI
  - → `allaid` (daemon, Rust)
  - → Agent Core (Python)
  - → Provider Router → {Claude API, Ollama local, futuros}
  - → Tool Executor (sandboxed)
  - → Sistema (Wayland compositor, shell, fs, browser via CDP)
  - ← Audit Log + Permission Prompts
- [ ] Documentar flujos: "abrir Firefox y buscar X", "leer este archivo y resumir", "instalar paquete".
- [ ] Identificar puntos de fallo y cómo se manejan.

## A.5 — Prototipo de viabilidad ("Computer Use Hello World") `[ ]`

**Tiempo: 3-4 días**

- [ ] En una VM Fedora Workstation limpia, escribir un script Python que:
  - [ ] Tome un screenshot de la pantalla.
  - [ ] Lo envíe a Claude API con el tool `computer_20250124`.
  - [ ] Reciba acciones (click, type, key) y las ejecute con `pyautogui` o `ydotool`.
  - [ ] Loop hasta completar tarea: "abre Firefox y busca 'allAI OS'".
- [ ] Repetir con Ollama + Qwen2.5-VL local: usar el mismo loop pero con un parser propio (Ollama todavía no tiene tool-use idéntico, hay que estructurar la respuesta).
- [ ] Documentar latencia, precisión y costos en `docs/prototype-results.md`.
- [ ] **Criterio de éxito**: completar 7/10 tareas simples sin intervención. Si falla, replanificar (no es bloqueante para seguir, pero ajusta expectativas).

---

# FASE L — Link (Capa de Proveedores)

> Construir la abstracción híbrida que permite a allAI hablar con cualquier modelo capaz, eligiendo el mejor según tarea, costo y disponibilidad.

**Duración estimada: 3-4 semanas**

## L.1 — Provider abstraction `[ ]`

**Tiempo: 4-5 días**

- [ ] Definir interfaz `Provider` en `agent/core/provider.py` con métodos: `chat`, `chat_stream`, `vision_chat`, `tool_use`, `compute_use`, `capabilities()`.
- [ ] Implementar `ClaudeProvider` (`agent/providers/claude.py`):
  - Modelos: `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`.
  - Prompt caching habilitado por defecto.
  - Computer Use tool integrado.
  - Streaming.
- [ ] Implementar `OllamaProvider` (`agent/providers/ollama.py`):
  - Detectar modelos instalados localmente.
  - Soporte vision (Qwen2.5-VL, Llama3.2-Vision, MiniCPM-V).
  - Adaptar tool-use al formato JSON de Ollama.
- [ ] Tests unitarios para cada provider con mocks + tests de integración con cuotas mínimas.

## L.2 — Router inteligente `[ ]`

**Tiempo: 3-4 días**

- [ ] `agent/core/router.py`: decide qué provider usar según:
  - Política del usuario (preferencia: cloud / local / auto).
  - Tipo de tarea (computer use → Claude, resumen rápido → local).
  - Disponibilidad de red.
  - Cuota/costo restante.
  - Privacidad de los datos (regex de detección de PII → forzar local).
- [ ] Fallback automático: si Claude falla → Ollama.
- [ ] Telemetría local de decisiones (sin enviar a ningún lado, solo para debug del usuario).

## L.3 — Tool registry `[ ]`

**Tiempo: 1 semana**

Implementar tools en `agent/tools/`. Cada tool: schema JSON + ejecutor + tests + nivel de riesgo (`safe` / `confirm` / `dangerous`).

- [ ] `screen.screenshot()`, `screen.region()`.
- [ ] `mouse.move`, `mouse.click`, `mouse.drag`, `mouse.scroll`.
- [ ] `keyboard.type`, `keyboard.key`, `keyboard.shortcut`.
- [ ] `shell.run` (sandboxed, con confirmación según riesgo).
- [ ] `fs.read`, `fs.write`, `fs.list`, `fs.glob` (con path policy).
- [ ] `app.launch`, `app.focus`, `app.list_windows`.
- [ ] `browser.open`, `browser.navigate`, `browser.dom` (vía CDP a Firefox/Chromium).
- [ ] `clipboard.read`, `clipboard.write`.
- [ ] `notify.send`.
- [ ] Manifest declarativo `tools.manifest.yaml`.

## L.4 — Memoria del agente `[ ]`

**Tiempo: 3-4 días**

- [ ] Memoria de corto plazo: contexto de sesión.
- [ ] Memoria de largo plazo: SQLite local cifrado (sqlcipher) con embeddings.
- [ ] Comandos: "olvida X", "recuerda Y", "qué sabes de mí".
- [ ] **Privacy by default**: la memoria nunca sale del equipo, ni siquiera con Claude (se inyecta en contexto sólo lo relevante a la query).

## L.5 — Voz (entrada y salida) `[ ]`

**Tiempo: 4-5 días**

- [ ] STT local: **Whisper** (faster-whisper) con modelos small/medium.
- [ ] TTS local: **Piper** (alta calidad, voces multi-idioma incluido español).
- [ ] Wake word opcional: "Hey allAI" con `openWakeWord`.
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

**Última actualización**: 2026-04-28 — Roadmap inicial creado.
