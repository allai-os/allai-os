# Prototipo de viabilidad — A.5

> "Computer Use Hello World" — el primer test técnico real de allAI OS.

Este prototipo prueba que la idea funciona: pedirle a una IA que controle un escritorio Fedora y verificar que puede completar tareas simples por su cuenta.

**Importante**: este es código de prototipo. **No es la arquitectura final**. No tiene sandbox real, ni capability system, ni audit log firmado, ni IPC D-Bus. Esas piezas vienen en la fase Link / Launch. El objetivo aquí es exclusivamente **validar viabilidad técnica**.

## Qué prueba

1. Que **Claude Computer Use** funciona en una VM Fedora moderna y puede completar tareas simples sin intervención humana.
2. Que **Ollama + un modelo de visión** (Qwen2.5-VL) puede hacer lo mismo, aunque con menor precisión y con parser propio del JSON de respuesta.
3. Que la latencia y el costo son aceptables para flujos típicos.

## Tareas de evaluación

Las 10 tareas que ejecutamos para medir éxito:

1. Abrir Firefox.
2. En Firefox, navegar a `https://allai-os.org` (cuando exista; entretanto `https://duckduckgo.com`).
3. Buscar "allAI OS" en el motor por defecto.
4. Abrir el terminal y ejecutar `uname -a`.
5. Crear un archivo `/tmp/hello.txt` con contenido "hola allAI" usando `gnome-text-editor`.
6. Tomar un screenshot y guardarlo en `~/Pictures/test.png` (vía la app Captura de pantalla).
7. Cambiar el wallpaper a uno de los predeterminados.
8. Abrir Configuración → Pantalla y leerme la resolución actual.
9. Abrir Files, ir a `/etc`, leerme cuántos archivos `.conf` hay.
10. Cerrar todas las ventanas abiertas.

**Criterio de éxito**: 7/10 tareas completadas sin intervención. Si falla, no es bloqueante para seguir el roadmap, pero ajusta expectativas y prioriza qué tools necesitan más trabajo.

## Requisitos

### En la VM Fedora

- **Fedora Workstation 41+** (Wayland o sesión Xorg; ver nota abajo).
- **Python 3.12+**.
- **Sesión gráfica activa** (no SSH headless; el prototipo necesita ver la pantalla real).
- Para Ollama: **al menos 8 GB de RAM** (mejor 16 GB) y opcionalmente GPU.

### Wayland vs Xorg

Este prototipo usa `pyautogui` para input y screenshots, que funciona **directamente en Xorg** y **necesita configuración adicional en Wayland**.

- **Camino fácil (recomendado para el prototipo)**: en GDM, click en el engranaje al elegir usuario → "GNOME on Xorg" → login. Todo funciona out of the box.
- **Wayland**: el prototipo funciona limitadamente. Se necesita `ydotool` (y permisos sobre `/dev/uinput`) o el camino correcto que será `libei` en la fase Link. Para validar viabilidad, Xorg basta.

La distro final usará Wayland + libei como decide [ADR-003](../../docs/adr/0003-servidor-grafico.md). El prototipo es desechable.

## Setup

```bash
# En la VM Fedora
sudo dnf install -y python3-pip python3-virtualenv xdotool gnome-screenshot

# Para la rama Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5vl:7b

# Clonar y preparar
git clone git@github.com:allai-os/allai-os.git
cd allai-os/agent/prototype
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecutar

### Con Claude

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
python run.py --provider claude --task "abre Firefox y busca allAI OS"
```

Logs y screenshots quedan en `./prototype-runs/<timestamp>/`.

### Con Ollama

```bash
ollama serve  # en otra terminal si no está corriendo
python run.py --provider ollama --model qwen2.5vl:7b --task "abre Firefox y busca allAI OS"
```

### Modo benchmark (las 10 tareas)

```bash
python run.py --provider claude --benchmark
python run.py --provider ollama --model qwen2.5vl:7b --benchmark
```

Genera reporte en `./prototype-runs/<timestamp>/report.md` con resultados por tarea.

## Salida esperada

Cada acción se loggea con timestamp. Por ejemplo:

```
[14:32:01.234] task: "abre Firefox y busca allAI OS"
[14:32:01.235] iter 0: screenshot 1920x1080 -> 287KB
[14:32:01.236] -> claude (claude-opus-4-7) [computer_20250124]
[14:32:03.842] <- 1 tool_use: launch app firefox
[14:32:03.844] tool: app.launch(firefox) ok
[14:32:08.110] iter 1: screenshot ...
[14:32:08.111] -> claude
[14:32:10.221] <- 1 tool_use: click 850, 60
[14:32:10.222] tool: mouse.click(850, 60) ok
...
[14:32:28.880] task complete after 8 iterations, 14.3s, 12 tool calls
```

## Reportar resultados

Cuando termines una corrida del benchmark, compártelo en `docs/prototype-results.md`. Estructura sugerida:

```markdown
# Resultados del prototipo A.5

## Corrida 2026-MM-DD — Claude

- Modelo: claude-opus-4-7
- VM: Fedora 41, GNOME on Xorg, 8 GB RAM
- Tareas completadas: X/10
- Tiempo total: ...
- Tokens consumidos: ...
- Costo estimado: ...
- Notas: ...

## Corrida 2026-MM-DD — Ollama

...
```

## Limitaciones conocidas

- `pyautogui` no maneja Wayland nativo. Usar Xorg para el prototipo o aceptar fallos.
- No hay sandbox: el script puede tocar tu home. Recomendado correr **en VM**, no en host.
- No hay confirmaciones de seguridad. La IA hará lo que decida hacer. **Dale tareas acotadas** y supervisa.
- El parser de tool-use de Ollama es heurístico — Qwen2.5-VL no tiene un formato tan estandarizado como Claude. Esperar más fallos.

## Después del prototipo

Cuando tengas resultados, actualiza el ROADMAP marcando A.5 como completado y avanza a Fase L — Link. Ahí construimos el provider abstraction y el tool registry de verdad, esta vez con la arquitectura de [ADR-001](../../docs/adr/0001-lenguaje-agente-core.md) y [ADR-006](../../docs/adr/0006-modelo-permisos.md).
