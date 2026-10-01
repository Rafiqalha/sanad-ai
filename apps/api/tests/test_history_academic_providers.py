from __future__ import annotations

import httpx
import pytest

from sanad_core.providers.crossref import CrossrefProvider
from sanad_core.providers.mediawiki import MediaWikiProvider
from sanad_core.providers.openalex import OpenAlexProvider


@pytest.mark.asyncio
async def test_mediawiki_fetches_actual_indonesian_extract_and_reuses_cache():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "id.wikipedia.org"
        if request.url.params.get("list") == "search":
            assert request.url.params["srsearch"] == "siapa Salahuddin Al-Ayyubi?"
            return httpx.Response(
                200,
                json={
                    "query": {
                        "search": [
                            {"pageid": 101, "title": "Salahuddin Ayyubi", "snippet": "x"}
                        ]
                    }
                },
            )
        assert request.url.params["pageids"] == "101"
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "pageid": 101,
                            "title": "Salahuddin Ayyubi",
                            "fullurl": "https://id.wikipedia.org/wiki/Salahuddin_Ayyubi",
                            "extract": (
                                "Salahuddin Ayyubi adalah seorang pemimpin Muslim yang "
                                "mendirikan Dinasti Ayyubiyah."
                            ),
                        }
                    ]
                }
            },
        )

    provider = MediaWikiProvider(
        languages="id,en",
        transport=httpx.MockTransport(handler),
        cache_ttl_seconds=60,
    )
    first = await provider.search("siapa Salahuddin Al-Ayyubi?")
    second = await provider.search("siapa Salahuddin Al-Ayyubi?")

    assert len(requests) == 2
    assert len(first) == len(second) == 1
    assert first[0].title == "Salahuddin Ayyubi"
    assert first[0].language == "id"
    assert first[0].source_class == "ENCYCLOPEDIC"
    assert first[0].canonical_url == (
        "https://id.wikipedia.org/wiki/Salahuddin_Ayyubi"
    )
    assert "mendirikan Dinasti" in first[0].extract
    assert provider.cache_hits == 1
    assert provider.request_count == 0


@pytest.mark.asyncio
async def test_mediawiki_uses_english_only_when_indonesian_has_no_page():
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.host == "id.wikipedia.org":
            return httpx.Response(200, json={"query": {"search": []}})
        if request.url.params.get("list") == "search":
            return httpx.Response(
                200,
                json={"query": {"search": [{"pageid": 202, "title": "Battle of Badr"}]}},
            )
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "pageid": 202,
                            "title": "Battle of Badr",
                            "fullurl": "https://en.wikipedia.org/wiki/Battle_of_Badr",
                            "extract": "The Battle of Badr was an early Muslim battle.",
                        }
                    ]
                }
            },
        )

    result = await MediaWikiProvider(
        languages="id,en",
        transport=httpx.MockTransport(handler),
    ).search("Battle of Badr")

    assert hosts == ["id.wikipedia.org", "en.wikipedia.org", "en.wikipedia.org"]
    assert result[0].language == "en"
    assert result[0].title == "Battle of Badr"


@pytest.mark.asyncio
async def test_openalex_returns_scholarly_metadata_in_keyed_or_keyless_mode():
    secret = "optional-openalex-key"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.params["api_key"] == secret
        assert request.url.params["mailto"] == "riset@example.org"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "display_name": "The Development of Hadith Studies",
                        "publication_year": 2021,
                        "publication_date": "2021-06-12",
                        "type": "article",
                        "doi": "https://doi.org/10.1234/HADITH.1",
                        "authorships": [
                            {"author": {"display_name": "Amina Rahman"}},
                            {"author": {"display_name": "Yusuf Karim"}},
                        ],
                        "primary_location": {
                            "landing_page_url": "https://journal.example.org/hadith-1",
                            "source": {"display_name": "Journal of Hadith Studies"},
                        },
                        "open_access": {
                            "is_oa": True,
                            "oa_status": "gold",
                            "oa_url": "https://journal.example.org/hadith-1",
                        },
                        "abstract_inverted_index": {
                            "Hadith": [0],
                            "studies": [1],
                            "developed": [2],
                            "historically": [3],
                        },
                    }
                ]
            },
        )

    provider = OpenAlexProvider(
        api_key=secret,
        mailto="riset@example.org",
        transport=httpx.MockTransport(handler),
        cache_ttl_seconds=60,
    )
    first = await provider.search("perkembangan ilmu hadis")
    second = await provider.search("perkembangan ilmu hadis")

    assert len(requests) == 1
    assert provider.keyed_mode is True
    assert first == second
    work = first[0]
    assert work.authors == ("Amina Rahman", "Yusuf Karim")
    assert work.year == 2021
    assert work.journal == "Journal of Hadith Studies"
    assert work.doi == "10.1234/hadith.1"
    assert work.canonical_doi_url == "https://doi.org/10.1234/hadith.1"
    assert work.is_open_access is True
    assert work.oa_status == "gold"
    assert work.source_class == "ACADEMIC"
    assert secret not in repr(work)


@pytest.mark.asyncio
async def test_crossref_search_and_exact_doi_validation_use_polite_public_api():
    requests: list[httpx.Request] = []

    item = {
        "title": ["The Development of Hadith Studies"],
        "author": [{"given": "Amina", "family": "Rahman"}],
        "publisher": "Academic Press",
        "container-title": ["Journal of Hadith Studies"],
        "published-online": {"date-parts": [[2021, 6, 12]]},
        "DOI": "10.1234/HADITH.1",
        "URL": "https://doi.org/10.1234/hadith.1",
        "type": "journal-article",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["user-agent"] == "SANAD.AI/0.2"
        assert request.url.params["mailto"] == "riset@example.org"
        if "query.bibliographic" in request.url.params:
            return httpx.Response(200, json={"message": {"items": [item]}})
        return httpx.Response(200, json={"message": item})

    provider = CrossrefProvider(
        mailto="riset@example.org",
        user_agent="SANAD.AI/0.2",
        transport=httpx.MockTransport(handler),
        cache_ttl_seconds=60,
    )
    works = await provider.search("perkembangan ilmu hadis")
    exact = await provider.lookup_doi("https://doi.org/10.1234/HADITH.1")
    repeated = await provider.lookup_doi("10.1234/hadith.1")

    assert len(requests) == 2
    assert works[0].publisher == "Academic Press"
    assert works[0].journal == "Journal of Hadith Studies"
    assert works[0].publication_year == 2021
    assert works[0].publication_date == "2021-06-12"
    assert works[0].authors == ("Amina Rahman",)
    assert exact == repeated
    assert exact is not None
    assert exact.doi == "10.1234/hadith.1"
    assert exact.source_url == "https://doi.org/10.1234/hadith.1"
    assert exact.validation_method == "DOI_LOOKUP"
    assert exact.authority_scope == "BIBLIOGRAPHIC_METADATA_NOT_FULL_TEXT"
