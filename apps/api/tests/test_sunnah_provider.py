import httpx
import pytest

from sanad_core.config import settings
from sanad_core.providers.sunnah import SunnahAPIProvider


def _payload(collection="testcollection", number="123"):
    return {
        "collection": collection,
        "hadithNumber": number,
        "bookNumber": "1",
        "chapterId": "1",
        "hadith": [
            {
                "lang": "en",
                "body": "Synthetic fixture body.",
                "urn": 999,
                "grades": [],
            }
        ],
    }


def test_normalize_requires_matching_provider_reference():
    provider = SunnahAPIProvider()
    candidates = provider._normalize(_payload(), "testcollection", "123")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.collection == "testcollection"
    assert candidate.item_number == "123"
    assert candidate.source_identifier == "testcollection:123"
    assert candidate.source_url == "https://sunnah.com/testcollection:123"
    assert candidate.title is None
    assert candidate.official_api_validated is True
    assert candidate.metadata_complete is True
    assert candidate.raw["urn"] == 999


@pytest.mark.parametrize(
    "payload",
    [
        _payload(collection="othercollection"),
        _payload(number="124"),
        {"hadithNumber": "123", "hadith": [{}]},
        {"collection": "testcollection", "hadith": [{}]},
        {"collection": "testcollection", "hadithNumber": "123", "hadith": []},
    ],
)
def test_normalize_fails_closed_on_incoherent_payload(payload):
    with pytest.raises(ValueError):
        SunnahAPIProvider()._normalize(payload, "testcollection", "123")


@pytest.mark.asyncio
async def test_api_redirect_is_not_followed_with_secret_header(monkeypatch):
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://example.com/leak"})

    monkeypatch.setattr(settings, "sunnah_api_key", "private-test-key")
    provider = SunnahAPIProvider(transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        await provider.fetch_by_reference("testcollection", "123")

    assert len(requests) == 1
    assert requests[0].url.host == "api.sunnah.com"


@pytest.mark.parametrize(
    "collection,number",
    [
        ("../other", "123"),
        ("testcollection", "../123"),
        ("test/collection", "123"),
        ("testcollection", "123?other=1"),
        (" ", "123"),
    ],
)
def test_rejects_unsafe_reference_components(collection, number):
    with pytest.raises(ValueError):
        SunnahAPIProvider()._normalize(_payload(), collection, number)
