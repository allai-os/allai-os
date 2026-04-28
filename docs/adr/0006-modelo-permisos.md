# ADR-006: Modelo de permisos y consentimiento

- **Estado**: Aceptado
- **Fecha**: 2026-04-28
- **Decididores**: Juan Manuel Castellanos (BDFL)

## Contexto

allAI OS otorga a una IA capacidad de actuar sobre la máquina del usuario. El modelo de permisos define qué puede hacer la IA, cuándo necesita preguntar, y cómo se audita lo que hizo. Es **el** sistema más sensible del proyecto.

Restricciones derivadas de [docs/AI_ETHICS.md](../AI_ETHICS.md):

- Soberanía del usuario absoluta.
- Mínimo privilegio.
- Reversibilidad.
- Audit log inmutable.
- Kill-switch siempre disponible.

El sandbox (ADR-005) define qué puede tocar el proceso. El modelo de permisos define qué se le permite hacer dentro de lo que puede tocar — y, sobre todo, qué requiere confirmación humana.

## Decisión

allAI OS implementa permisos en tres capas que cooperan:

### Capa 1: polkit (acciones de sistema)

Acciones que requieren root o cruzan límites de privilegio van por **polkit**, con prompts gráficos del estándar GNOME.

- Acciones registradas en `system/polkit/org.allai.policy`.
- Ejemplos: instalar paquete, cambiar configuración de red a nivel sistema, leer logs `/var/log`.
- Default `auth_admin_keep` (pide contraseña, recuerda 5 min) o `auth_admin` por acción.

### Capa 2: capabilities por sesión (allAI-specific)

Cada sesión del agente tiene un set de **capabilities** activas. Una capability es una promesa otorgada por el usuario para esta sesión: "puedes hacer esto sin preguntarme cada vez".

Capabilities existentes (lista no exhaustiva, vivirá en `agent/permissions/capabilities.yaml`):

| Capability | Descripción |
|------------|-------------|
| `read-fs:<path>` | Lectura del path especificado |
| `write-fs:<path>` | Escritura del path |
| `network:any` | Acceso a red sin restricciones |
| `network:domains:<list>` | Sólo dominios listados |
| `shell:safe` | Shell sin destructivos |
| `shell:any` | Shell sin restricciones |
| `input:emulate` | Mover mouse, teclear |
| `screen:capture` | Tomar screenshots |
| `audio:record` | Micrófono |
| `clipboard:read` `:write` | Portapapeles |
| `app:launch:<app>` | Lanzar app específica |
| `browser:control` | Manejar navegador |
| `notify:send` | Enviar notificaciones |

Cada capability se concede en uno de tres modos:

- **`once`**: válida hasta cerrar la sesión actual.
- **`always`**: persistida en perfil del usuario hasta que la revoque.
- **`never`**: bloqueada hasta que el usuario cambie de opinión.

### Capa 3: gates por acción (riesgos individuales)

Algunas acciones requieren confirmación humana **incluso si la capability está concedida**, por su irreversibilidad o impacto. Definidas en [docs/AI_ETHICS.md](../AI_ETHICS.md), reglas absolutas. Ejemplos:

- `rm -rf` o equivalentes destructivos.
- `git push --force`.
- Envío de mensajes a otras personas.
- Operaciones financieras.
- Modificar archivos de sistema fuera del sandbox.

Estas se cumplen siempre, no son configurables.

### Audit log

Cada acción ejecutada genera una entrada append-only en `~/.local/share/allai/audit.jsonl`:

```json
{
  "ts": "2026-05-01T14:32:01.234Z",
  "session": "abc123",
  "actor": "agent",
  "provider": "claude:claude-opus-4-7",
  "action": "shell.run",
  "args": {"cmd": "ls ~/Documents"},
  "capability_used": "read-fs:~/Documents",
  "result": "ok",
  "user_confirmed": false,
  "duration_ms": 42
}
```

Cada entrada se firma con HMAC-SHA256 con clave por dispositivo (al estilo de TPM si está disponible). El log es inmutable: append-only file con flag de chattr `+a` cuando posible. Una herramienta `allai-ctl audit verify` chequea integridad.

### Kill-switch

Combinación de teclas reservada (default: **Ctrl+Alt+Esc**, configurable) registrada por la extensión GNOME y también por `allaid`. Al activarse:

1. SIGSTOP a todos los procesos hijos del agent core.
2. Liberación de focus, mouse y teclado al usuario.
3. Mensaje en pantalla con resumen de lo que la IA estaba haciendo.
4. Opción de "matar sesión", "reanudar", o "auditar".

### Activity Center

Vista en la overlay UI con:

- Acciones de la última hora / día / semana.
- Filtro por tipo, riesgo, proveedor.
- Capacidad de revertir (si aplica) o reportar como problema.
- Estado de capabilities concedidas, con botón "revocar".

## Alternativas consideradas

- **Sólo polkit**: insuficiente. polkit es para escalada de privilegio, no para granularidad de acciones de un agente.
- **Sólo capabilities sin polkit**: pierdes integración con GNOME y con el resto del sistema (pkexec, etc.).
- **Sólo gates por acción**: agotador para el usuario; cada acción pregunta. UX inviable.
- **Modelo binario "trust/no-trust"**: pierde granularidad. allAI debe hacer cosas seguras sin molestar y cosas peligrosas siempre con consentimiento.
- **Modelo de roles tipo SELinux para el agente**: complementario, no sustitutivo (lo usamos en ADR-005 como capa adicional).

## Consecuencias

### Positivas

- UX equilibrada: lo seguro fluye, lo peligroso se confirma.
- Trazabilidad total con audit log firmado.
- Revocable en cualquier momento por el usuario.
- Compatible con accesibilidad (prompts de polkit y GTK son AT-SPI-friendly).

### Negativas

- Implementación compleja: tres capas que deben coordinarse.
- Diseñar la lista canónica de capabilities requiere iteración con casos reales.
- Audit log puede crecer. Rotación necesaria (mantener 90 días por default + export).

### Neutras

- El usuario tiene que aprender el concepto de capabilities (mitigado por defaults sensatos y wizard de primera corrida).

## Plan de implementación

1. `agent/permissions/` con módulo `capabilities.py`, `gates.py`, `audit.py`.
2. UI de prompts de capability en overlay.
3. Polkit policies en `system/polkit/`.
4. Audit log signer en Rust dentro de `allaid`.
5. Activity Center en overlay (fase Launch).
6. Tests: scenarios donde la IA intenta saltarse cada capa, debe fallar.

## Revisión

Reevaluar si:

- Aparecen patrones de uso reales que el modelo no captura bien.
- El audit log tiene huecos (acciones que no se loguean).
- El kill-switch tiene fallos de UX.

Plazo de revisión: tras la beta cerrada (Fase Ignite).

## Referencias

- [docs/AI_ETHICS.md](../AI_ETHICS.md)
- ADR-005 (sandboxing)
- [polkit docs](https://www.freedesktop.org/software/polkit/docs/latest/)
- Anthropic — [Constitutional AI](https://www.anthropic.com/news/claudes-constitution) (referencia inspirativa, no implementación)
