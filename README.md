# allAI OS

> Una distribución Linux basada en Fedora donde la inteligencia artificial es ciudadano de primera clase del sistema operativo.

**Estado**: Pre-alfa, en desarrollo activo. Iniciado en abril de 2026.

## ¿Qué es allAI OS?

allAI OS es un sistema operativo en el que un agente de IA puede hacer todo lo que haría un usuario humano: mover el cursor, abrir aplicaciones, ejecutar comandos, leer y escribir archivos, navegar la web, hablar y escuchar. Inspirado en la idea del IDE Antigravity, pero llevada al nivel completo del escritorio.

El agente es **híbrido por diseño**:

- **Claude API** (Anthropic) como cerebro principal cuando el usuario tiene clave de API. Capacidades avanzadas de Computer Use, razonamiento extendido y herramientas.
- **Ollama + modelos locales** (Qwen2.5-VL, Llama 3.2 Vision, etc.) como alternativa gratuita, offline y respetuosa con la privacidad.
- Arquitectura agnóstica: cualquier proveedor capaz puede sumarse en el futuro.

Cada acción de la IA pasa por un sistema de permisos auditable, sandbox por defecto y un kill-switch global siempre disponible.

## Visión

> Que cualquier persona, sin importar su nivel técnico, pueda usar una computadora completa con sólo describir lo que quiere lograr.

allAI no es un asistente más. Es un sistema operativo donde la línea entre "lo que el usuario quiere" y "lo que la máquina hace" se desdibuja, conservando control humano y transparencia total sobre lo que ocurre.

## Estado del proyecto

Este proyecto está en fase de fundamentos. Toda la información viva sobre el plan, decisiones y progreso vive en:

- [ROADMAP.md](ROADMAP.md) — Plan maestro por fases (A-L-L-A-I) con tiempos estimados y checkboxes de avance.
- [docs/architecture.md](docs/architecture.md) — Diagrama y flujos del sistema *(pendiente — fase A.4)*.
- [docs/adr/](docs/adr/) — Registros de decisiones arquitectónicas *(pendientes — fase A.2)*.
- [docs/AI_ETHICS.md](docs/AI_ETHICS.md) — Código de ética para el agente.

## Cómo contribuir

El proyecto está en una etapa demasiado temprana para PRs externos extensivos, pero se aceptan:

- Issues con ideas, casos de uso o reportes de cosas pensadas que no consideramos.
- Discusiones de arquitectura.
- Pruebas de los prototipos cuando estén disponibles.

Lee primero [CONTRIBUTING.md](CONTRIBUTING.md) y [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Licencia

allAI OS se distribuye bajo la [Apache License 2.0](LICENSE), salvo componentes específicos que la cadena de Fedora exija bajo GPL u otra licencia compatible. Cada componente declara su licencia en su propia carpeta.

## Aviso

allAI OS no está afiliado con Anthropic, el proyecto Fedora ni Red Hat. "Claude" es marca de Anthropic; "Fedora" es marca de Red Hat, Inc. allAI OS las usa con fines de interoperabilidad y atribución.
