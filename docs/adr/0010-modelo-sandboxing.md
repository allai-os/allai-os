# ADR-010: Modelo de sandboxing y consentimiento

- **Estado**: Aceptado
- **Fecha**: 2026-05-04
- **Decididores**: Juan Manuel Castellanos (BDFL)
- **Relacionados**: [ADR-005](0005-sandboxing.md), [ADR-006](0006-modelo-permisos.md), [ADR-009](0009-memoria-local-cifrada.md)

## Contexto

allAI OS es un agente de IA que controla la computadora del usuario con sus permisos: mueve mouse y teclado, captura pantalla, lanza apps, edita archivos, navega web, ejecuta comandos shell. En la posición más inocente posible, esto es un asistente útil. En la peor, es un programa con acceso prácticamente total al equipo, dirigido por un modelo de lenguaje que puede ser engañado, equivocarse, o ser objetivo de **prompt injection** desde contenido externo (páginas web, archivos abiertos, mensajes recibidos, capturas de pantalla con texto adversarial).

ADR-005 ya estableció el stack técnico (bubblewrap + SELinux + seccomp). Este ADR define **cómo** y **con qué granularidad** lo aplicamos, qué se confina, qué consentimiento pedimos al usuario, y cómo construimos defensa en profundidad sin que la UX se vuelva impracticable.

Tensiones principales:

- **Utilidad** (la IA tiene que poder actuar) vs **contención** (no puede hacer cualquier cosa).
- **UX fluida** (no preguntar 50 veces seguidas) vs **consentimiento informado** (que el usuario sepa qué está autorizando).
- **Confiar en el modelo** (es nuestra interfaz) vs **modelo objeto de prompt injection** (puede ser manipulado por contenido que ve).
- **Cobertura de superficie** (cuantas más capas mejor) vs **complejidad de mantenimiento**.

## Decisión

El sandboxing del agente se rige por estos principios:

### 1. Sandbox por default, no opt-in

Cada proceso del agente que ejecute acciones (computer use, shell, fs, browser, app launch) **nace dentro de bubblewrap**. No hay un modo "sin sandbox" para usuarios avanzados; no hay un "skip just this once". La única forma de que algo corra fuera del sandbox es que el desarrollador del agente lo escriba así explícitamente — y eso debe quedar reflejado en el código revisable, no en una preferencia del usuario.

Razón: si "fuera del sandbox" es accesible, una prompt injection exitosa va a llegar ahí más temprano que tarde.

### 2. Defensa en profundidad: tres capas siempre activas

| Capa | Tecnología | Qué impide |
|------|-----------|------------|
| 1. Filesystem / network / user namespace | **bubblewrap** | Acceso a archivos fuera del scope, salir del namespace, leer otros procesos del usuario. |
| 2. Syscall filter | **seccomp BPF whitelist** | Llamar a syscalls inesperadas (ej. `ptrace`, `keyctl`, `bpf`, `mount`). Whitelist de ~80 syscalls esenciales. |
| 3. Mandatory Access Control | **SELinux dominio `allai_t`** | Acceder a labels que el dominio no puede tocar, aunque DAC lo permitiera. |

Las tres siempre activas. Un atacante que rompa una capa todavía tiene dos. No aceptamos la lógica "ya con bwrap es suficiente para v1".

### 3. Capabilities por sesión, no por instalación

El usuario no concede permisos al "agente" globalmente. Concede capabilities a una **sesión** (la conversación actual). Cuando se cierra la sesión, las capabilities se revocan. Para una nueva sesión hay que volver a otorgar — aunque la UI puede recordar consentimientos previos para la misma capability con el mismo scope (ver §6).

Capabilities reconocidas (ejemplos no exhaustivos):

- `read-fs:~/Documents` — lee bajo `~/Documents` recursivo.
- `write-fs:~/Pictures/allai-output` — escribe bajo un subdirectorio acotado.
- `network:api.openweathermap.org` — abre conexiones a un host específico.
- `network:any` — abre cualquier conexión (peligroso, requiere modo paranoid=False y confirmación explícita).
- `shell:read-only` — ejecuta comandos sin modificar archivos (p.ej. `ls`, `git status`).
- `shell:writes` — comandos que modifican.
- `clipboard:read`, `clipboard:write`.
- `screen:capture`.
- `input:keyboard`, `input:mouse` (necesarias para Computer Use).
- `app:launch:firefox`, etc.
- `sudo:never` — el sandbox refusará cualquier intento de elevación, polkit aparte.

Cada capability tiene **scope**, **caducidad** (default: fin de sesión), y queda registrada en el audit log con timestamp y quién la concedió.

### 4. Tres modos de operación

| Modo | Confirmaciones | Sandbox | Para qué sirve |
|------|---------------|---------|----------------|
| **paranoid** | Confirma cada acción individual, incluso `safe`. | Sandbox + lista blanca explícita por hostname. | Demos sensibles, primer uso, debugging. |
| **normal** (default) | Confirma `confirm` y `dangerous` (igual que el `ToolExecutor` actual). | Sandbox + capabilities concedidas por sesión. | Uso diario. |
| **demo** | Confirma todo + dry-run total: la IA simula, no ejecuta. | Sandbox sigue activo (defensa adicional, aunque dry-run no tocaría nada). | Grabar videos, mostrar la app, training material. |

