# ADR-009: Memoria local cifrada del agente

- **Estado**: Aceptado
- **Fecha**: 2026-05-01
- **Decididores**: Juan Manuel Castellanos (BDFL)

## Contexto

allAI OS es un agente de IA que controla el escritorio Linux del usuario: lee archivos, lanza apps, captura pantalla, escribe texto. Para ser útil a largo plazo el agente necesita **memoria persistente** — recordar preferencias, hechos del usuario, historial de tareas. Pero esa memoria puede contener datos muy sensibles (contraseñas, emails, información personal) y está en la máquina del usuario.

Tensiones principales:

- Utilidad del agente (más contexto = mejores respuestas) vs privacidad del usuario.
- Persistencia entre sesiones vs riesgo de filtración a APIs cloud.
- Búsqueda semántica (embeddings) vs dependencia de servicios remotos.
- Flexibilidad de consulta vs complejidad de la implementación.

## Decisión

La memoria del agente sigue estos principios de diseño:

### 1. Local-only por default

**Toda la memoria vive en la máquina del usuario**, en `~/.local/share/allai/memory/`. No hay sincronización a la nube. No hay backup automático a servicios externos. Si el usuario quiere backups, usa la tool `export` y gestiona él mismo el archivo.

### 2. Cifrado AES-256 con Argon2id

- **SQLCipher** (AES-256-CBC + HMAC-SHA512) cifra toda la base de datos SQLite.
- La **passphrase** del usuario se estira con **Argon2id** (parámetros: 64MB memoria, 3 iteraciones, paralelismo 4) antes de usarse como key.
- La **salt** se almacena en archivo separado con permisos `0600`. Sin la salt no es posible derivar la key correcta.
- El formato de PRAGMA key es hex blob: `PRAGMA key = "x'<32-bytes-hex>'"` (comillas dobles obligatorias para SQLCipher).

### 3. Entradas sensibles marcadas automáticamente

- El módulo `memory.pii` detecta PII (emails, teléfonos, DNI, IBANs, tarjetas, IPs) y marca entradas como `sensitive=True` automáticamente al insertar con `remember`.
- Las entradas `sensitive=True` **no se inyectan en requests cloud** (Claude API, Gemini API) sin confirmación explícita.
- `recall` y `memory.list` excluyen entradas sensibles por default (`include_sensitive=False`).

### 4. Guardia anti-prompt-injection

- Todo contenido que entra por `remember` pasa por `memory.injection_guard` antes de persistir.
- Política: `WRAP` en escritura (envuelve el contenido en un bloque etiquetado), `BLOCK` en alta confianza.
- Los patrones monitorizados: jailbreak clásico, role hijacking, IGNORE PREVIOUS, SYSTEM prompt, exfiltración, inyección de tools, base64 obfuscado, delimitadores falsos, manipulación de confianza.

### 5. Embeddings 100% locales

- Búsqueda semántica con **sentence-transformers**, nunca APIs remotas.
- Auto-selección de modelo según hardware:
  - GPU con compute capability ≥ sm_75 → `BAAI/bge-m3` (~570 MB).
  - CPU o GPU incompatible (ej. NVIDIA 940MX = sm_50) → `paraphrase-multilingual-MiniLM-L12-v2` (~500 MB).
- Si `sentence-transformers` no está instalado, la búsqueda cae back a FTS5 puro (SQLite full-text search).

### 6. Búsqueda híbrida FTS5 + semántica

- `memory.retrieval.retrieve()` primero obtiene candidatos por FTS5 (full-text BM25-like) y luego los re-rankea por similitud coseno con embeddings.
- Si FTS no devuelve resultados, fallback a las `k` entradas más recientes.
- Sin modelo cargado: solo FTS5.

### 7. Audit log append-only con hash-chain

- Toda operación de escritura (insert, delete, rotate_key) queda en `audit.jsonl`.
- Cada entrada lleva HMAC-SHA256 de la entrada anterior (hash-chain), lo que hace detectable cualquier tampering o borrado selectivo.
- El log se puede verificar con `memory.audit.verify()`.

### 8. Memoria de sesión en RAM

