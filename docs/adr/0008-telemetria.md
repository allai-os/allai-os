# ADR-008: Telemetría y métricas

- **Estado**: Aceptado
- **Fecha**: 2026-04-28
- **Decididores**: Juan Manuel Castellanos (BDFL)

## Contexto

Para mejorar allAI OS necesitamos saber qué funciona y qué no: errores comunes, tareas que fallan, latencias, hardware en uso. Pero allAI OS es un proyecto que pone soberanía y privacidad del usuario primero ([docs/AI_ETHICS.md](../AI_ETHICS.md)), y tiene a la IA tocando todo en la máquina. Una telemetría mal hecha puede destruir la confianza del proyecto antes de empezar.

Tensiones:

- Datos útiles para mejorar el producto vs privacidad absoluta.
- Crashes anónimos vs trazabilidad completa.
- Necesidad de detectar fraude/abuso vs no espiar al usuario.

## Decisión

allAI OS implementa telemetría bajo estos principios:

### 1. Opt-in estricto, granular y revocable

- **Default desactivada**. La instalación por default no envía nada.
- El first-run wizard pregunta: "¿quieres ayudarnos con datos anónimos? Aquí está exactamente qué enviaríamos: [lista]". El usuario marca por categoría.
- Categorías: `crash-reports`, `feature-usage`, `performance-metrics`, `hardware-info`. Cada una independiente.
- Cualquier categoría se puede desactivar en cualquier momento desde Configuración → Privacidad. Cambio aplica inmediatamente.

### 2. Anonimización fuerte

- Sin user IDs persistentes. Cada envío genera una sesión-id efímera.
- Sin direcciones IP en logs (proxy de stripping en el receptor).
- Sin contenido del usuario, jamás. Ni prompts, ni screenshots, ni archivos.
- Hardware: solo categorías agregadas (CPU vendor, GPU vendor genérico, RAM en buckets, no exact specs).
- Resoluciones de pantalla redondeadas a buckets estándar.
- Locale: sólo idioma, no región.

### 3. Mínimo necesario

- `crash-reports`: backtrace + versión + arch + módulo donde crasheó. **No** stack frames con valores locales (revelan datos).
- `feature-usage`: nombre del feature + frecuencia. **No** parámetros, **no** contenido.
- `performance-metrics`: latencia por categoría de tarea + provider usado (claude/ollama). **No** prompts.
- `hardware-info`: una sola vez por upgrade mayor, en buckets.

### 4. Transparencia radical

- Toda telemetría enviada queda registrada en `~/.local/share/allai/telemetry-sent.jsonl`. El usuario ve exactamente qué se envió.
- Schema de cada categoría documentado públicamente en `docs/telemetry-schema.md`.
- Endpoint receptor open source (mismo repo).
- Reportes agregados públicos al menos cada 6 meses.

### 5. Autohospedado

- Servidor receptor gestionado por el proyecto, no terceros.
- Stack: receptor en Rust → ClickHouse o DuckDB → dashboard interno.
- **No** Google Analytics. **No** Sentry SaaS. **No** Mixpanel. **No** ningún tracker comercial, ni en la app ni en el sitio web.
- Para la web: **Plausible** (autohospedado o sin cookies) o nada.

### 6. Operadores de IA: sin telemetría especial

- Las llamadas del usuario a Claude API o a Ollama van directamente a Anthropic / al proceso local. allAI OS **no proxy** esas llamadas ni las registra para el proyecto.
- El audit log de acciones del agente vive en la máquina del usuario y nunca se envía a allAI OS.

### 7. Crash reports especialmente cuidadosos

- Antes de enviar un crash, el usuario ve el contenido exacto del reporte y aprueba.
- Modo "no preguntar más" disponible solo después de que el usuario haya enviado al menos un crash y entendido el formato.

## Alternativas consideradas

- **Cero telemetría**: filosóficamente puro pero imposibilita iterar sobre fallos reales. Una versión opt-in cuidadosa es mejor que ninguna.
- **Opt-out**: rechazado de plano. Viola los principios de soberanía del usuario.
- **Telemetría con tracker comercial (Sentry SaaS, etc.)**: rechazado. No queremos que datos del usuario pasen por terceros que no controlamos.
- **Telemetría con identificadores persistentes**: rechazado. Permite correlacionar comportamientos en el tiempo, viola privacidad.
- **Solo crashes**: insuficiente para entender uso real. Aceptable como punto de partida si el resto se diferenciara post-1.0.

## Consecuencias

### Positivas

- Confianza del usuario preservada.
- Cumple GDPR sin esfuerzo extra (no procesamos datos personales).
- Cualquier auditor puede verificar lo que enviamos.

### Negativas

- Datos más pobres que la competencia comercial. Iteración basada más en feedback cualitativo que en analytics.
- Hosting propio de receptor implica mantenimiento.
- Sin user-IDs no podemos hacer "funnels" de retención clásicos. Aceptable.

### Neutras

- Forzados a diseñar features sin obsesión métrica. Más arte, menos optimización ciega.

## Plan de implementación

1. Schema en `docs/telemetry-schema.md` (Fase Architect, post-A.2).
2. Cliente en `agent/telemetry/` con queue local cifrada y envío diferido.
3. Receptor en `services/telemetry-receiver/` (Rust, stateless).
4. Storage: empezar simple con DuckDB; migrar a ClickHouse si volumen lo exige.
5. Dashboard interno (Grafana o Metabase) tras 1.0.
6. Reporte público anual.

## Revisión

Reevaluar si:

- Aparece evidencia de que necesitamos datos que el modelo actual impide.
- El proyecto crece y mantener el receptor propio es inviable (entonces evaluamos selfhosted Plausible o algo similar; nunca un comercial cerrado).

Plazo de revisión: anual.

## Referencias

- [docs/AI_ETHICS.md](../AI_ETHICS.md) (privacidad como default)
- [GDPR](https://gdpr.eu/)
- [Plausible Analytics](https://plausible.io/) (referencia para web)
- ADR-006 (audit log inmutable, distinto y local)
