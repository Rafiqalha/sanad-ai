from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from sanad_core.history_pipeline import (
    IslamicHistoryPipeline,
    ProvenanceSource,
    _merge_duplicate_sources,
    _source_query_fit,
)
from sanad_core.providers.crossref import CrossrefProvider
from sanad_core.providers.mediawiki import MediaWikiArticle, MediaWikiProvider
from sanad_core.providers.openalex import OpenAlexProvider


def _wiki_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("list") == "search":
            return httpx.Response(
                200,
                json={
                    "query": {
                        "search": [
                            {"pageid": 90, "title": "Ilmu hadis"}
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "pageid": 90,
                            "title": "Ilmu hadis",
                            "fullurl": "https://id.wikipedia.org/wiki/Ilmu_hadis",
                            "extract": (
                                "Ilmu hadis mempelajari periwayatan dan perkembangan "
                                "kajian hadis dalam sejarah Islam."
                            ),
                        }
                    ]
                }
            },
        )

    return httpx.MockTransport(handler)


def _openalex_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W55",
                        "display_name": "The Development of Hadith Studies",
                        "publication_year": 2020,
                        "publication_date": "2020-03-01",
                        "type": "article",
                        "doi": "https://doi.org/10.5555/HADITH",
                        "authorships": [
                            {"author": {"display_name": "Fatimah Hasan"}}
                        ],
                        "primary_location": {
                            "landing_page_url": "https://journal.example.org/article",
                            "source": {"display_name": "Islamic Studies Review"},
                        },
                        "open_access": {"is_oa": False, "oa_status": "closed"},
                        "abstract_inverted_index": {
                            "Historical": [0],
                            "development": [1],
                            "of": [2],
                            "hadith": [3],
                            "studies": [4],
                        },
                    }
                ]
            },
        )

    return httpx.MockTransport(handler)


