# SELinux policy module — allAI OS

Este directorio contiene el módulo SELinux `allai` que confina al daemon
del agente y a los procesos hijos que éste lanza.

## Decisiones

Documento completo en [`docs/adr/0010-modelo-sandboxing.md`](../../docs/adr/0010-modelo-sandboxing.md)
y [`docs/threat-model.md`](../../docs/threat-model.md). Resumen:

- **Default deny**: tipos sin `allow` declarado no se pueden tocar.
- **Defensa en profundidad** sobre bwrap + seccomp.
- **`neverallow`** sobre `shadow_t`, `ssh_home_t`, `gpg_secret_t`,
  `security_t`, `kernel_t` — un módulo accidental futuro no podría
  conceder acceso a estos tipos sensibles.
- **Dos dominios**: `allai_t` (daemon principal) y `allai_sandboxed_t`
  (procesos hijos confinados aún más estrictamente).

## Archivos

| Archivo | Descripción |
|---------|-------------|
| `allai.te` | Type Enforcement: declaraciones de tipos y reglas allow/neverallow. |
| `allai.fc` | File contexts: regex → tipo SELinux. Aplicado por `restorecon`. |
| `allai.if` | Interface: macros públicas que otros módulos pueden invocar. |
| `Makefile` | Build script (`make` / `make install` / `make reload`). |

## Build & install

Requiere `selinux-policy-devel` (Fedora/RHEL):

```bash
sudo dnf install -y selinux-policy-devel
make
sudo make install
```

`make install` ejecuta `semodule -i allai.pp` y luego `restorecon -R`
sobre los paths configurados en `allai.fc`.

## Modos

- **enforcing** (default en allAI OS): denials matan la operación.
- **permissive**: denials se loggean en `/var/log/audit/audit.log` pero
  no bloquean — útil para depurar policies nuevas sin romper la sesión.

```bash
# Ver denials del módulo allai
sudo ausearch -m AVC -ts recent | grep allai

# Generar reglas faltantes a partir de denials
sudo audit2allow -a -M allai_local
sudo semodule -i allai_local.pp   # ¡revisar el .te generado antes!
```

## Iteraciones futuras

Ver `TODO` en `allai.te` y la sección de Launch.5 en
[`ROADMAP.md`](../../ROADMAP.md). Próximas mejoras pendientes:

- Transición tagged-by-capability para que `allai_sandboxed_t` herede
  network selectivamente.
- Booleans para activar/desactivar sub-features (ej. `allai_use_camera`,
  `allai_use_audio`).
- Tests automatizados con `selinux-policy-test` / `sechecker`.
- Auditoría externa de la policy antes de allAI OS 1.0 (objetivo
  declarado en threat-model.md).

## Desarrollo en Windows / macOS

La policy SELinux **sólo compila y carga en Linux con SELinux activo**.
En Windows el módulo Python `agent/sandbox/selinux.py` provee:

- Detección de disponibilidad (`is_selinux_available()`).
- Utilidades para parsear y validar contextos como strings (testeables
  sin libselinux).
- Fallback graceful: si SELinux no está, se loggea un warning pero el
  agente sigue funcionando con bwrap+seccomp.
