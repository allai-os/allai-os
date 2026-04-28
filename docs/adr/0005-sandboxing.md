# ADR-005: Sandboxing del agente

- **Estado**: Aceptado
- **Fecha**: 2026-04-28
- **Decididores**: Juan Manuel Castellanos (BDFL)

## Contexto

El agent core ejecuta acciones potencialmente arbitrarias derivadas de prompts del usuario (y de contenido externo procesado, como páginas web o archivos). Sin un sandbox sólido, una sola vulnerabilidad o una prompt injection exitosa puede escalar a control total del equipo.

Requisitos:

- Aislar al agente del sistema host por defecto.
- Permitir extender capabilities por sesión de forma granular y revocable.
- Mantener performance aceptable (no se puede meter cada acción en una VM).
- Encajar con SELinux que Fedora trae por default.
- Ser comprensible y auditable.

Tecnologías relevantes:

- **bubblewrap (`bwrap`)**: setuid sandbox usado por Flatpak. User namespaces, mount namespaces, seccomp.
- **firejail**: sandbox setuid alternativo. Más cómodo, pero historia de CVEs por su superficie de ataque.
- **systemd-nspawn**: contenedor más pesado, orientado a servicios completos.
- **Flatpak**: sandbox de aplicaciones gráficas. Usa bubblewrap por debajo.
- **podman**: contenedores OCI, demasiado pesado para procesos de agente.
- **SELinux**: MAC del kernel, ortogonal al sandbox.
- **seccomp-bpf**: filtrado de syscalls, complementario.

## Decisión

Usaremos **bubblewrap** como sandbox primario para el agent core, complementado por:

- **SELinux policy custom** específica para `allaid` y procesos hijos (`allai_agent_t` domain).
- **seccomp-bpf** restringiendo syscalls peligrosas.
- **`xdg-desktop-portal`** como única vía para acceso a recursos del usuario (archivos, screenshots, cámara, micrófono).
- **Capability system propio** por encima de bubblewrap (ver ADR-006).

Perfil base de bubblewrap (resumido):

```
--ro-bind /usr /usr
--ro-bind /etc /etc
--proc /proc
--dev /dev
--bind ~/.local/share/allai ~/.local/share/allai
--tmpfs /tmp
--unshare-all
--share-net           (sólo si la sesión tiene capability network:any)
--die-with-parent
--new-session
```

Sin `--share-net` por defecto. Sin acceso al home del usuario por defecto: el portal de archivos es la vía.

## Alternativas consideradas

- **firejail**: rechazado. Es setuid root, ha tenido vulnerabilidades serias y su superficie es mayor que bubblewrap. La complejidad de su DSL no compensa.
- **systemd-nspawn**: demasiado pesado para procesos cortos. Es para "containers", no para "sandboxes de proceso".
- **Sólo SELinux sin sandbox**: deja al proceso con acceso teórico al sistema, mitigado solo por la policy. Defense-in-depth pide capas.
- **Sólo bubblewrap sin SELinux**: deja al proceso fuera del sandbox del kernel. SELinux atrapa lo que bwrap deja escapar.
- **VMs (microVM como Firecracker)**: aislamiento máximo pero overhead por sesión inaceptable. Tal vez para casos de "ejecutar código no confiable que el usuario me da" en futuro.

## Consecuencias

### Positivas

- bubblewrap es el sandbox de Flatpak y de Steam Runtime — código probado en millones de instalaciones.
- Sin setuid daemon: bwrap drop-privileges correctamente.
- Defense in depth: bubblewrap + SELinux + seccomp + capability system.
- Compatible con el modelo de portales que ya usa GNOME.

### Negativas

- bubblewrap es más restrictivo que firejail: hay que configurar cada acceso. Esto es **bueno** pero exige cuidado.
- Escribir SELinux policy custom es trabajo serio (semanas de iteración para que no rompa).
- Cualquier nueva capability del agente requiere extender el perfil. Disciplina.

### Neutras

- bubblewrap no es un security-boundary firmado: si alguien rompe el kernel, el sandbox cae. Aceptable como tradeoff de un proceso de espacio usuario.

## Plan de implementación

1. `agent/sandbox/bwrap_profile.py` que construye el comando bubblewrap según las capabilities concedidas a la sesión.
2. SELinux policy en `system/selinux/allai.te`, compilada y empaquetada en `allai-selinux.rpm`.
3. seccomp filter en `agent/sandbox/seccomp.py` (lista de allow basada en tipo de tarea).
4. Tests E2E que intentan escapar del sandbox y verifican que fallan.
5. Auditoría manual del perfil antes de cada release mayor.

## Revisión

Reevaluar si:

- bubblewrap deprecara o pierde mantenimiento.
- Surge una vulnerabilidad estructural en su modelo.
- Necesitamos aislamiento más fuerte que el sandbox de proceso (entonces evaluamos VMs ligeras).

Plazo de revisión: cada 6 meses.

## Referencias

- [bubblewrap](https://github.com/containers/bubblewrap)
- [Flatpak sandbox](https://docs.flatpak.org/en/latest/sandbox-permissions.html)
- [SELinux Notebook](https://github.com/SELinuxProject/selinux-notebook)
- ADR-006 (modelo de permisos)
- [docs/AI_ETHICS.md](../AI_ETHICS.md) (mínimo privilegio)