def _crossref_transport(requests: list[httpx.Request]) -> httpx.MockTransport:
    item = {
        "title": ["The Development of Hadith Studies"],
        "author": [{"given": "Fatimah", "family": "Hasan"}],
        "publisher": "Scholarly House",
        "container-title": ["Islamic Studies Review"],
        "published-online": {"date-parts": [[2020, 3, 1]]},
        "DOI": "10.5555/HADITH",
        "URL": "https://doi.org/10.5555/hadith",
        "type": "journal-article",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "query.bibliographic" in request.url.params:
            return httpx.Response(200, json={"message": {"items": [item]}})
        return httpx.Response(200, json={"message": item})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_pipeline_merges_openalex_with_crossref_doi_validation_and_ranks():
    crossref_requests: list[httpx.Request] = []
    pipeline = IslamicHistoryPipeline(
        mediawiki=MediaWikiProvider(transport=_wiki_transport()),
        openalex=OpenAlexProvider(transport=_openalex_transport()),
        crossref=CrossrefProvider(
            transport=_crossref_transport(crossref_requests),
            mailto="riset@example.org",
        ),
        enable_broad_web=False,
    )

    result = await pipeline.retrieve(
        "ada penelitian akademik tentang perkembangan ilmu hadis?"
    )

    assert len(crossref_requests) == 2  # search plus exact DOI validation
    assert result.provider_counts == {
        "wikipedia": 1,
        "openalex": 1,
        "crossref": 1,
        "broad_web": 0,
    }
    assert len(result.sources) == 2
    academic = next(item for item in result.sources if item.doi)
    assert academic.provider_ids == ("openalex", "crossref")
    assert academic.provider == "OpenAlex + Crossref"
    assert academic.publisher == "Scholarly House"
    assert academic.journal == "Islamic Studies Review"
    assert academic.source_url == "https://doi.org/10.5555/hadith"
    assert academic.link_state == "VERIFIED_PROVIDER"
    assert academic.metadata["crossref_doi_validated"] is True
    assert academic.metadata["crossref_title_validation"] == "MATCH"
    assert academic.authority_scope == (
        "SCHOLARLY_DISCOVERY_AND_METADATA_NOT_RELIGIOUS_AUTHORITY"
    )
    assert result.academic_sources == (academic,)
    assert result.encyclopedic_sources[0].source_class == "ENCYCLOPEDIC"
    assert result.failure_message is None


class _EmptyProvider:
    provider_id = "empty"
    last_errors: list[str] = []

    async def search(self, query: str, *, limit: int):
        return []


class _EmptyCrossref(_EmptyProvider):
    async def lookup_doi(self, doi: str):
        return None


@pytest.mark.asyncio
async def test_pipeline_returns_honest_no_source_message_without_fabrication():
    result = await IslamicHistoryPipeline(
        mediawiki=_EmptyProvider(),
        openalex=_EmptyProvider(),
        crossref=_EmptyCrossref(),
        enable_broad_web=False,
    ).retrieve("kutipan agama yang sepenuhnya dibuat-buat")

    assert result.sources == ()
    assert result.failure_message == (
        "Sumber pernyataan ini belum diketahui atau belum dapat diverifikasi "
        "dari sumber yang berhasil ditelusuri."
    )


@dataclass
class _Hit:
    source_url: str
    page_title: str
    snippet: str
    rank: int = 1


class _BroadProvider:
    async def search(self, queries, *, max_requests):
        assert max_requests <= 2
        return SimpleNamespace(
            hits=[
                _Hit(
                    source_url="https://library.example.edu/badr",
                    page_title="The Battle of Badr",
                    snippet="Search snippet must not become evidence.",
                )
            ],
            errors=[],
        )


class _PageRetriever:
    async def fetch(self, hit, *, relevance_queries):
        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            result=SimpleNamespace(
                page_title="The Battle of Badr: Historical Sources",
                source_url=hit.source_url,
                resolved_url="https://library.example.edu/collections/badr",
                content_excerpt=(
                    "A university library essay surveys historical sources for "
                    "the Battle of Badr and identifies its manuscript catalogue."
                ),
                link_validated_at=now,
                retrieved_at=now,
                author="Library Research Team",
                publisher="Example University Library",
                institution="Example University Library",
                publication_date="2024-01-01",
                retrieval_queries=relevance_queries,
                link_provider="brave_web_discovery",
                source_class="INSTITUTIONAL",
                http_status=200,
                source_domain="library.example.edu",
            ),
            error=None,
        )


@pytest.mark.asyncio
async def test_pipeline_includes_only_fetched_broad_page_not_search_snippet():
    result = await IslamicHistoryPipeline(
        mediawiki=_EmptyProvider(),
        openalex=_EmptyProvider(),
        crossref=_EmptyCrossref(),
        broad_web_provider=_BroadProvider(),
        page_retriever=_PageRetriever(),
        enable_broad_web=True,
    ).retrieve("bagaimana sejarah Perang Badar?")

    assert len(result.sources) == 1
    source = result.sources[0]
    assert source.link_state == "DISCOVERY_ONLY"
    assert source.source_class == "INSTITUTIONAL"
    assert source.resolved_url == "https://library.example.edu/collections/badr"
    assert "university library essay" in (source.content or "")
    assert "Search snippet" not in (source.content or "")
    assert source.authority_scope == "WEB_DISCOVERY_NOT_RELIGIOUS_AUTHORITY"
    assert result.broad_web_sources == (source,)
    assert result.institutional_sources == ()


