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

> Pendiente: primera corrida de Juan Manuel.
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