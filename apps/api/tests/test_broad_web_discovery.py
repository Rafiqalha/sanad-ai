from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from sanad_core.config import settings
from sanad_core.orchestrator import SanadOrchestrator
from sanad_core.providers.broad_web import (
    AsyncTTLCache,
    BroadWebDiscoveryProvider,
    WebPageRetriever,
    WebSearchHit,
    classify_source,
)
from sanad_core.schemas import (
    CacheState,
    Candidate,
    Domain,
    EvidenceRelation,
    FinalStatus,
    IntentAnalysis,
    LinkState,
    LinkValidation,
    QueryBundle,
    RankingFeatures,
    ReconstructedClaim,
    RoutingMethod,
    SourceClass,
    WebSourceResult,
)
from sanad_core.web_retrieval import WebDiscoveryPipeline


def _article_html(
    *,
    title: str = "Hadis tentang amal dan niat",
    publisher: str = "Lembaga Kajian Islam",
    body: str | None = None,
) -> str:
    article = body or (
        "Hadis tentang amal dan niat menerangkan hubungan perbuatan dengan "
        "niat. Artikel ini menelusuri sumber riwayat, nomor hadis, dan konteks "
        "ungkapan bahwa amal bergantung pada niat agar pembaca dapat memeriksa "
        "rujukan primernya secara langsung."
    )
    return f"""<!doctype html>
    <html lang="id">
      <head>
        <title>{title}</title>
        <meta property="og:title" content="{title}">
        <meta property="og:site_name" content="{publisher}">
        <meta name="author" content="Peneliti Contoh">
        <meta property="article:published_time" content="2026-09-20">
      </head>
      <body>
        <nav>Isi navigasi harus diabaikan.</nav>
        <main><h1>{title}</h1><p>{article}</p></main>
        <script>privateValue = 'harus diabaikan';</script>
      </body>
    </html>"""


@pytest.mark.asyncio
async def test_broad_search_deduplicates_caps_at_two_and_reuses_cache(monkeypatch):
    secret = "brave-secret-must-not-be-serialized"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        query = request.url.params["q"]
        slug = "niat" if "niat" in query.casefold() else "amal"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": f"Sumber {slug}",
                            "url": f"https://example.org/{slug}",
                            "description": f"Hasil penelusuran {query}",
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(settings, "brave_search_api_key", secret)
    monkeypatch.setattr(settings, "sanad_max_brave_requests", 2)
    provider = BroadWebDiscoveryProvider(
        transport=httpx.MockTransport(handler),
        cache=AsyncTTLCache(ttl_seconds=60),
    )
    queries = [
        "hadis tentang niat",
        "  HADIS   TENTANG NIAT  ",
        "actions depend on intentions",
        "third query must not be requested",
    ]

    first = await provider.search(queries, max_requests=3)
    second = await provider.search(queries, max_requests=3)

    assert len(requests) == 2
    assert {request.url.params["q"] for request in requests} == {
        "hadis tentang niat",
        "actions depend on intentions",
    }
    assert all(request.headers["x-subscription-token"] == secret for request in requests)
    assert first.brave_request_count == 2
    assert first.cache_misses == 2
    assert first.cache_hits == 0
    assert second.brave_request_count == 0
    assert second.cache_misses == 0
    assert second.cache_hits == 2
    assert len(first.hits) == len(second.hits) == 2
    assert secret not in repr(first)
    assert secret not in repr(second)


@pytest.mark.asyncio
async def test_page_retriever_resolves_redirect_extracts_metadata_and_classifies_source():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url == httpx.URL("https://discovery.example/start"):
            return httpx.Response(
                302,
                headers={"Location": "https://artikel.kemenag.go.id/kajian/niat"},
            )
        assert request.url == httpx.URL("https://artikel.kemenag.go.id/kajian/niat")
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=_article_html(publisher="Kementerian Agama RI"),
        )

    retriever = WebPageRetriever(transport=httpx.MockTransport(handler))
    outcome = await retriever.fetch(
        WebSearchHit(
            source_url="https://discovery.example/start",
            page_title="Cuplikan hasil pencarian",
            snippet="Hadis amal dan niat",
            retrieval_queries=["amal tergantung niat hadis"],
            rank=1,
        ),
        relevance_queries=["amal tergantung niat hadis"],
    )

    assert outcome.error is None
    assert outcome.cache_hit is False
    assert outcome.result is not None
    result = outcome.result
    assert [str(request.url) for request in requests] == [
        "https://discovery.example/start",
        "https://artikel.kemenag.go.id/kajian/niat",
    ]
    assert result.source_url == "https://discovery.example/start"
    assert result.resolved_url == "https://artikel.kemenag.go.id/kajian/niat"
    assert result.source_domain == "artikel.kemenag.go.id"
    assert result.page_title == "Hadis tentang amal dan niat"
    assert result.publisher == "Kementerian Agama RI"
    assert result.institution == "Kementerian Agama RI"
    assert result.author == "Peneliti Contoh"
    assert result.publication_date == "2026-09-20"
    assert result.source_class == SourceClass.OFFICIAL_GOVERNMENT
    assert result.http_status == 200
    assert result.relevance_score >= 0.20
    assert "Isi navigasi" not in (result.content_excerpt or "")
    assert "privateValue" not in (result.content_excerpt or "")
    assert result.evidence_state == LinkState.DISCOVERY_ONLY
    assert result.link_state == LinkState.DISCOVERY_ONLY


