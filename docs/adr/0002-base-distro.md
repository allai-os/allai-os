# ADR-002: Base de distro y modelo de imagen

- **Estado**: Aceptado
- **Fecha**: 2026-04-28
- **Decididores**: Juan Manuel Castellanos (BDFL)

## Contexto

allAI OS es una distribución Linux distribuible. Necesitamos elegir:

1. La distro upstream sobre la que nos basamos.
2. El modelo de gestión de imagen del sistema (paquetes tradicionales vs imagen atómica).

Restricciones:

- Una IA con privilegios de actuar sobre el sistema necesita garantías fuertes de integridad y rollback. Un upgrade roto en 1.000.000 de máquinas es inaceptable.
- Equipo pequeño (BDFL solo al inicio): no podemos mantener un fork agresivo, sólo una capa encima de upstream.
- El usuario espera updates automáticas y seguras.
- Necesitamos GNOME moderno con buen soporte de Wayland y portales.

## Decisión

Basaremos allAI OS en **Fedora Silverblue 41+** y entregaremos la imagen como **OCI image** construida con `Containerfile`, al estilo de **Universal Blue / Bluefin**.

- Modelo de paquete: **rpm-ostree** (atómico, transaccional, rollback con un comando).
- Distribución de imagen: registry OCI (`ghcr.io/allai-os/allai:stable`).
- Instalación: ISO basada en Anaconda que rebasa a la imagen OCI durante la instalación, o `rpm-ostree rebase` desde una Silverblue existente.
- Aplicaciones GUI del usuario: **Flatpak** (Flathub habilitado por default).
- Paquetes adicionales del usuario: `rpm-ostree install` (overlay) o **Toolbox/Distrobox** para entornos mutables.

## Alternativas consideradas

- **Fedora Workstation tradicional (mutable)**: ecosistema más grande, pero updates rompibles, sin rollback nativo, peor encaja con la responsabilidad de un agente que toca el sistema.
- **Ubuntu LTS / Debian**: comunidad enorme, pero rpm-ostree y Silverblue ofrecen el modelo atómico que queremos sin re-inventar. Snap como tecnología de paquete propietaria de Canonical es indeseable.
- **Arch / openSUSE MicroOS**: MicroOS es excelente y atómico, pero su tooling y ecosistema son menores que Fedora's en escritorio. Arch es rolling release y por diseño no encaja con "distribución estable y firmada".
- **NixOS**: técnicamente superior en reproducibilidad, pero la curva de aprendizaje y el ecosistema de paquetes/aplicaciones de escritorio son barreras serias para usuarios finales.
- **Fedora Kinoite (KDE)**: mismo modelo atómico pero KDE. GNOME tiene mejor integración con accesibilidad (AT-SPI) y portales, ambos críticos para allAI.

## Consecuencias

### Positivas

- **Updates atómicas**: si un upgrade falla, rollback con `rpm-ostree rollback`. Vital para una distro con IA actuando.
- **Integridad**: imagen firmada, contenido inmutable en `/usr`.
- **Reproducibilidad**: el `Containerfile` es la receta exacta de la imagen.
- **Bajo costo de mantenimiento**: heredamos la base de Fedora (CVE patches, kernel, drivers) sin forkear.
- **Ecosistema GNOME**: portales `xdg-desktop-portal` listos, AT-SPI maduro, Wayland.
- **Flatpak por default**: apps del usuario sandboxeadas, ortogonal al sistema.

### Negativas

- **Cambio mental para usuarios** acostumbrados a `dnf install`. Mitigación: documentación clara, instalación por defecto de Toolbox para casos avanzados.
- **Capa del kernel y drivers** atados al ciclo de Fedora (~6 meses).
- **Tooling rpm-ostree** menos maduro que `dnf` para algunos casos esquina (overlays grandes, drivers propietarios).
- **NVIDIA**: drivers propietarios requieren manejo especial (akmods o imagen variant). Universal Blue ya resolvió esto, podemos copiar.

### Neutras

- Hay que aprender la cadena de build de imágenes OCI con `rpm-ostree compose`.

## Plan de implementación

1. Crear `distro/ostree/Containerfile` heredando de `quay.io/fedora-ostree-desktops/silverblue:41`.
2. Capas: instalar paquetes propios + ollama + dependencias del agente + branding + servicios systemd.
3. Build en GitHub Actions con `buildah`/`podman build`.
4. Push a `ghcr.io/allai-os/allai:stable`.
5. Variant futura: `allai:nvidia` con drivers propietarios (fase Assemble).
6. ISO con Anaconda + `livemedia-creator` heredando el toolchain de Universal Blue.

## Revisión

Reevaluar si:

- Fedora cambia su política respecto a Silverblue / imágenes OCI de forma que perjudique al proyecto.
- Surge una alternativa atómica con ventajas decisivas (ej. mejor tooling, comunidad mayor).

Plazo de revisión: anual.

## Referencias

- [Universal Blue](https://universal-blue.org/) — modelo de referencia para imágenes OCI sobre Silverblue
- [Bluefin](https://projectbluefin.io/) — distro construida exactamente con este patrón
- [rpm-ostree docs](https://coreos.github.io/rpm-ostree/)
- ADR-007 (tooling de empaquetado)
