"""Safe extension points for future audio and video processing.

SANAD.AI does not currently bundle a speech-to-text engine.  The default
implementations in this module are therefore deliberately unavailable: they
report their capability and raise a typed exception when called.  In
particular, they never turn filenames, metadata, or empty input into a made-up
transcript or claim.

Concrete engines can subclass these interfaces later without changing the
shape of the stored segment result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from os import PathLike
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .schemas import Domain, EvidenceItem


class MediaModality(str, Enum):
    TEXT = "TEXT"
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"


class MultimodalUnavailableError(RuntimeError):
    """Base error for a multimodal operation with no configured engine."""


class TranscriptionUnavailableError(MultimodalUnavailableError):
    """Raised when audio or video transcription is not available."""


class ClaimExtractionUnavailableError(MultimodalUnavailableError):
    """Raised when no segment claim-extraction engine is available."""


@dataclass(frozen=True, slots=True)
class CapabilityStatus:
    """Machine-readable status for an optional local capability."""

    capability: str
    available: bool
    engine: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SegmentTimestamp:
    """Inclusive start and optional exclusive end offset in seconds."""

    start_seconds: float
    end_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.start_seconds < 0:
            raise ValueError("start_seconds must be non-negative")
        if self.end_seconds is not None and self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds must not precede start_seconds")


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """A transcript supplied by a real engine, paired with its media offset."""

    timestamp: SegmentTimestamp
    transcript: str

    def __post_init__(self) -> None:
        if not self.transcript.strip():
            raise ValueError("transcript must contain engine-produced text")


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """Output contract for a configured transcription engine."""

    modality: MediaModality
    engine: str
    segments: tuple[TranscriptSegment, ...]
    language: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.modality not in {MediaModality.AUDIO, MediaModality.VIDEO}:
            raise ValueError("transcription modality must be AUDIO or VIDEO")
        if not self.engine.strip():
            raise ValueError("engine must identify the actual transcription engine")


@dataclass(frozen=True, slots=True)
class MultimodalSegmentResult:
    """Future-proof result shape for one grounded media segment.

    ``evidence`` and ``source_links`` default to empty collections.  Callers
    must explicitly supply evidence returned by the normal SANAD retrieval
    pipeline; this container never creates or promotes evidence by itself.
    """

    timestamp: SegmentTimestamp
    transcript: str
    extracted_claim: str | None = None
    detected_domain: Domain = Domain.UNKNOWN
    evidence: tuple[EvidenceItem, ...] = ()
    source_links: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.transcript.strip():
            raise ValueError("transcript must contain engine-produced text")
        if self.extracted_claim is not None and not self.extracted_claim.strip():
            raise ValueError("extracted_claim must be non-empty when present")
        for link in self.source_links:
            parsed = urlparse(link)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("source_links must contain absolute HTTP(S) URLs")


MediaSource = bytes | bytearray | memoryview | str | PathLike[str]


class AudioTranscriber:
    """Subclassable audio transcription interface.

    The base class is also the safe no-op scaffold used when no engine has
    been configured.
    """

    capability_name = "audio_transcription"
    engine_name: str | None = None

    @property
    def available(self) -> bool:
        return False

    def capability_status(self) -> CapabilityStatus:
        return CapabilityStatus(
            capability=self.capability_name,
            available=False,
            engine=self.engine_name,
            reason="Mesin transkripsi audio belum tersedia.",
        )

    async def transcribe(
        self,
        source: MediaSource,
        *,
        mime_type: str | None = None,
        language_hint: str | None = None,
    ) -> TranscriptionResult:
        del source, mime_type, language_hint
        raise TranscriptionUnavailableError(
            "Audio transcription is unavailable; no engine is configured."
        )


class VideoTranscriber:
    """Subclassable video transcription interface with a fail-closed base."""

    capability_name = "video_transcription"
    engine_name: str | None = None

    @property
    def available(self) -> bool:
        return False

    def capability_status(self) -> CapabilityStatus:
        return CapabilityStatus(
            capability=self.capability_name,
            available=False,
            engine=self.engine_name,
            reason="Mesin transkripsi video belum tersedia.",
        )

    async def transcribe(
        self,
        source: MediaSource,
        *,
        mime_type: str | None = None,
        language_hint: str | None = None,
    ) -> TranscriptionResult:
        del source, mime_type, language_hint
        raise TranscriptionUnavailableError(
            "Video transcription is unavailable; no engine is configured."
        )


class SegmentClaimExtractor:
    """Subclassable interface for extracting claims from real transcripts."""

    capability_name = "segment_claim_extraction"
    engine_name: str | None = None

    @property
    def available(self) -> bool:
        return False

    def capability_status(self) -> CapabilityStatus:
        return CapabilityStatus(
            capability=self.capability_name,
            available=False,
            engine=self.engine_name,
            reason="Mesin ekstraksi klaim per segmen belum tersedia.",
        )

    async def extract_claims(
        self,
        segments: Sequence[TranscriptSegment],
    ) -> tuple[MultimodalSegmentResult, ...]:
        del segments
        raise ClaimExtractionUnavailableError(
            "Segment claim extraction is unavailable; no engine is configured."
        )


class UnavailableAudioTranscriber(AudioTranscriber):
    """Explicit name for dependency injection while audio STT is unavailable."""


class UnavailableVideoTranscriber(VideoTranscriber):
    """Explicit name for dependency injection while video STT is unavailable."""


class UnavailableSegmentClaimExtractor(SegmentClaimExtractor):
    """Explicit name for dependency injection while extraction is unavailable."""


__all__ = [
    "AudioTranscriber",
    "CapabilityStatus",
    "ClaimExtractionUnavailableError",
    "MediaModality",
    "MultimodalSegmentResult",
    "MultimodalUnavailableError",
    "SegmentClaimExtractor",
    "SegmentTimestamp",
    "TranscriptSegment",
    "TranscriptionResult",
    "TranscriptionUnavailableError",
    "UnavailableAudioTranscriber",
    "UnavailableSegmentClaimExtractor",
    "UnavailableVideoTranscriber",
    "VideoTranscriber",
]
