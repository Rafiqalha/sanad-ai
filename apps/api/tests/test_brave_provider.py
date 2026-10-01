import httpx
import pytest

from sanad_core.config import settings
from sanad_core.providers.brave import (
    BraveDiscoveryProvider,
    classify_sunnah_discovery_url,
)


@pytest.mark.asyncio
async def test_brave_normalizes_results_as_discovery_only(monkeypatch):
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Synthetic result",
                            "url": "https://sunnah.com/testcollection:123",
                            "description": "Synthetic discovery snippet.",
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(settings, "brave_search_api_key", "private-test-key")
    provider = BraveDiscoveryProvider(transport=httpx.MockTransport(handler))
    candidates = await provider.search(["first query", "second query"])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.provider_id == "brave"
    assert candidate.trust_tier == 4
    assert candidate.official_api_validated is False
    assert candidate.retrieval_queries == ["first query", "second query"]


@pytest.mark.asyncio
async def test_brave_redirect_is_not_followed_with_secret_header(monkeypatch):
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://example.com/leak"})

    monkeypatch.setattr(settings, "brave_search_api_key", "private-test-key")
    provider = BraveDiscoveryProvider(transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        await provider.search(["synthetic query"])

    assert len(requests) == 1
    assert requests[0].url.host == "api.search.brave.com"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://sunnah.com/testcollection:123", "CANONICAL_ITEM_PATH"),
        ("https://sunnah.com/search?q=synthetic", "SEARCH_PAGE"),
        ("https://sunnah.com/testcollection", "COLLECTION_OR_BOOK_PAGE"),
        ("https://sunnah.com/testcollection/1", "COLLECTION_OR_BOOK_PAGE"),
        ("https://sunnah.com/testcollection/1/2", "NONCANONICAL_ITEM_PATH"),
        ("https://evil-sunnah.com/testcollection:123", "UNAPPROVED_ORIGIN"),
    ],
)
def test_discovery_url_classification(url, expected):
    assert classify_sunnah_discovery_url(url) == expected


@pytest.mark.asyncio
async def test_brave_filters_navigation_and_noncanonical_pages(monkeypatch):
    urls = [
        "https://sunnah.com/testcollection:123",
        "https://sunnah.com/search?q=synthetic",
        "https://sunnah.com/testcollection",
        "https://sunnah.com/testcollection/1",
        "https://sunnah.com/testcollection/1/2",
        "https://evil-sunnah.com/testcollection:999",
    ]

    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": f"Synthetic result {index}",
                            "url": url,
                            "description": "Synthetic discovery snippet.",
                        }
                        for index, url in enumerate(urls)
                    ]
                }
            },
        )

    monkeypatch.setattr(settings, "brave_search_api_key", "private-test-key")
    provider = BraveDiscoveryProvider(transport=httpx.MockTransport(handler))
    candidates = await provider.search(["synthetic query"])

    assert [candidate.source_url for candidate in candidates] == [urls[0]]
    assert candidates[0].provider_id == "brave"
    assert candidates[0].trust_tier == 4
    assert candidates[0].official_api_validated is False
    assert candidates[0].source_identifier is None
    assert provider.last_filter_counts == {
        "RAW_RESULTS": 6,
        "CANONICAL_ITEM_PATH": 1,
        "SEARCH_PAGE": 1,
        "PROVIDER_HOME": 0,
        "COLLECTION_OR_BOOK_PAGE": 2,
        "NONCANONICAL_ITEM_PATH": 1,
        "UNAPPROVED_ORIGIN": 1,
    }


@pytest.mark.asyncio
async def test_legacy_brave_discovery_caches_duplicate_queries(monkeypatch):
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Synthetic result",
                            "url": "https://sunnah.com/testcollection:123",
                            "description": "Synthetic discovery snippet.",
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(settings, "brave_search_api_key", "private-test-key")
    provider = BraveDiscoveryProvider(transport=httpx.MockTransport(handler))

    first = await provider.search(["same query"])
    assert provider.request_count == 1
    assert provider.cache_misses == 1
    second = await provider.search(["same query"])

    assert calls == 1
    assert [item.source_url for item in first] == [item.source_url for item in second]
    assert provider.request_count == 0
    assert provider.cache_hits == 1
