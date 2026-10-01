import httpx
import pytest
from pydantic import ValidationError

from sanad_core.config import settings
from sanad_core.providers.hadithapi import (
    HadithAPIError,
    HadithAPIProvider,
    HadithAPISearchRequest,
)


def _payload(*, records=None):
    if records is None:
        records = [
            {
                "id": 42,
                "hadithNumber": "123",
                "englishNarrator": "Synthetic narrator",
                "hadithEnglish": "Synthetic English fixture about knowledge.",
                "hadithArabic": "نص تجريبي عن العلم",
                "headingEnglish": "Synthetic heading",
                "chapterId": "7",
                "bookSlug": "sahih-bukhari",
                "volume": "1",
                "status": "Sahih",
                "book": {
                    "bookName": "Synthetic Book",
                    "bookSlug": "sahih-bukhari",
                },
                "chapter": {
                    "id": "7",
                    "chapterNumber": "7",
                    "chapterEnglish": "Synthetic chapter",
                    "chapterArabic": "باب تجريبي",
                },
            }
        ]
    return {
        "status": 200,
        "message": "Hadiths",
        "hadiths": {"current_page": 1, "data": records, "last_page": 1},
    }


@pytest.mark.asyncio
async def test_missing_key_fails_before_transport(monkeypatch):
    called = False

    def handler(request: httpx.Request):
        nonlocal called
        called = True
        return httpx.Response(200, json=_payload())

    monkeypatch.setattr(settings, "hadith_api_key", None)
    provider = HadithAPIProvider(transport=httpx.MockTransport(handler))

    with pytest.raises(HadithAPIError, match="not configured"):
        await provider.search(HadithAPISearchRequest(hadith_english="knowledge"))

    assert called is False


@pytest.mark.asyncio
async def test_all_documented_filters_are_sent_and_metadata_is_normalized(monkeypatch):
    captured = []

    def handler(request: httpx.Request):
        captured.append(request)
        return httpx.Response(200, json=_payload())

    monkeypatch.setattr(settings, "hadith_api_key", "private-test-key")
    provider = HadithAPIProvider(transport=httpx.MockTransport(handler))
    request = HadithAPISearchRequest(
        hadith_english="seeking knowledge",
        hadith_arabic="طلب العلم",
        hadith_number="123",
        book="sahih-bukhari",
        chapter="7",
        status="sahih",
        paginate=20,
    )

    candidates = await provider.search(request)

    assert len(captured) == 1
    assert str(captured[0].url).startswith(
        "https://www.hadithapi.com/public/api/hadiths?"
    )
    params = captured[0].url.params
    assert params["apiKey"] == "private-test-key"
    assert params["hadithEnglish"] == "seeking knowledge"
    assert params["hadithArabic"] == "طلب العلم"
    assert params["hadithNumber"] == "123"
    assert params["book"] == "sahih-bukhari"
    assert params["chapter"] == "7"
    assert params["status"] == "Sahih"
    assert params["paginate"] == "20"

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.provider_id == "hadithapi"
    assert candidate.trust_tier == 2
    assert candidate.collection == "sahih-bukhari"
    assert candidate.item_number == "123"
    assert candidate.source_identifier == "hadithapi:sahih-bukhari:123"
    assert candidate.retrieved_texts == {
        "en": "Synthetic English fixture about knowledge.",
        "ar": "نص تجريبي عن العلم",
    }
    assert candidate.provider_api_validated is True
    assert candidate.official_api_validated is False
    assert candidate.source_url == "https://www.hadithapi.com/public/api/hadiths"
    assert "apiKey" not in candidate.source_url
    assert "private-test-key" not in str(candidate.raw)


@pytest.mark.asyncio
async def test_empty_paginated_result_returns_no_candidates(monkeypatch):
    monkeypatch.setattr(settings, "hadith_api_key", "private-test-key")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=_payload(records=[]))
    )
    provider = HadithAPIProvider(transport=transport)

    result = await provider.search(
        HadithAPISearchRequest(hadith_arabic="طلب العلم")
    )

    assert result == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [302, 401, 403, 429, 500])
async def test_http_errors_are_sanitized_and_redirects_not_followed(
    monkeypatch, status_code
):
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        headers = {"Location": "https://example.com/leak"} if status_code == 302 else {}
        return httpx.Response(status_code, headers=headers)

    secret = "private-test-key"
    monkeypatch.setattr(settings, "hadith_api_key", secret)
    provider = HadithAPIProvider(transport=httpx.MockTransport(handler))

    with pytest.raises(HadithAPIError) as exc_info:
        await provider.search(HadithAPISearchRequest(hadith_english="knowledge"))

    assert str(status_code) in str(exc_info.value)
    assert secret not in str(exc_info.value)
    assert "apiKey" not in str(exc_info.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_malformed_payload_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "hadith_api_key", "private-test-key")
    provider = HadithAPIProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": 200})
        )
    )

    with pytest.raises(HadithAPIError, match="missing"):
        await provider.search(HadithAPISearchRequest(hadith_english="knowledge"))


@pytest.mark.asyncio
async def test_unusable_or_undocumented_record_is_not_promoted(monkeypatch):
    records = [
        {"bookSlug": "unknown-book", "hadithNumber": "1", "hadithEnglish": "x"},
        {"bookSlug": "sahih-bukhari", "hadithEnglish": "missing number"},
        {"bookSlug": "sahih-bukhari", "hadithNumber": "2"},
    ]
    monkeypatch.setattr(settings, "hadith_api_key", "private-test-key")
    provider = HadithAPIProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_payload(records=records))
        )
    )

    result = await provider.search(
        HadithAPISearchRequest(hadith_english="knowledge")
    )

    assert result == []


@pytest.mark.asyncio
async def test_conflicting_book_metadata_fails_closed(monkeypatch):
    record = _payload()["hadiths"]["data"][0]
    record["book"] = {
        "bookName": "Conflicting Synthetic Book",
        "bookSlug": "sahih-muslim",
    }
    monkeypatch.setattr(settings, "hadith_api_key", "private-test-key")
    provider = HadithAPIProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_payload(records=[record]))
        )
    )

    result = await provider.search(
        HadithAPISearchRequest(hadith_english="knowledge")
    )

    assert result == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"book": "invented-book"},
        {"status": "unknown"},
        {"hadith_number": "1/2"},
        {"chapter": "../1"},
        {"hadith_english": "x", "paginate": 201},
    ],
)
def test_invalid_filters_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        HadithAPISearchRequest(**kwargs)
