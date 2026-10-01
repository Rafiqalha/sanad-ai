from __future__ import annotations

import pytest

from sanad_core.multimodal import (
    AudioTranscriber,
    ClaimExtractionUnavailableError,
    MediaModality,
    MultimodalSegmentResult,
    SegmentClaimExtractor,
    SegmentTimestamp,
    TranscriptSegment,
    TranscriptionResult,
    TranscriptionUnavailableError,
    UnavailableAudioTranscriber,
    UnavailableSegmentClaimExtractor,
    UnavailableVideoTranscriber,
    VideoTranscriber,
)
from sanad_core.schemas import Domain


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transcriber,source",
    [
        (AudioTranscriber(), b"not decoded"),
        (UnavailableAudioTranscriber(), b"not decoded"),
        (VideoTranscriber(), "fixture.mp4"),
        (UnavailableVideoTranscriber(), "fixture.mp4"),
    ],
)
async def test_unconfigured_transcribers_fail_closed(transcriber, source):
    status = transcriber.capability_status()

    assert transcriber.available is False
    assert status.available is False
    assert status.engine is None
    assert status.reason

    with pytest.raises(TranscriptionUnavailableError, match="no engine"):
        await transcriber.transcribe(source)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extractor", [SegmentClaimExtractor(), UnavailableSegmentClaimExtractor()]
)
async def test_unconfigured_claim_extractor_never_invents_claims(extractor):
    source_segment = TranscriptSegment(
        timestamp=SegmentTimestamp(start_seconds=2.5, end_seconds=4.0),
        transcript="Teks yang benar-benar diberikan oleh engine.",
    )

    assert extractor.available is False
    with pytest.raises(ClaimExtractionUnavailableError, match="no engine"):
        await extractor.extract_claims([source_segment])


def test_segment_result_has_required_future_fields_without_fabricated_evidence():
    result = MultimodalSegmentResult(
        timestamp=SegmentTimestamp(start_seconds=0, end_seconds=3.25),
        transcript="Cuplikan transkrip aktual",
    )

    assert result.timestamp.start_seconds == 0
    assert result.transcript == "Cuplikan transkrip aktual"
    assert result.extracted_claim is None
    assert result.detected_domain == Domain.UNKNOWN
    assert result.evidence == ()
    assert result.source_links == ()


def test_segment_models_reject_empty_transcript_and_invalid_offsets_or_links():
    with pytest.raises(ValueError, match="non-negative"):
        SegmentTimestamp(start_seconds=-0.1)
    with pytest.raises(ValueError, match="must not precede"):
        SegmentTimestamp(start_seconds=5, end_seconds=4)
    with pytest.raises(ValueError, match="engine-produced"):
        TranscriptSegment(
            timestamp=SegmentTimestamp(start_seconds=0),
            transcript="   ",
        )
    with pytest.raises(ValueError, match="absolute HTTP"):
        MultimodalSegmentResult(
            timestamp=SegmentTimestamp(start_seconds=0),
            transcript="Transkrip aktual",
            source_links=("/not-a-public-url",),
        )


def test_transcription_contract_requires_real_engine_identity_and_media_modality():
    segment = TranscriptSegment(
        timestamp=SegmentTimestamp(start_seconds=0),
        transcript="Transkrip aktual",
    )
    result = TranscriptionResult(
        modality=MediaModality.AUDIO,
        engine="local-fixture-engine",
        segments=(segment,),
    )
    assert result.segments == (segment,)

    with pytest.raises(ValueError, match="AUDIO or VIDEO"):
        TranscriptionResult(
            modality=MediaModality.TEXT,
            engine="local-fixture-engine",
            segments=(segment,),
        )
    with pytest.raises(ValueError, match="actual transcription engine"):
        TranscriptionResult(
            modality=MediaModality.AUDIO,
            engine=" ",
            segments=(segment,),
        )