@pytest.mark.parametrize(
    ("domain", "metadata", "expected"),
    [
        ("kemenag.go.id", {}, SourceClass.OFFICIAL_GOVERNMENT),
        ("sunnah.com", {}, SourceClass.PRIMARY_RELIGIOUS_SOURCE),
        ("journal.ac.id", {}, SourceClass.ACADEMIC),
        ("uici.ac.id", {}, SourceClass.INSTITUTIONAL),
        ("institute.org", {}, SourceClass.INSTITUTIONAL),
        ("media.example", {"og:site_name": "Media"}, SourceClass.PUBLISHER),
        ("example.com", {}, SourceClass.GENERAL_WEB),
        ("reddit.com", {}, SourceClass.COMMUNITY),
        ("", {}, SourceClass.UNKNOWN),
    ],
)
def test_provenance_classification_is_explicit_and_not_a_truth_score(
    domain, metadata, expected
):
    assert classify_source(domain, metadata) == expected


def test_provider_hadith_gets_only_exact_fetched_primary_public_link():
    candidate = Candidate(
        candidate_id="hadithapi-1",
        provider_id="hadithapi",
        provider_name="HadithAPI",
        source_type="hadith_curated_secondary",
        collection="sahih-bukhari",
        item_number="1",
        source_url="https://www.hadithapi.com/public/api/hadiths",
        provider_api_validated=True,
        raw={"book_name": "Sahih al-Bukhari"},
    )
    now = datetime.now(timezone.utc)
    exact_page = WebSourceResult(
        source_url="https://sunnah.com/bukhari:1",
        resolved_url="https://sunnah.com/bukhari:1",
        source_domain="sunnah.com",
        page_title="Sahih al-Bukhari 1",
        source_class=SourceClass.PRIMARY_RELIGIOUS_SOURCE,
        content_excerpt="Sahih al-Bukhari, Hadith 1. Actions are by intentions.",
        link_state=LinkState.DISCOVERY_ONLY,
        evidence_state=LinkState.DISCOVERY_ONLY,
        http_status=200,
        link_validated_at=now,
    )

    SanadOrchestrator._attach_matching_public_sources(
        [SimpleNamespace(candidate=candidate)],
        [exact_page],
    )

    assert candidate.raw["public_source_url"] == "https://sunnah.com/bukhari:1"
    assert candidate.raw["public_source_link_state"] == "DISCOVERY_ONLY"
    assert candidate.provider_api_validated is True
    assert candidate.official_api_validated is False


def test_provider_hadith_rejects_wrong_reference_or_nonprimary_page():
    candidate = Candidate(
        candidate_id="hadithapi-2",
        provider_id="hadithapi",
        provider_name="HadithAPI",
        source_type="hadith_curated_secondary",
        collection="sahih-bukhari",
        item_number="1",
        source_url="https://www.hadithapi.com/public/api/hadiths",
        provider_api_validated=True,
        raw={"book_name": "Sahih al-Bukhari"},
    )
    now = datetime.now(timezone.utc)
    wrong = WebSourceResult(
        source_url="https://sunnah.com/bukhari:2",
        resolved_url="https://sunnah.com/bukhari:2",
        source_domain="sunnah.com",
        page_title="Sahih al-Bukhari 2",
        source_class=SourceClass.PRIMARY_RELIGIOUS_SOURCE,
        content_excerpt="Sahih al-Bukhari, Hadith 2.",
        link_state=LinkState.DISCOVERY_ONLY,
        evidence_state=LinkState.DISCOVERY_ONLY,
        http_status=200,
        link_validated_at=now,
    )
    nonprimary = wrong.model_copy(
        update={
            "resolved_url": "https://blog.example.org/bukhari-1",
            "source_url": "https://blog.example.org/bukhari-1",
            "source_domain": "blog.example.org",
            "page_title": "Sahih al-Bukhari 1",
            "content_excerpt": "Sahih al-Bukhari, Hadith 1.",
            "source_class": SourceClass.GENERAL_WEB,
        }
    )

    SanadOrchestrator._attach_matching_public_sources(
        [SimpleNamespace(candidate=candidate)],
        [wrong, nonprimary],
    )

    assert "public_source_url" not in candidate.raw