El modo se elige al iniciar la sesión y no se puede subir el privilegio a media sesión sin reiniciar (puede bajar — paranoid → normal exige re-consentimiento; normal → paranoid es libre).

### 5. Detección de prompt injection en superficies de entrada

`memory.injection_guard` ya define 9 familias de patrones (jailbreak, role hijacking, IGNORE PREVIOUS, exfiltración, etc.) y se aplica al **escribir** en memoria. Aquí lo extendemos a **leer** del mundo exterior:

- **Screenshots** (computer use): tras capturar, OCR (Tesseract) y pasar el texto extraído por `injection_guard`. Si match alta-confianza, **dropear el screenshot del prompt** y pedir al usuario confirmación con un preview del texto sospechoso antes de continuar la tarea.
- **Contenido web** (`browser.dom`, `browser.text`): mismo escaneo sobre el HTML/texto.
- **Archivos** (`fs.read`): mismo escaneo sobre el contenido.
- **Clipboard** (`clipboard.read`): mismo escaneo.

Política por superficie:
- En screenshots y clipboard → siempre escanear y advertir.
- En `fs.read` con `--allow-injection` explícito → permitir (útil cuando uno está intencionalmente leyendo un dataset de jailbreaks).
- En contenido web → siempre escanear; bloquear si la página viene de un dominio fuera de capability.

### 6. Memoria de consentimientos (UX-friendly + auditable)

Para no forzar 50 confirmaciones idénticas en una sesión, allAI recuerda:

- Capability concedida con scope idéntico → no re-pregunta en la misma sesión.
- Capability concedida con scope idéntico repetidamente entre sesiones → la UI ofrece "recordar para esta carpeta" (memorización persistente, escrita a `~/.local/share/allai/sandbox-consents.jsonl` cifrada con la misma key del módulo memoria).
- **Excepciones**: las capabilities `dangerous` (sudo, network:any, fs sobre dotfiles del sistema) **nunca** se memorizan. Cada uso confirma.

### 7. Kill switch redundante con audit

El usuario debe poder parar al agente con confianza, incluso si la UI está congelada. Tres caminos paralelos:

1. **Hotkey global** `Ctrl+Alt+Esc` (configurable). Registrada por la extensión GNOME (Launch.3) o por libei en sesiones donde la extensión no está. Mata todos los procesos del agente.
2. **Panic file**: si `~/.local/share/allai/PANIC` aparece, un watcher en `allaid` que polea cada 250ms mata todo. Útil cuando puedes acceder al filesystem desde otra terminal/SSH pero no a la UI.
3. **Señal `SIGUSR1`** a `allaid` → shutdown ordenado, flush de buffers, cierre limpio. Para scripts.

Cada activación queda en `~/.local/share/allai/kill-events.jsonl` con timestamp, fuente del kill, estado al momento del kill (qué tool se estaba ejecutando, qué capability tenía la sesión). Append-only con hash-chain estilo audit log de memoria — hace detectable que alguien intente borrar evidencia de un kill.

### 8. Polkit: `auth_admin_keep` siempre, sin trust-the-session

Para acciones que requieren root (instalar paquete, modificar systemd, montar disco), allAI no actúa directamente. Llama a polkit, que pide la contraseña del usuario al **administrador autorizado** (típicamente el mismo usuario). Política de polkit:

- `<allow_active>auth_admin_keep</allow_active>`: el usuario teclea su contraseña; queda válida ~5 minutos para acciones idénticas inmediatas (esto es comportamiento de polkit, no nuestro).
- **JAMÁS** `allow_active=yes`. Esto es no-negociable.
- Acciones granulares: `org.allai.system.install_package`, `org.allai.system.modify_user_systemd`, etc. Sin un `org.allai.system.do_anything` comodín.

### 9. Activity Center

Toda acción del agente alimenta tres flujos verificables:

1. `~/.local/share/allai/audit.jsonl` (memoria) — operaciones sobre memoria.
2. `~/.local/share/allai/sandbox-events.jsonl` (sandbox) — capabilities concedidas/usadas/denegadas, syscalls bloqueadas, hostnames bloqueados.
3. `~/.local/share/allai/kill-events.jsonl` (kill) — activaciones del kill switch.

Los tres con hash-chain. La UI de Activity Center (Launch.4) los lee y muestra al usuario "qué hizo allAI hoy".

## Alternativas consideradas

