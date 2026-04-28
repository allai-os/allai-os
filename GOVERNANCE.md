# Gobernanza de allAI OS

Este documento describe cómo se toman decisiones en el proyecto allAI OS.

## Etapa actual: BDFL benevolente

Mientras el proyecto está en fase fundacional (pre-1.0), allAI OS opera bajo el modelo de **Benevolent Dictator For Life** (BDFL).

- **BDFL**: Juan Manuel Castellanos Hernández — fundador y mantenedor principal.
- **Decisiones técnicas y de producto**: las toma el BDFL, idealmente tras escuchar a la comunidad y a contribuidores.
- **Mergeo de PRs**: el BDFL o personas designadas explícitamente como mantenedores.
- **Cambios en licencia, código de conducta o gobernanza**: requieren anuncio público con al menos 14 días de comentarios.

Este modelo busca velocidad y coherencia técnica en la etapa más frágil del proyecto. No es definitivo.

## Etapa siguiente: gobernanza distribuida (objetivo post-1.0)

Cuando el proyecto alcance estabilidad y comunidad sostenible, la gobernanza se moverá a un modelo distribuido. Criterios para iniciar la transición:

1. Versión 1.0 publicada y al menos 6 meses de operación estable.
2. Al menos 5 mantenedores activos durante 6 meses consecutivos.
3. Una comunidad de usuarios funcional (foro, canales, contribuciones externas regulares).

Modelo objetivo: **Steering Committee electo** (3-7 personas) + grupos de trabajo por área (agente, distro, comunidad, seguridad). Inspiraciones: Fedora Council, Rust Project, Python Steering Council.

A largo plazo, se considerará la creación de una **fundación sin ánimo de lucro** que albergue las marcas, dominios y tesorería. No antes de que el proyecto lo justifique.

## Roles actuales

| Rol | Responsable | Responsabilidades |
|-----|-------------|-------------------|
| BDFL | Juan Manuel Castellanos | Visión, decisiones finales, releases |
| Mantenedores | (vacante) | Revisar y mergear PRs en su área |
| Contribuidores | Cualquiera | Issues, PRs, discusiones |
| Comunidad | Cualquiera | Uso, feedback, evangelización |

Para ser mantenedor: contribuir consistentemente durante al menos 3 meses y ser invitado por el BDFL.

## Cómo se proponen cambios mayores

Para cambios arquitectónicos, de producto o de proceso significativos:

1. Abrir un **ADR** (Architecture Decision Record) en `docs/adr/` siguiendo la plantilla.
2. Anunciar en el canal correspondiente.
3. Período de comentarios mínimo: 7 días para cambios técnicos, 14 días para cambios de gobernanza/licencia.
4. Decisión registrada con quórum: BDFL en etapa actual.

## Conflictos

Las disputas se resuelven en este orden:

1. Discusión pública en issue/PR/foro.
2. Mediación por un mantenedor neutral.
3. Decisión del BDFL como instancia final, con razones documentadas.

Las violaciones del [Código de Conducta](CODE_OF_CONDUCT.md) se manejan separadamente según ese documento.

## Transparencia

- Todas las decisiones de gobernanza se documentan en commits, ADRs o anuncios públicos.
- Las cuentas y gastos del proyecto se publicarán cuando exista tesorería.
- No hay decisiones secretas que afecten a la comunidad.

---

Última actualización: 2026-04-28