@pytest.mark.asyncio
async def test_page_retriever_rejects_live_but_irrelevant_content():
    irrelevant_body = (
        "Panduan perawatan mesin turbin membahas pelumas, bantalan, getaran, "
        "tekanan hidraulik, dan jadwal inspeksi industri. Dokumen teknis ini "
        "berisi prosedur kalibrasi alat serta daftar komponen mekanis cadangan."
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=_article_html(
                title="Manual turbin industri",
                publisher="Penerbit Teknik",
                body=irrelevant_body,
            ),
        )

    outcome = await WebPageRetriever(
        transport=httpx.MockTransport(handler)
    ).fetch(
        WebSearchHit(
            source_url="https://example.org/manual-turbin",
            page_title="Manual turbin",
            snippet="Dokumen mesin",
        ),
        relevance_queries=["amal tergantung niat hadis"],
    )

    assert outcome.result is None
    assert outcome.error == "Web page content was not relevant to the query."


@pytest.mark.asyncio
async def test_cached_page_is_rescored_and_rejected_for_unrelated_query():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=_article_html(),
        )

    retriever = WebPageRetriever(transport=httpx.MockTransport(handler))
    hit = WebSearchHit(
        source_url="https://example.org/hadis-niat",
        page_title="Hadis niat",
        snippet="Amal tergantung niat",
        retrieval_queries=["amal tergantung niat hadis"],
    )

    first = await retriever.fetch(
        hit,
        relevance_queries=["amal tergantung niat hadis"],
    )
    unrelated = await retriever.fetch(
        hit,
        relevance_queries=["quantum semiconductor lattice mechanics"],
    )

    assert first.result is not None
    assert unrelated.result is None
    assert unrelated.cache_hit is True
    assert unrelated.error == "Cached web page content was not relevant to the query."
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://example.org/article",
        "https://localhost/article",
        "https://localhost.localdomain/article",
        "https://127.0.0.1/article",
        "https://10.0.0.1/article",
        "https://[::1]/article",
        "https://example.org:444/article",
        "https://user:password@example.org/article",
    ],
)
async def test_page_retriever_blocks_non_https_local_and_nonstandard_port_ssrf(
    unsafe_url,
):
    requests: list[httpx.Request] = []

    def should_not_run(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    outcome = await WebPageRetriever(
        transport=httpx.MockTransport(should_not_run)
    ).fetch(
        WebSearchHit(
            source_url=unsafe_url,
            page_title="Unsafe",
            snippet=None,
        ),
        relevance_queries=["hadis niat"],
    )

    assert outcome.result is None
    assert outcome.error == "Web page validation failed: ValueError."
    assert requests == []


@pytest.mark.asyncio
async def test_page_retriever_revalidates_each_redirect_against_ssrf():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://127.0.0.1/private"})

    outcome = await WebPageRetriever(
        transport=httpx.MockTransport(handler)
    ).fetch(
        WebSearchHit(
            source_url="https://example.org/start",
            page_title="Start",
            snippet=None,
        ),
        relevance_queries=["hadis niat"],
    )

    assert outcome.result is None
    assert outcome.error == "Web page validation failed: ValueError."
    assert [str(request.url) for request in requests] == ["https://example.org/start"]


@pytest.mark.asyncio
async def test_pipeline_fetches_relevant_pages_and_never_promotes_discovery(monkeypatch):
    search_requests: list[httpx.Request] = []
    page_requests: list[httpx.Request] = []

    def search_handler(request: httpx.Request) -> httpx.Response:
        search_requests.append(request)
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Kajian hadis niat",
                            "url": "https://journal.example.org/hadis-niat",
                            "description": "Kajian amal tergantung niat",
                        },
                        {
                            "title": "Manual turbin",
                            "url": "https://manual.example.org/turbin",
                            "description": "Dokumen mesin",
                        },
                    ]
                }
            },
        )

    def page_handler(request: httpx.Request) -> httpx.Response:
        page_requests.append(request)
        if request.url.host == "journal.example.org":
            body = _article_html(publisher="Jurnal Kajian Islam")
        else:
            body = _article_html(
                title="Manual turbin industri",
                body=(
                    "Dokumen pemeliharaan turbin menjelaskan bantalan mesin, "
                    "pelumas, suhu operasi, rotasi poros, tekanan, dan inspeksi "
                    "teknis berkala untuk fasilitas industri pembangkit listrik."
                ),
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=body,
        )

    monkeypatch.setattr(settings, "brave_search_api_key", "fixture-brave-key")
    monkeypatch.setattr(settings, "sanad_enable_broad_web_discovery", True)
    monkeypatch.setattr(settings, "sanad_max_brave_requests", 2)
    monkeypatch.setattr(settings, "sanad_max_web_pages", 3)
    pipeline = WebDiscoveryPipeline(
        provider=BroadWebDiscoveryProvider(
            transport=httpx.MockTransport(search_handler)
        ),
        page_retriever=WebPageRetriever(
            transport=httpx.MockTransport(page_handler)
        ),
    )
    claim = ReconstructedClaim(
        reconstructed_claim="Amal atau perbuatan berkaitan dengan niat.",
        source_text="katanya perbuatan tergantung niat",
        search_focus=["amal", "niat"],
        domain=Domain.HADITH,
    )
    queries = QueryBundle(
        web_queries=["amal tergantung niat hadis"],
    )

    results, errors, telemetry = await pipeline.retrieve(claim, queries)

    assert len(search_requests) == 1
    assert len(page_requests) == 2
    assert len(results) == 1
    assert results[0].resolved_url == "https://journal.example.org/hadis-niat"
    assert results[0].evidence_state == LinkState.DISCOVERY_ONLY
    assert results[0].link_state == LinkState.DISCOVERY_ONLY
    assert all(item.link_state == LinkState.DISCOVERY_ONLY for item in results)
    assert errors == ["Web page content was not relevant to the query."]
    assert telemetry.web_candidate_count == 2
    assert telemetry.fetched_page_count == 1
    assert telemetry.brave_request_count == 1
    assert telemetry.brave_request_limit == 2
    assert telemetry.cache_state == CacheState.MISS


