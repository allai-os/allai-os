# ADR-007: Tooling de empaquetado y construcción de imagen

- **Estado**: Aceptado
- **Fecha**: 2026-04-28
- **Decididores**: Juan Manuel Castellanos (BDFL)

## Contexto

ADR-002 ya fija que la base es Fedora Silverblue con imagen OCI tipo Universal Blue. Este ADR detalla **cómo** construimos esa imagen y la ISO instalable, desde el código fuente hasta artefactos firmados.

Componentes a empaquetar:

- Paquetes RPM propios (`allai-agent`, `allai-daemon`, `allai-overlay`, `allai-gnome-extension`, `allai-branding`, `allai-selinux`).
- Imagen OCI base (`ghcr.io/allai-os/allai:stable`).
- Variantes (futuras): `:nvidia`, `:rocm`, `:nightly`.
- ISO instalable (con Anaconda).
- Repositorio OSTree público (deltas para upgrade).

## Decisión

### RPMs propios

- **SPEC files** en `distro/rpms/*.spec` con macros estándar de Fedora.
- Build con **`rpmbuild`** y **`mock`** (entornos limpios reproducibles) en CI.
- Hosting en **Fedora COPR** bajo `copr.fedorainfracloud.org/coprs/allai/stable/` y `coprs/allai/testing/`.
- Firmados con clave GPG del proyecto (rotación documentada).

### Imagen OCI

- **`Containerfile`** en `distro/ostree/` heredando de `quay.io/fedora-ostree-desktops/silverblue:41`.
- Build con **`podman build`** o **`buildah`** en GitHub Actions.
- Push a **GitHub Container Registry** (`ghcr.io/allai-os/allai`).
- Tags: `:stable`, `:testing`, `:nightly-YYYYMMDD`, `:N.M.P` (semver).
- Firmados con **cosign** (Sigstore).
- Verificación con `policy.json` del usuario para que `rpm-ostree` rechace imágenes no firmadas.

### ISO instalable

- **Anaconda + `livemedia-creator`** con kickstart `distro/kickstart/allai-os.ks`.
- El kickstart instala una imagen OSTree específica desde `ghcr.io`.
- Branding de Anaconda custom (logo, idiomas, layout simplificado).
- Build dentro de un container Fedora en CI para ser reproducible.
- Hospedaje de la ISO inicialmente en GitHub Releases (CDN gratuito), evaluación de mirror Cloudflare R2 cuando el tamaño/tráfico lo justifique.

### OSTree repo

- Para deltas eficientes en upgrade, además de la imagen OCI mantenemos un **OSTree repo** en `ostree.allai-os.org` (servido vía Cloudflare).
- Generación con `rpm-ostree compose tree` desde el container.
- Esto es opcional para el usuario: por default `rpm-ostree upgrade` usa la imagen OCI; los usuarios que prefieran ostree-tree puro pueden usar el repo OSTree.

### CI/CD

- **GitHub Actions** como CI primario (gratis para open source, suficiente al inicio).
- Workflows separados:
  - `lint-test.yml` — ruff, mypy, cargo clippy, eslint en cada PR.
  - `build-rpms.yml` — mock build matrix (fedora-41, fedora-rawhide).
  - `build-image.yml` — buildah → ghcr.io.
  - `build-iso.yml` — disparo manual o por release tag.
  - `release.yml` — firma con cosign, GitHub Release con changelog.
- **Reproducible builds**: meta a 1.0; documentamos divergencias hasta que sea factible.

## Alternativas consideradas

- **Koji (build system de Fedora oficial)**: ideal a largo plazo si el proyecto entra a Fedora upstream. Sobredimensionado al inicio.
- **OBS (openSUSE Build Service)**: multi-distro pero curva de aprendizaje y nuestro target es Fedora.
- **CircleCI / GitLab CI**: técnicamente equivalentes a Actions; preferimos Actions por estar donde el repo vive.
- **CDN propio (S3 + CloudFront)**: caro al inicio; GitHub Releases es suficiente hasta ~50GB/mes.
- **Sin firma de imagen**: inaceptable para el threat model.
- **Construir la ISO con `osbuild-composer`**: alternativa moderna a livemedia-creator. La evaluamos en revisión futura; livemedia-creator está más probado en el flujo Silverblue actual.

## Consecuencias

### Positivas

- Stack 100% open source y nativo de Fedora.
- Free CI razonable (Actions) y free hosting (ghcr.io, GitHub Releases) en etapa inicial.
- Firmas con cosign aprovechan transparency log (Rekor) gratis.
- COPR es entorno conocido para usuarios Fedora.

### Negativas

- Mantener kickstart custom requiere actualizar con cada nueva versión de Anaconda.
- ghcr.io tiene rate limits para usuarios anónimos; al crecer migraremos o añadiremos mirror.
- Reproducible builds a 1.0 es ambicioso, posiblemente se atrasa.

### Neutras

- Cosign + Sigstore implica clave OIDC (workload identity); manejar secretos de CI con cuidado.

## Plan de implementación

1. SPEC files iniciales para `allai-agent`, `allai-daemon` (Fase Assemble A.1).
2. Containerfile + workflow de build (Fase Assemble A.2).
3. Kickstart + ISO (Fase Assemble A.3).
4. Workflow de firma con cosign (Fase Ignite I.2).
5. Documentar el proceso en `docs/build.md`.

## Revisión

Reevaluar si:

- GitHub cambia condiciones de Actions/Packages/Releases que no toleremos.
- Aparece tecnología claramente superior (osbuild-composer madura, etc.).
- Necesidades de multi-arch (aarch64) requieren cambio de stack.

Plazo de revisión: anual o ante cambio relevante upstream.

## Referencias

- [Fedora Packaging Guidelines](https://docs.fedoraproject.org/en-US/packaging-guidelines/)
- [Universal Blue Containerfiles](https://github.com/ublue-os/main)
- [cosign / Sigstore](https://www.sigstore.dev/)
- [rpm-ostree compose](https://coreos.github.io/rpm-ostree/compose-server/)
- ADR-002 (base de distro)