def test_discovery_body_never_inherits_structured_provider_validation():
    now = datetime.now(timezone.utc)
    provider = ProvenanceSource(
        title="Metadata kajian hadis",
        provider_ids=("openalex",),
        provider="OpenAlex",
        source_class="ACADEMIC",
        source_url="https://journal.example.org/item",
        resolved_url="https://journal.example.org/item",
        link_state="VERIFIED_PROVIDER",
        validation_timestamp=now,
        summary="Structured abstract supplied through scholarly metadata.",
    )
    discovery_body = "Fetched Brave page body. " * 80
    discovery = ProvenanceSource(
        title="Metadata kajian hadis",
        provider_ids=("brave_web_discovery",),
        provider="Brave Search + fetched page",
        source_class="ACADEMIC",
        source_url="https://journal.example.org/item",
        resolved_url="https://journal.example.org/item",
        link_state="DISCOVERY_ONLY",
        validation_timestamp=now,
        summary=discovery_body,
        content=discovery_body,
    )

    merged = _merge_duplicate_sources([provider, discovery])

    assert len(merged) == 2
    structured = next(item for item in merged if item.link_state == "VERIFIED_PROVIDER")
    web = next(item for item in merged if item.link_state == "DISCOVERY_ONLY")
    assert structured.summary == "Structured abstract supplied through scholarly metadata."
    assert discovery_body not in (structured.content or "")
    assert web.content == discovery_body


class _IrrelevantWiki:
    provider_id = "wikipedia"
    last_errors: list[str] = []
    request_count = 1
    cache_hits = 0
    cache_misses = 1

    async def search(self, query: str, *, limit: int):
        return [
            MediaWikiArticle(
                title="Quantum mechanics",
                language="en",
                canonical_url="https://en.wikipedia.org/wiki/Quantum_mechanics",
                extract="A physics article about particles, waves, and measurement.",
                page_id=1,
                retrieved_at=datetime.now(timezone.utc),
            )
        ]


@pytest.mark.asyncio
async def test_structured_history_candidate_must_be_relevant_before_provenance_bonus():
    result = await IslamicHistoryPipeline(
        mediawiki=_IrrelevantWiki(),
        openalex=_EmptyProvider(),
        crossref=_EmptyCrossref(),
        enable_broad_web=False,
    ).retrieve("bagaimana sejarah Perang Badar?")

    assert result.sources == ()
    assert result.failure_message is not None


def test_history_relevance_requires_distinctive_entity_not_generic_war_words():
    now = datetime.now(timezone.utc)
    unrelated = ProvenanceSource(
        title="Perang Dunia II: Strategi Perang Darat",
        provider_ids=("crossref",),
        provider="Crossref",
        source_class="ACADEMIC",
        source_url="https://doi.org/10.1234/example",
        resolved_url="https://doi.org/10.1234/example",
        link_state="VERIFIED_PROVIDER",
        validation_timestamp=now,
    )
    transliteration_variant = ProvenanceSource(
        title="The Battle of Badr: Historical Sources",
        provider_ids=("openalex",),
        provider="OpenAlex",
        source_class="ACADEMIC",
        source_url="https://openalex.org/W1",
        resolved_url="https://openalex.org/W1",
        link_state="VERIFIED_PROVIDER",
        validation_timestamp=now,
    )

    queries = ["bagaimana sejarah Perang Badar?"]
    assert _source_query_fit(unrelated, queries) < 0.08
    assert _source_query_fit(transliteration_variant, queries) >= 0.08


def test_academic_relevance_requires_the_user_topic_not_generic_research_terms():
    now = datetime.now(timezone.utc)
    unrelated = ProvenanceSource(
        title="Global incidence and healthy life expectancy",
        provider_ids=("openalex",),
        provider="OpenAlex",
        source_class="ACADEMIC",
        source_url="https://openalex.org/W-health",
        resolved_url="https://openalex.org/W-health",
        link_state="VERIFIED_PROVIDER",
        validation_timestamp=now,
        summary="A research study about global health development and knowledge.",
    )
    relevant = ProvenanceSource(
        title="Hadith Studies in the Indonesian Context",
        provider_ids=("crossref",),
        provider="Crossref",
        source_class="ACADEMIC",
        source_url="https://doi.org/10.1234/hadith",
        resolved_url="https://doi.org/10.1234/hadith",
        link_state="VERIFIED_PROVIDER",
        validation_timestamp=now,
    )
    queries = [
        "ada penelitian akademik tentang perkembangan ilmu hadis?",
        "Islamic studies research academic development knowledge hadith",
    ]

    assert _source_query_fit(unrelated, queries) == 0.0
    assert _source_query_fit(relevant, queries) >= 0.08
