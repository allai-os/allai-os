# Resultados del prototipo A.5

> Este archivo se completa cuando Juan Manuel ejecute el prototipo en una VM Fedora.
> Plantilla preparada para anotar resultados de Claude y Ollama de forma comparable.

## Cómo registrar una corrida

Cada vez que corras `python run.py --provider X --benchmark`, copia los datos clave del
`report.md` generado y pégalos como una nueva sección abajo. Mantén las secciones
ordenadas cronológicamente (más reciente arriba).

## Plantilla

```markdown
## YYYY-MM-DD — <provider>

- **Provider**: claude | ollama
- **Modelo**: claude-opus-4-7 | qwen2.5vl:7b | ...
- **Hardware**: CPU, RAM, GPU (si aplica)
- **Sesión gráfica**: Xorg | Wayland
- **Resolución**: 1920x1080 | ...
- **Resultado**: X/10 tareas
- **Duración total**: ...
- **Tokens consumidos**: ... (sólo Claude)
- **Costo estimado**: USD ... (sólo Claude)

### Tareas

| Tarea | Éxito | Iter | Notas |
|-------|-------|------|-------|
| open_firefox | ✅ | 3 | |
| navigate_url | ✅ | 5 | |
| ... | | | |

### Observaciones cualitativas

- Lo que funcionó bien:
- Lo que falló y por qué:
- Sugerencias para fase Link:
```

---

## Corridas

---

## 2026-05-01 — claude (claude-opus-4-7) ✅

- **Provider**: claude
- **Modelo**: claude-opus-4-7
- **Beta header**: `computer-use-2025-11-24` / Tool type: `computer_20251124`
- **Hardware**: Fedora 43, kernel 6.19.14-200.fc43.x86_64, x86_64
- **Sesión gráfica**: Xorg (DISPLAY=:0)
- **Resolución**: 1366×768
- **Resultado**: **8/9 tareas completadas** (1 interrumpida al final de sesión)
- **Duración total**: ~60 min

### Tareas

| Tarea | Éxito | Iter | Duración | Notas |
|-------|-------|------|----------|-------|
| open_firefox | ✅ | 10 | 65s | Abrió Firefox desde terminal |
| navigate_url | ✅ | 12 | 156s | DuckDuckGo cargado correctamente |
| search_term | ✅ | 5 | 35s | Buscó "allAI OS", resultados mostrados |
| terminal_uname | ✅ | 29 | 731s | Ejecutó `uname -a`, leyó output completo |
| create_text_file | ✅ | 25 | 497s | Creó `/tmp/hello.txt` con "hola allAI" |
| take_screenshot | ✅ | 12 | 174s | Screenshot guardado vía gnome-screenshot |
| change_wallpaper | ✅ | 10 | 114s | Cambió wallpaper a azul geométrico |
| read_resolution | ✅ | 4 | 36s | Reportó 1366×768 correctamente |
| count_conf | ❌ | 30 | 757s | Agotó max_iterations sin completar |
| close_all | ⚠️ | 7+ | — | Interrumpida: proceso killed al cerrar sesión |

### Observaciones cualitativas

- **Lo que funcionó bien**: tareas de UI directa (open, navigate, search, wallpaper, resolution) — el modelo navega menús con eficacia.
- **Lo que falló**: `count_conf` (contar archivos .conf en /etc vía Nautilus) — tarea ambigua para navegación GUI; se habría resuelto mejor con shell.
- **`terminal_uname`**: tardó 731s/29 iters — el modelo exploró varios terminales hasta dar con uno funcional, señal de que necesita contexto del entorno.
- **Sugerencias para fase Link**: exponer un tool de shell directo (`bash`) para tareas de conteo/lectura de archivos; reducir dependencia de GUI pura para operaciones que shell resuelve en 1 iter.

---

## 2026-05-01 — claude (bloqueado: sin créditos)

- **Provider**: claude
- **Modelo**: claude-opus-4-7
- **Hardware**: Fedora, sesión X11, pantalla 1366×768
- **Resultado**: 0/10 tareas — bloqueadas por API (no ejecutadas)
- **Error**: `BadRequestError 400 — credit balance too low`
- **Acción**: recargar créditos en console.anthropic.com y re-correr.

---

## 2026-05-01 — gemini (bloqueado: free tier agotado)

- **Provider**: gemini
- **Modelo**: gemini-2.5-computer-use-preview-10-2025
- **Hardware**: Fedora, sesión X11, pantalla 1366×768
- **Resultado**: 0/10 tareas — bloqueadas por API (no ejecutadas)
- **Error**: `429 RESOURCE_EXHAUSTED — free tier quota 0 para computer-use-preview`
- **Acción**: activar billing en Google AI Studio y re-correr.

---

> **Nota técnica (2026-05-01):** Se descubrió y corrigió un bug en `memory/store.py`:
> `PRAGMA key = x'<hex>'` → `PRAGMA key = "x'<hex>'"` (comillas dobles requeridas
> por SQLCipher para el formato blob hex). Los 248 unit tests del agente pasan ahora
> en su totalidad (excl. Ollama).

---

## Corrida anterior — claude (error de SDK)

# Benchmark del prototipo — claude

- Modelo: `claude-opus-4-7`
- Fecha: 2026-04-29 08:05:17
- Resultado: **0/10** tareas completadas
- Duración total: 30.1s

## Detalle

| Tarea | Éxito | Iteraciones | Tool calls | Duración (s) | Error |
|-------|-------|-------------|------------|--------------|-------|
| open_firefox | ❌ | 1 | 0 | 0.01 | TypeError: Messages.create() got an unexpected keyword argument 'betas' |
| navigate_url | ❌ | 1 | 0 | 0.01 | TypeError: Messages.create() got an unexpected keyword argument 'betas' |
| search_term | ❌ | 1 | 0 | 0.01 | TypeError: Messages.create() got an unexpected keyword argument 'betas' |
| terminal_uname | ❌ | 1 | 0 | 0.01 | TypeError: Messages.create() got an unexpected keyword argument 'betas' |
| create_text_file | ❌ | 1 | 0 | 0.03 | TypeError: Messages.create() got an unexpected keyword argument 'betas' |
| take_screenshot | ❌ | 1 | 0 | 0.01 | TypeError: Messages.create() got an unexpected keyword argument 'betas' |
| change_wallpaper | ❌ | 1 | 0 | 0.01 | TypeError: Messages.create() got an unexpected keyword argument 'betas' |
| read_resolution | ❌ | 1 | 0 | 0.01 | TypeError: Messages.create() got an unexpected keyword argument 'betas' |
| count_conf | ❌ | 1 | 0 | 0.01 | TypeError: Messages.create() got an unexpected keyword argument 'betas' |
| close_all | ❌ | 1 | 0 | 0.01 | TypeError: Messages.create() got an unexpected keyword argument 'betas' |