- **Sólo bubblewrap, sin seccomp ni SELinux**: rechazado. Bubblewrap es bueno aislando filesystem y network, pero un sandboxbreakout vía syscall raro (`unshare` + `setns`) o vía exploit del kernel queda sin protección. La defensa en profundidad es barata de añadir y muy cara de retroactivamente meter.
- **Confiar en flatpak/portales**: rechazado como única capa. Flatpak es genérico y diseñado para aplicaciones que el usuario eligió ejecutar; aquí tenemos un proceso dirigido por LLM, mucho más adversarial. Reusamos los **portales** de XDG (file picker, screenshot) cuando aplica, pero el sandbox principal es nuestro.
- **Capability "trust the session entirely"**: rechazado. La conveniencia no compensa el riesgo: la sesión puede ser secuestrada por prompt injection a media tarea.
- **Detección de prompt injection con clasificador ML**: aceptado como complemento futuro, no como reemplazo. Las heurísticas de `injection_guard` son explicables y auditables; un modelo opaco que clasifica false-positive vs false-negative agrega valor pero no debe ser la única capa.
- **Modo "trust" como default**: rechazado. El usuario no debe pagar el costo de un modelo manipulado por confiar por default. Default es `normal`, no `trust`.
- **Cifrar el panic file con HMAC**: descartado por inutilidad. Si el panic file aparece queremos matar; un atacante que pueda escribir ahí ya tiene control total del usuario y matar al agente es lo de menos.

## Consecuencias

### Positivas

- Una prompt injection exitosa todavía está limitada por bwrap + seccomp + SELinux + capabilities. Para un escape real, el atacante necesita encadenar 4 fallos simultáneos.
- El usuario ve qué se autoriza, cuándo, y puede revocar. Audit log inmutable.
- El kill switch redundante reduce el riesgo de "no pude parar a la IA" a algo arquitectónicamente improbable.
- Diseñar el sandbox antes que el daemon previene encajonar seguridad sobre código ya escrito.

### Negativas

- Mantener una SELinux policy custom es trabajo recurrente; cuando upstream cambia paths, hay que actualizar `allai.te`.
- El whitelist de syscalls puede romper cuando una dependencia agregue una syscall nueva (ej. `io_uring` en versiones nuevas de glibc). Tenemos que monitorear.
- Confirmaciones repetidas en modo paranoid pueden cansar al usuario; mitigamos con la memoria de consentimientos pero no la eliminamos.
- Tesseract OCR no es perfecto; algunos screenshots con prompt injection visualmente diseñada (texto en imagen, ASCII art, etc.) pueden colarse. Documentamos como riesgo conocido y planificamos un detector multimodal en una iteración futura.

### Neutras

- Algunas tools del agente que hoy funcionan plano (ej. `app.launch firefox`) ahora dependen de tener la capability `app:launch:firefox` concedida. La primera vez que ocurra, la sesión piensa el flujo de consentimiento; sesiones siguientes con scope idéntico no.
- En distros que no son allAI OS, la SELinux policy puede no estar cargada; el sandbox sigue funcionando con bwrap+seccomp solamente, pero perdemos una capa. Lo documentamos como "soporte limitado en otras distros".

## Estructura de archivos

```
agent/sandbox/
├── policy.py             # SandboxPolicy, capabilities, modos
├── bwrap.py              # generador de comandos bubblewrap
├── seccomp.py            # generador de filtro BPF
├── selinux.py            # carga del dominio allai_t
├── injection_screen.py   # OCR + injection_guard sobre screenshots/web/archivos
├── kill_switch.py        # panic file watcher, señales, audit
└── tests/

distro/
├── selinux/allai.te      # política SELinux del dominio allai_t
└── polkit/org.allai.policy
```

```
~/.local/share/allai/
├── memory/                       # ya existe (ADR-009)
├── sandbox-events.jsonl          # capabilities/syscalls/hostnames bloqueados
├── kill-events.jsonl             # activaciones del kill switch
├── sandbox-consents.jsonl        # capabilities memorizadas entre sesiones (cifrado)
└── PANIC                         # archivo trigger (no debe existir nunca; si aparece, muere todo)
```

## Plan de implementación

Ver [ROADMAP.md § Launch.5](../../ROADMAP.md). Resumen: 13 días repartidos entre policy.py (días 2-3), bwrap.py (4-5), seccomp.py (6), selinux.py (7), injection_screen.py (8-9), kill_switch.py (10), polkit (11), integración con tools (12), commit final (13).

## Referencias

- [ADR-005](0005-sandboxing.md) — stack técnico (bwrap + SELinux + seccomp).
- [ADR-006](0006-modelo-permisos.md) — modelo de permisos polkit + capability system.
- [ADR-009](0009-memoria-local-cifrada.md) — memoria del agente y `injection_guard` reusable.
- [docs/threat-model.md](../threat-model.md) — análisis de amenazas que justifica las elecciones aquí.
- [bubblewrap](https://github.com/containers/bubblewrap) — sandbox de Flatpak, primitive bien probada.
- [libseccomp](https://github.com/seccomp/libseccomp) — filtros BPF de syscalls.
- [SELinux Policy](https://github.com/fedora-selinux/selinux-policy) — base sobre la que escribimos `allai.te`.
- [polkit](https://www.freedesktop.org/wiki/Software/polkit/) — autorización fina.
