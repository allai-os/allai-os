# Política de seguridad de allAI OS

allAI OS es un sistema operativo donde una IA tiene capacidad real de actuar sobre la máquina del usuario. La seguridad no es opcional: es la condición bajo la cual el proyecto puede existir. Tomamos los reportes de seguridad muy en serio.

## Versiones soportadas

Mientras el proyecto está en pre-alfa (antes de 1.0) sólo se da soporte de seguridad a la rama `main`. Después de 1.0 se publicará una matriz de versiones soportadas.

## Cómo reportar una vulnerabilidad

**No abras un issue público.** Las vulnerabilidades se reportan en privado.

Métodos preferidos:

1. **GitHub Security Advisories**: usa la pestaña "Security" → "Report a vulnerability" en el repositorio (cuando esté disponible).
2. **Email cifrado**: `security@allai-os.org` *(dirección a configurar; usa la clave PGP publicada cuando exista)*.
3. **Email directo**: al mantenedor del proyecto si lo anterior no está disponible.

Incluye en el reporte:

- Descripción del problema y su impacto.
- Pasos para reproducir.
- Versión / commit afectado.
- Si tienes una propuesta de mitigación o parche, mejor.
- Si quieres crédito público, cómo te llamamos en el aviso.

## Qué esperamos de quien reporta

- Darnos un plazo razonable para investigar y publicar parche antes de divulgación pública: **90 días** por defecto, ampliable de mutuo acuerdo si la complejidad lo requiere.
- No explotar la vulnerabilidad más allá de demostrarla.
- No acceder, modificar ni exfiltrar datos de otras personas.

## Qué pueden esperar quienes reportan de nosotros

- Respuesta inicial dentro de **3 días hábiles**.
- Comunicación regular sobre el progreso.
- Crédito público en el aviso si así lo deseas.
- Sin acciones legales por reportes de buena fe que cumplan esta política.

## Áreas de especial interés para nosotros

Por la naturaleza del proyecto, estos vectores son críticos:

- **Escalada de privilegios** desde el agente al sistema.
- **Escape de sandbox** (bubblewrap, SELinux).
- **Prompt injection** que provoque acciones no deseadas (texto en pantalla, contenido de archivos, páginas web maliciosas).
- **Exfiltración de datos** del usuario hacia proveedores externos sin consentimiento.
- **Persistencia indebida** del agente o de instrucciones inyectadas.
- **Bypass del sistema de permisos / kill-switch**.
- **Tampering del audit log**.
- **Vulnerabilidades en la cadena de suministro** (paquetes, modelos, dependencias).

## Bug bounty

No hay programa formal de bug bounty mientras el proyecto sea pre-1.0 y sin financiación. Aún así, reconoceremos públicamente los reportes válidos y, si en algún momento hay tesorería, daremos prioridad a recompensar reportes pasados que nos ayudaron significativamente.

## Divulgación

Tras parchar, publicaremos un aviso de seguridad describiendo:

- El problema (sin detalles que faciliten ataques antes de que la mayoría haya actualizado).
- Versiones afectadas y arregladas.
- Crédito a quien reportó (si aplica).
- Recomendaciones para usuarios.

---

Última actualización: 2026-04-28
