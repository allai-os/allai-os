# ADR-003: Servidor gráfico y mecanismo de automatización de entrada

- **Estado**: Aceptado
- **Fecha**: 2026-04-28
- **Decididores**: Juan Manuel Castellanos (BDFL)

## Contexto

allAI OS necesita simular eventos de input (mouse, teclado) y leer la pantalla (screenshots, posiblemente OCR/UI tree). Esto choca de frente con el modelo de seguridad de **Wayland**, que por diseño aísla las aplicaciones unas de otras: una app no puede ver lo que hacen otras ni inyectar input global.

X11 permite todo esto trivialmente con `xdotool`/`xwininfo`/`scrot`. Wayland no.

Restricciones:

- Fedora Silverblue 41 usa **Wayland** por default (X11 está en sunset).
- El usuario espera el escritorio moderno (mejor seguridad, soporte HiDPI, fractional scaling, mejor energía en laptops).
- El agente debe poder operar el escritorio del usuario de forma confiable.

Tecnologías relevantes:

- **`libei`** (Emulated Input): API moderna para que apps autorizadas inyecten eventos en compositores Wayland.
- **`xdg-desktop-portal-remotedesktop`**: portal estándar que pide consentimiento al usuario para input remoto/grabación de pantalla.
- **PipeWire**: para captura de pantalla y video sin requerir privilegios extras.
- **AT-SPI**: árbol de accesibilidad del escritorio, permite leer estructura de UI sin OCR.
- **`ydotool`**: herramienta que escribe a `/dev/uinput` (kernel-level), bypasea Wayland pero requiere permisos especiales.

## Decisión

allAI OS adoptará **Wayland como servidor gráfico primario**, con la siguiente estrategia de automatización en orden de preferencia:

1. **`libei` + portal `RemoteDesktop`** para input emulado, con consentimiento del usuario por sesión (default).
2. **PipeWire screencast portal** para screenshots y captura de pantalla.
3. **AT-SPI** para inspeccionar el árbol de UI cuando el target lo expone (más confiable y barato que OCR).
4. **CDP (Chrome DevTools Protocol)** para automatización del navegador, vía un Firefox/Chromium con flag de debug local.
5. **Fallback a `ydotool`** sólo si el usuario opta explícitamente (modo "power user", documenta los riesgos).

X11 **no es soportado oficialmente** como entorno primario. La distro entrega sólo sesiones Wayland. Los usuarios que necesiten X11 pueden hacerlo a su propio riesgo desde una sesión secundaria, pero allAI OS no garantiza funcionalidad ahí.

## Alternativas consideradas

- **Volver a X11**: sería la salida fácil, pero condena el proyecto técnicamente. Wayland es el futuro de Linux desktop y va a empeorar la situación si nos atamos a X11.
- **Compositor propio (fork de Mutter)**: técnicamente posible, pero coste de mantenimiento gigantesco. Imposible para un equipo pequeño.
- **Sólo `ydotool` + screenshots root**: funciona pero rompe el modelo de seguridad de Wayland y obliga a permisos peligrosos por defecto.
- **Sólo accesibilidad (AT-SPI)**: insuficiente cuando la app target no expone bien su árbol o cuando hay que actuar sobre lienzo gráfico (Figma web, juegos, etc.).

## Consecuencias

### Positivas

- Modelo de seguridad fuerte: input emulado pasa por consentimiento del compositor.
- Compatibilidad con el desktop moderno (HiDPI, energía, gestos).
- AT-SPI primero significa que muchas tareas no necesitan visión computacional → más rápidas y baratas.
- Alineamiento con la dirección de upstream Fedora/GNOME.

### Negativas

- **`libei` y los portales son relativamente nuevos**: posibles bugs en Mutter/GNOME Shell. Habrá que contribuir aguas arriba cuando los encontremos.
- **Primera ejecución requiere consentimientos**: UX explica claramente por qué.
- **Algunas apps no exponen AT-SPI bien**: requerirán visión + screenshots, más caro.
- **Captura de pantalla por portal puede solicitar consentimiento por sesión**: aceptable, alineado con el principio de soberanía del usuario.

### Neutras

- Tendremos que documentar limitaciones explícitas: "esta app no es operable hoy porque no expone accesibilidad y su lienzo es opaco".

## Plan de implementación

1. Prototipo con `python-libei` + `python-uinput` en Fase A.5.
2. Wrapper en `agent/tools/input/` que abstrae los backends (libei, ydotool fallback).
3. Wrapper de screenshots en `agent/tools/screen/` usando `xdg-desktop-portal-screenshot`.
4. Lector AT-SPI en `agent/tools/ui_tree/` con `pyatspi2`.
5. Driver de browser en `agent/tools/browser/` usando Playwright o CDP directo.
6. Documentar limitaciones por aplicación en `docs/app-compat.md` (trabajo continuo).

## Revisión

Reevaluar si:

- Wayland evoluciona protocolos que cambien el panorama (ya está pasando con `ext-foreign-toplevel`, `image-capture-source`, etc.).
- libei se vuelve insuficiente y necesitamos algo más bajo nivel.

Plazo de revisión: cada 6 meses durante la fase de desarrollo activo.

## Referencias

- [libei project](https://gitlab.freedesktop.org/libinput/libei)
- [xdg-desktop-portal-remotedesktop](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html)
- [AT-SPI2](https://gitlab.gnome.org/GNOME/at-spi2-core)
- ADR-005 (sandboxing) y ADR-006 (permisos)
