# Arquitectura de allAI OS

> Documento vivo. Pendiente: diagrama formal y flujos paso a paso (ver [ROADMAP.md](../ROADMAP.md) paso A.4).

## Vista de 10.000 metros

```
┌──────────────────────────────────────────────────────────────┐
│  Usuario (texto, voz, archivo arrastrado, hotkey global)     │
└──────────────────────┬───────────────────────────────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  Overlay UI (GTK4) /        │
        │  GNOME Shell extension /    │
        │  CLI allai-ctl              │
        └──────────────┬──────────────┘
                       │ D-Bus (org.allai.Agent1)
        ┌──────────────▼──────────────┐
        │  allaid (Rust, systemd user)│
        │  - Sesiones                 │
        │  - Kill-switch              │
        │  - Audit log firmado        │
        └──────────────┬──────────────┘
                       │ subprocess + IPC
        ┌──────────────▼──────────────┐
        │  Agent core (Python)        │
        │  ┌────────────────────────┐ │
        │  │ Router híbrido         │ │
        │  └─────┬──────────────┬───┘ │
        │        │              │     │
        │  ┌─────▼─────┐  ┌─────▼───┐ │
        │  │ Claude    │  │ Ollama  │ │
        │  │ Provider  │  │ Provider│ │
        │  └─────┬─────┘  └────┬────┘ │
        │        │              │     │
        │  ┌─────▼──────────────▼───┐ │
        │  │ Tool Executor          │ │
        │  │ (sandbox: bubblewrap)  │ │
        │  └─────┬──────────────────┘ │
        └────────┼─────────────────────┘
                 │
   ┌─────────────┼──────────────┬──────────────┬────────────┐
   ▼             ▼              ▼              ▼            ▼
 mouse/kbd    shell          fs           browser       network
 (libei,      (sandbox)     (capability)  (CDP)         (allowlist)
  ydotool)
```

## Componentes

### Overlay UI

Lanzada por hotkey global (`Super+Space` por defecto). Multimodal: texto, imagen, archivo, voz. Muestra plan de acción y estado en vivo.

### `allaid`

Daemon en Rust que vive como servicio de usuario. Único punto que decide qué se ejecuta. Mantiene el audit log y el kill-switch.

### Agent core

Python. Toda la lógica de proveedores, planificación, herramientas, memoria. Lanzado por `allaid` en una sandbox.

### Provider router

Decide entre Claude API y Ollama (y proveedores futuros) según política del usuario, tipo de tarea, costo, privacidad y disponibilidad de red.

### Tool executor

Cada herramienta tiene un nivel de riesgo y políticas asociadas. Acciones destructivas requieren confirmación humana incluso en modo "trust".

### Sandbox

bubblewrap por defecto. SELinux policy custom. Sin red salvo allowlist. Sin `sudo` salvo polkit.

## Flujos clave (pendiente desarrollar en A.4)

- "Abre Firefox y busca 'allAI OS'"
- "Lee este PDF y resúmemelo"
- "Instala el paquete X"
- "Manda este mensaje por Telegram" (← requiere salvaguardas extras)
- "Conecta a la VPN"
- "Modo presentación: silencia notificaciones por 1 hora"

## Decisiones de diseño relevantes

Ver [ADRs](adr/) cuando estén publicados.

---

Última actualización: 2026-04-28
