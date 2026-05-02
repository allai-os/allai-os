"""Capa de voz del agente — STT (entrada) y TTS (salida) 100% locales.

Política de privacidad: ningún audio del usuario sale de la máquina. Los
motores soportados son siempre locales (faster-whisper para STT, Piper
para TTS). Cualquier provider remoto requeriría aprobación arquitectónica
explícita.

Submódulos:
  - types:     tipos provider-agnostic (AudioBuffer, Transcript, etc.).
  - provider:  interfaces abstractas STTProvider / TTSProvider.
  - stt_whisper: implementación con faster-whisper — TODO.
  - tts_piper:   implementación con Piper — TODO.
  - wakeword:    detección de "Hey allAI" con openWakeWord — TODO.
  - pipewire:    captura/reproducción vía PipeWire — TODO.
"""

from voice.provider import (
    STTCapabilities,
    STTProvider,
    STTUnavailableError,
    TTSCapabilities,
    TTSProvider,
    TTSUnavailableError,
    UnsupportedLanguageError,
    UnsupportedVoiceError,
    VoiceError,
)
from voice.types import (
    AudioBuffer,
    AudioFormat,
    SynthesisResult,
    SynthesizeRequest,
    TranscribeRequest,
    Transcript,
    TranscriptSegment,
    VoiceInfo,
)

__all__ = [
    "AudioBuffer",
    "AudioFormat",
    "STTCapabilities",
    "STTProvider",
    "STTUnavailableError",
    "SynthesisResult",
    "SynthesizeRequest",
    "TTSCapabilities",
    "TTSProvider",
    "TTSUnavailableError",
    "TranscribeRequest",
    "Transcript",
    "TranscriptSegment",
    "UnsupportedLanguageError",
    "UnsupportedVoiceError",
    "VoiceError",
    "VoiceInfo",
]
