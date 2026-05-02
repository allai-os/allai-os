"""Embeddings locales para memoria semántica.

100% local — nunca llama a APIs remotas. Usa sentence-transformers.

Modelos soportados (en orden de preferencia):
  1. BAAI/bge-m3         — 1024 dim, multilingüe, alta calidad.
                           Requiere GPU compatible (sm_75+) o ~2GB RAM libre en CPU.
  2. paraphrase-multilingual-MiniLM-L12-v2 — 384 dim, multilingüe,
                           ligero, funciona bien en CPU (< 500MB RAM).

El módulo detecta automáticamente si hay GPU compatible con PyTorch.
Si no la hay, usa CPU + modelo ligero para garantizar funcionamiento.
El caller puede forzar modelo/device con EmbeddingsConfig.

Política de privacidad: el texto nunca sale del equipo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


MODEL_BGE_M3 = "BAAI/bge-m3"
MODEL_MULTILINGUAL_MINI = "paraphrase-multilingual-MiniLM-L12-v2"

_DEFAULT_MODEL_GPU = MODEL_BGE_M3
_DEFAULT_MODEL_CPU = MODEL_MULTILINGUAL_MINI


class EmbeddingsError(Exception):
    """Error general del módulo de embeddings."""


class EmbeddingsUnavailableError(EmbeddingsError):
    """`sentence-transformers` no está instalado."""


@dataclass
class EmbeddingsConfig:
    model_name: str | None = None
    """None = selección automática según hardware."""
    device: str | None = None
    """None = detección automática. 'cpu' para forzar CPU."""
    batch_size: int = 32
    normalize: bool = True
    """Normalizar a norma unitaria facilita cosine similarity con dot product."""


def _cuda_is_compatible() -> bool:
    """True si hay GPU CUDA disponible y compatible con PyTorch."""
    try:
        import torch  # type: ignore[import-untyped]
        if not torch.cuda.is_available():
            return False
        # Verificamos que al menos un dispositivo sea compatible
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            cc = props.major * 10 + props.minor  # compute capability × 10
            # PyTorch ≥2.0 requiere sm_37+ (cc≥37); versiones recientes sm_75+
            if cc >= 37:
                return True
        return False
    except Exception:  # noqa: BLE001
        return False


def _select_defaults(cfg: EmbeddingsConfig) -> tuple[str, str]:
    """Devuelve (model_name, device) resolviendo los None del config."""
    if cfg.device is not None:
        device = cfg.device
    else:
        device = "cuda" if _cuda_is_compatible() else "cpu"

    if cfg.model_name is not None:
        model = cfg.model_name
    else:
        model = _DEFAULT_MODEL_GPU if device == "cuda" else _DEFAULT_MODEL_CPU

    return model, device


class EmbeddingsModel:
    """Wrapper sobre SentenceTransformer con config de privacidad."""

    def __init__(self, config: EmbeddingsConfig | None = None) -> None:
        self._cfg = config or EmbeddingsConfig()
        self._model_name, self._device = _select_defaults(self._cfg)
        self._model = None  # lazy load

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
        except ImportError as exc:
            raise EmbeddingsUnavailableError(
                "sentence-transformers no está instalado. "
                "Ejecuta: pip install sentence-transformers"
            ) from exc

        # Silenciamos CUDA para evitar warnings si el device es cpu
        if self._device == "cpu":
            os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

        self._model = SentenceTransformer(
            self._model_name, device=self._device
        )

    def encode(self, texts: list[str]) -> "np.ndarray":
        """Codifica una lista de textos. Devuelve array (N, dim)."""
        if not texts:
            import numpy as np
            return np.empty((0, self.dim), dtype="float32")
        self._load()
        result = self._model.encode(  # type: ignore[union-attr]
            texts,
            batch_size=self._cfg.batch_size,
            normalize_embeddings=self._cfg.normalize,
            show_progress_bar=False,
        )
        return result  # type: ignore[return-value]

    def encode_one(self, text: str) -> "np.ndarray":
        """Codifica un único texto. Devuelve array 1-D (dim,)."""
        return self.encode([text])[0]

    def similarity(self, a: "np.ndarray", b: "np.ndarray") -> float:
        """Cosine similarity entre dos vectores (asume norma unitaria)."""
        import numpy as np
        return float(np.dot(a, b))

    def top_k(
        self,
        query: "np.ndarray",
        corpus: "np.ndarray",
        k: int = 5,
    ) -> list[tuple[int, float]]:
        """Devuelve los `k` índices más similares con su score.

        Args:
            query:  vector 1-D normalizado de la consulta.
            corpus: array (N, dim) normalizado del corpus.
            k:      número de resultados.

        Returns:
            Lista de (índice, score) ordenada por score desc.
        """
        import numpy as np
        if corpus.shape[0] == 0:
            return []
        scores: "np.ndarray" = corpus @ query
        k = min(k, len(scores))
        top_idx = np.argpartition(scores, -k)[-k:]
        top_idx = top_idx[np.argsort(scores[top_idx])[::-1]]
        return [(int(i), float(scores[i])) for i in top_idx]

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def device(self) -> str:
        return self._device

    @property
    def dim(self) -> int:
        """Dimensión del embedding. Requiere que el modelo esté cargado."""
        self._load()
        return self._model.get_sentence_embedding_dimension()  # type: ignore[union-attr]

    def is_available(self) -> bool:
        """True si sentence-transformers está instalado."""
        try:
            import sentence_transformers  # noqa: F401  # type: ignore[import-untyped]
            return True
        except ImportError:
            return False