class _HadithIntent:
    def analyze(self, text: str) -> IntentAnalysis:
        return IntentAnalysis(
            original_text=text,
            primary_intent="Mencari sumber hadis tentang amal dan niat.",
            explicit_claims=[text],
            key_concepts=["amal", "niat"],
            domain_candidate=Domain.HADITH,
            routing_method=RoutingMethod.LOCAL_SEMANTIC,
            routing_confidence=0.91,
            ambiguity_score=0.05,
            needs_clarification=False,
        )

    def reconstruct(self, intent: IntentAnalysis) -> ReconstructedClaim:
        return ReconstructedClaim(
            reconstructed_claim="Amal atau perbuatan berkaitan dengan niat.",
            source_text=intent.original_text,
            search_focus=["amal", "niat"],
            domain=Domain.HADITH,
        )


class _HadithQueries:
    def generate(self, claim: ReconstructedClaim) -> QueryBundle:
        return QueryBundle(
            indonesian_queries=["hadis amal tergantung niat"],
            english_queries=["actions are judged by intentions hadith"],
            web_queries=["amal tergantung niat hadis"],
        )


class _StructuredHadithRetrieval:
    async def retrieve(self, queries: QueryBundle):
        return [
            Candidate(
                candidate_id="sunnah:bukhari:1",
                provider_id="sunnah",
                provider_name="Sunnah.com Official API",
                source_type="hadith",
                trust_tier=1,
                title="Sahih al-Bukhari 1",
                collection="bukhari",
                item_number="1",
                language="ar+en",
                retrieved_text="Actions are judged by intentions and each person has what was intended.",
                retrieved_texts={
                    "ar": "إنما الأعمال بالنيات",
                    "en": "Actions are judged by intentions.",
                },
                source_url="https://sunnah.com/bukhari:1",
                source_identifier="bukhari:1",
                retrieval_queries=queries.all_queries,
                metadata_complete=True,
                official_api_validated=True,
            )
        ], []


class _StructuredFirstReranker:
    def rank(self, claim: ReconstructedClaim, candidates: list[Candidate]):
        assert len(candidates) == 1
        return [
            (
                candidates[0],
                RankingFeatures(
                    lexical_overlap=0.96,
                    semantic_similarity=0.96,
                    metadata_match=1.0,
                    multi_query_agreement=0.66,
                    relevance_score=0.90,
                ),
            )
        ]


