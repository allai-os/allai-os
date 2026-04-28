# Contribuir a allAI OS

¡Gracias por tu interés en allAI OS! Este documento describe cómo participar.

## El proyecto está en fase muy temprana

Pre-alfa. Estamos construyendo los fundamentos. Esto significa:

- La arquitectura puede cambiar bruscamente sin previo aviso.
- Muchos componentes aún no existen.
- PRs grandes sobre código todavía sin diseñar serán rechazados con amabilidad.

Si quieres contribuir hoy, lo más útil es:

1. **Issues con casos de uso**: ¿qué te gustaría que allAI OS hiciera por ti? Cuanto más concreto, mejor.
2. **Issues con problemas de seguridad o privacidad** que veas en el roadmap o en código publicado.
3. **Discusiones de arquitectura** comentando los ADRs cuando se publiquen.
4. **Pruebas de prototipos** cuando se anuncien.

## Antes de contribuir código

1. Lee el [ROADMAP.md](ROADMAP.md) para entender en qué fase estamos.
2. Lee los [ADRs](docs/adr/) para entender las decisiones tomadas.
3. Abre un **issue** primero para discutir el cambio. PRs sin issue previo serán cerrados salvo bugs obvios.
4. Acepta que tu contribución se distribuye bajo Apache 2.0 (DCO firmado en cada commit).

## Sign-off de commits (DCO)

Todos los commits deben llevar `Signed-off-by:` para certificar que tienes derecho de aportar el código bajo la licencia del proyecto:

```
git commit -s -m "tu mensaje"
```

Esto añade automáticamente la línea con tu nombre y email.

## Estilo

- **Python**: ruff + black, tipos con mypy estricto.
- **Rust**: rustfmt + clippy con `-D warnings`.
- **JS/TS** (extensión GNOME, web): prettier + eslint.
- **Mensajes de commit**: convencionales (`feat:`, `fix:`, `docs:`, `refactor:`, etc.).
- **Idiomas**: documentación en español e inglés. Código y comentarios en inglés.

## Reportar vulnerabilidades de seguridad

**No** abras un issue público para vulnerabilidades. Sigue el procedimiento en [SECURITY.md](SECURITY.md) *(pendiente — fase A.1)*.

## Código de Conducta

Toda participación está sujeta al [Código de Conducta](CODE_OF_CONDUCT.md). Sin excepciones.

## Preguntas

Mientras no haya foro:

- Issues de GitHub para discusiones técnicas.
- Email del mantenedor para consultas privadas.

Bienvenida y bienvenido. Construyamos algo útil para la humanidad.