- `SessionMemory` mantiene el contexto de la sesión actual en memoria volátil.
- `remember` escribe en ambos sitios: DB cifrada (persistente) y `SessionMemory` (inmediata).
- La sesión se limpia al cerrar el agente; no persiste entre reinicios.

### 9. Interface de comandos en lenguaje natural

- El módulo `memory.commands` parsea instrucciones como "recuerda X", "olvida X", "¿qué sabes sobre Y?", "exporta la memoria", "borra toda la memoria".
- Las tools expuestas al modelo (`recall`, `memory.list`, `remember`, `forget`, `export`, `rotate_key`) tienen niveles de riesgo explícitos: SAFE / CONFIRM / DANGEROUS.

## Alternativas consideradas

- **Sin cifrado (SQLite plano)**: rechazado. Un acceso físico o exploit local expone toda la memoria del agente, incluidos datos personales del usuario.
- **Cifrado con key fija en código**: rechazado. No aporta seguridad real; la key sería visible en el binario o en `strings`.
- **Embeddings remotos (OpenAI, Cohere)**: rechazado de plano. Los textos de la memoria del usuario contienen potencialmente PII y datos sensibles; enviarlos a una API externa viola el principio local-only.
- **Solo búsqueda FTS5 (sin semántica)**: aceptable como fallback, pero inferior en calidad de recuperación. La arquitectura híbrida da lo mejor de ambos mundos.
- **Redis / vector DB externa**: demasiado pesado para un equipo de escritorio. SQLite + FTS5 + embeddings locales cumple los requisitos con una sola dependencia ligera.
- **Memoria cifrada con LUKS (volumen completo)**: delega el cifrado al OS, más transparente, pero requiere privilegios de root y complica el portable backup.

## Consecuencias

### Positivas

- El usuario conserva soberanía total sobre su memoria.
- PII y datos sensibles nunca llegan a APIs cloud por accidente.
- La búsqueda semántica funciona offline completo.
- Un atacante con acceso al archivo `.db` no puede leerlo sin la passphrase.

### Negativas

- La primera carga del modelo de embeddings tarda ~30s y descarga ~500 MB.
- Sin la passphrase el usuario pierde acceso a toda la memoria (no hay recovery key). Se documenta este riesgo en la UI.
- SQLCipher añade ~5-10% overhead de CPU en operaciones de lectura/escritura (aceptable).

### Neutras

- La memoria no se sincroniza entre dispositivos. Si el usuario quiere multi-device, tiene que exportar manualmente.

## Estructura de archivos

```
~/.local/share/allai/memory/
├── memory.db        # SQLCipher AES-256, permisos 0600
├── memory.salt      # Salt Argon2id, permisos 0600
└── audit.jsonl      # Audit log append-only, permisos 0600
```

## Plan de implementación

- [x] L.4.1 — `memory.crypto`: KDF Argon2id, salt, AEAD seal/unseal
- [x] L.4.2 — `memory.permissions`: chmod 0700/0600
- [x] L.4.3 — `memory.store`: SQLCipher open/insert/get/delete/search_fts
- [x] L.4.4 — `memory.audit`: append-only log con hash-chain
- [x] L.4.5 — `memory.pii`: filtro PII, CloudBlockedError
- [x] L.4.6 — `memory.injection_guard`: 9 familias de patrones, BLOCK/WRAP/ALLOW
- [x] L.4.7 — `memory.embeddings`: sentence-transformers local, auto-CPU/GPU
- [x] L.4.8 — `memory.retrieval`: búsqueda híbrida FTS5 + semántica
- [x] L.4.9 — `memory.session`: SessionMemory RAM
- [x] L.4.10 — `memory.commands`: parser "recuerda/olvida/qué sabes"
- [x] L.4.11 — `tools.memory`: recall/list/remember/forget/export/rotate_key

## Referencias

- [ADR-006](0006-modelo-permisos.md) — modelo de permisos y capabilities
- [ADR-008](0008-telemetria.md) — la memoria del agente nunca se envía a telemetría
- [docs/AI_ETHICS.md](../AI_ETHICS.md) — privacidad como default
- [SQLCipher](https://www.zetetic.net/sqlcipher/) — cifrado de SQLite
- [Argon2](https://github.com/P-H-C/phc-winner-argon2) — KDF ganador PHC 2015
- [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) — modelo de embeddings multilingual