class _VerifiedStructuredLink:
    async def validate(self, candidate: Candidate) -> LinkValidation:
        return LinkValidation(
            state=LinkState.VERIFIED_DIRECT,
            original_url=candidate.source_url,
            final_url=candidate.source_url,
            http_status=200,
            provider_domain_match=True,
            exact_identity_match=True,
        )


@pytest.mark.asyncio
async def test_orchestrator_web_discovery_is_opt_in():
    orchestrator = SanadOrchestrator(
        intent_engine=_HadithIntent(),
        query_generator=_HadithQueries(),
        retrieval=_StructuredHadithRetrieval(),
        reranker=_StructuredFirstReranker(),
        link_validator=_VerifiedStructuredLink(),
    )

    response = await orchestrator.search("katanya perbuatan tergantung niat")

    assert orchestrator.web_retrieval is None
    assert response.web_results == []
    assert len(response.evidence) == 1
    assert response.evidence[0].link.state == LinkState.VERIFIED_DIRECT


@pytest.mark.asyncio
async def test_orchestrator_keeps_structured_hadith_primary_and_web_separate(
    monkeypatch,
):
    brave_secret = "private-brave-sentinel"
    hadith_secret = "private-hadith-sentinel"
    quran_secret = "private-quran-sentinel"
    search_requests: list[httpx.Request] = []

    def search_handler(request: httpx.Request) -> httpx.Response:
        search_requests.append(request)
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Artikel penjelas hadis niat",
                            "url": "https://institute.example.org/artikel/niat",
                            "description": "Penjelasan dan rujukan hadis amal bergantung niat",
                        }
                    ]
                }
            },
        )

    def page_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=_article_html(publisher="Institut Studi Islam"),
        )

    monkeypatch.setattr(settings, "brave_search_api_key", brave_secret)
    monkeypatch.setattr(settings, "hadith_api_key", hadith_secret)
    monkeypatch.setattr(settings, "quran_foundation_client_secret", quran_secret)
    monkeypatch.setattr(settings, "sanad_enable_broad_web_discovery", True)
    monkeypatch.setattr(settings, "sanad_max_brave_requests", 2)
    web_pipeline = WebDiscoveryPipeline(
        provider=BroadWebDiscoveryProvider(
            transport=httpx.MockTransport(search_handler)
        ),
        page_retriever=WebPageRetriever(
            transport=httpx.MockTransport(page_handler)
        ),
    )
    orchestrator = SanadOrchestrator(
        intent_engine=_HadithIntent(),
        query_generator=_HadithQueries(),
        retrieval=_StructuredHadithRetrieval(),
        reranker=_StructuredFirstReranker(),
        link_validator=_VerifiedStructuredLink(),
        web_retrieval=web_pipeline,
    )

    response = await orchestrator.search("katanya perbuatan tergantung niat")
    serialized = response.model_dump_json()
    decoded = json.loads(serialized)

    assert response.status == FinalStatus.SUCCESS
    assert len(response.evidence) == 1
    assert response.evidence[0].candidate.provider_id == "sunnah"
    assert response.evidence[0].relationship == EvidenceRelation.DIRECT_MATCH
    assert response.evidence[0].link.state == LinkState.VERIFIED_DIRECT
    assert len(response.web_results) == 1
    assert response.web_results[0].source_url == (
        "https://institute.example.org/artikel/niat"
    )
    assert response.web_results[0].evidence_state == LinkState.DISCOVERY_ONLY
    assert response.web_results[0].link_state == LinkState.DISCOVERY_ONLY
    assert decoded["evidence"][0]["candidate"]["source_url"] == (
        "https://sunnah.com/bukhari:1"
    )
    assert decoded["web_results"][0]["source_url"] == (
        "https://institute.example.org/artikel/niat"
    )
    assert response.retrieval_telemetry.structured_candidate_count == 1
    assert response.retrieval_telemetry.web_candidate_count == 1
    assert response.retrieval_telemetry.fetched_page_count == 1
    assert response.retrieval_telemetry.brave_request_count == 1
    assert len(search_requests) == 1
    assert search_requests[0].headers["x-subscription-token"] == brave_secret
    assert brave_secret not in serialized
    assert hadith_secret not in serialized
    assert quran_secret not in serialized
    assert "x-subscription-token" not in serialized.casefold()
