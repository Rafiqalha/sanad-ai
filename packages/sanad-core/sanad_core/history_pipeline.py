from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from difflib import SequenceMatcher
import re
from typing import Any, Iterable, Mapping, Sequence

from .concept_expansion import normalize_concepts
from .providers.crossref import CrossrefProvider, CrossrefWork
from .providers.mediawiki import MediaWikiArticle, MediaWikiProvider
from .providers.openalex import OpenAlexProvider, OpenAlexWork, normalise_doi


_QUESTION_WORDS = {
    "a", "about", "ada", "adalah", "academic", "akademik", "al", "apa",
    "apakah", "bagaimana", "dan", "dari", "di", "history", "is", "islam",
    "islamic", "kajian", "mengenai", "of", "oleh", "penelitian", "research",
    "sejarah", "siapa", "studi", "study", "sumber", "tentang", "the", "untuk",
    "yang", "perang",
}
_ACADEMIC_MARKERS = {
    "academic", "akademik", "artikel", "doi", "journal", "jurnal", "kajian",
    "paper", "penelitian", "research", "scholarly", "studi", "study",
}
_GENERIC_TOPIC_TOKENS = {
    "development", "berkembang", "berkembangnya", "perkembangan",
    "ilmu", "knowledge", "source", "sources", "work", "works",
}
_MIN_QUERY_FIT = 0.08


@dataclass(frozen=True, slots=True)
class ProvenanceSource:
    """A normalized source record.

    `source_class` records provenance only. `relevance_score` measures query fit,
    never religious authority or truth.
    """

    title: str
    provider_ids: tuple[str, ...]
    provider: str
    source_class: str
    source_url: str
    resolved_url: str
    link_state: str
    validation_timestamp: datetime
    summary: str | None = None
    content: str | None = None
    language: str | None = None
    authors: tuple[str, ...] = ()
    publisher: str | None = None
    institution: str | None = None
    journal: str | None = None
    year: int | None = None
    publication_date: str | None = None
    doi: str | None = None
    oa_status: str | None = None
    is_open_access: bool | None = None
    relevance_score: float = 0.0
    retrieval_queries: tuple[str, ...] = ()
    authority_scope: str = "PROVENANCE_ONLY"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def author(self) -> str | None:
        return ", ".join(self.authors) or None

    @property
    def provenance(self) -> str:
        return self.source_class

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["validation_timestamp"] = self.validation_timestamp.isoformat()
        data["author"] = self.author
        data["provenance"] = self.provenance
        return data


@dataclass(frozen=True, slots=True)
class HistoryRetrievalResult:
    query: str
    generated_queries: tuple[str, ...]
    sources: tuple[ProvenanceSource, ...]
    encyclopedic_sources: tuple[ProvenanceSource, ...]
    academic_sources: tuple[ProvenanceSource, ...]
    institutional_sources: tuple[ProvenanceSource, ...]
    broad_web_sources: tuple[ProvenanceSource, ...]
    errors: tuple[str, ...]
    provider_counts: Mapping[str, int]
    provider_telemetry: Mapping[str, int]
    retrieved_at: datetime

    @property
    def failure_message(self) -> str | None:
        if self.sources:
            return None
        return (
            "Sumber pernyataan ini belum diketahui atau belum dapat diverifikasi "
            "dari sumber yang berhasil ditelusuri."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "generated_queries": list(self.generated_queries),
            "sources": [source.to_dict() for source in self.sources],
            "encyclopedic_sources": [
                source.to_dict() for source in self.encyclopedic_sources
            ],
            "academic_sources": [source.to_dict() for source in self.academic_sources],
            "institutional_sources": [
                source.to_dict() for source in self.institutional_sources
            ],
            "broad_web_sources": [
                source.to_dict() for source in self.broad_web_sources
            ],
            "errors": list(self.errors),
            "provider_counts": dict(self.provider_counts),
            "provider_telemetry": dict(self.provider_telemetry),
            "retrieved_at": self.retrieved_at.isoformat(),
            "failure_message": self.failure_message,
        }


@dataclass(slots=True)
class _ProviderRun:
    items: list[Any] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    candidate_count: int = 0
    request_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    page_cache_hits: int = 0
    page_cache_misses: int = 0


class IslamicHistoryPipeline:
    """Aggregate Wikipedia, OpenAlex, Crossref, and fetched broad-web pages.

    The pipeline is intentionally independent of religious evidence selection.
    Wikipedia remains secondary/encyclopedic; OpenAlex and Crossref remain
    scholarly-discovery and bibliographic metadata services.
    """

    def __init__(
        self,
        *,
        mediawiki: MediaWikiProvider | None = None,
        openalex: OpenAlexProvider | None = None,
        crossref: CrossrefProvider | None = None,
        broad_web_provider: Any | None = None,
        page_retriever: Any | None = None,
        enable_broad_web: bool = True,
        max_queries: int = 2,
        max_per_provider: int = 4,
        max_broad_pages: int = 3,
        max_doi_validations: int = 2,
    ):
        self.mediawiki = mediawiki or MediaWikiProvider(max_results=max_per_provider)
        self.openalex = openalex or OpenAlexProvider(max_results=max_per_provider)
        self.crossref = crossref or CrossrefProvider(max_results=max_per_provider)
        self.max_queries = max(1, min(int(max_queries), 3))
        self.max_per_provider = max(1, min(int(max_per_provider), 10))
        self.max_broad_pages = max(1, min(int(max_broad_pages), 5))
        self.max_doi_validations = max(0, min(int(max_doi_validations), 5))
        # Provider telemetry fields are mutable compatibility attributes.
        # Serialize aggregate runs so concurrent API requests cannot overwrite
        # one another's error and cost accounting.
        self._run_lock = asyncio.Lock()

        self.broad_web_provider = None
        self.page_retriever = None
        if enable_broad_web:
            if broad_web_provider is None or page_retriever is None:
                # The import stays local so this independent pipeline can be
                # reused without forcing the existing Brave path on callers.
                from .providers.broad_web import (
                    BroadWebDiscoveryProvider,
                    WebPageRetriever,
                )

                broad_web_provider = broad_web_provider or BroadWebDiscoveryProvider()
                page_retriever = page_retriever or WebPageRetriever()
            self.broad_web_provider = broad_web_provider
            self.page_retriever = page_retriever

    async def retrieve(
        self,
        query: str,
        *,
        generated_queries: Sequence[str] | None = None,
        max_results: int = 12,
    ) -> HistoryRetrievalResult:
        async with self._run_lock:
            return await self._retrieve_unlocked(
                query,
                generated_queries=generated_queries,
                max_results=max_results,
            )

    async def _retrieve_unlocked(
        self,
        query: str,
        *,
        generated_queries: Sequence[str] | None = None,
        max_results: int = 12,
    ) -> HistoryRetrievalResult:
        query = _clean_query(query)
        queries = _unique_queries([query, *(generated_queries or ())], self.max_queries)
        retrieved_at = datetime.now(timezone.utc)
        if not query:
            return _empty_result(query, queries, ["History query was empty."], retrieved_at)

        wiki_task = asyncio.create_task(
            self._search_many(self.mediawiki, queries, self.max_per_provider)
        )
        # OpenAlex keyless mode is more reliable with one focused scholarly
        # query than with an immediate multilingual burst. Other providers
        # still receive the independent raw + semantic query pair.
        openalex_queries = queries[1:2] if len(queries) > 1 else queries
        openalex_task = asyncio.create_task(
            self._search_many(
                self.openalex,
                openalex_queries,
                self.max_per_provider,
            )
        )
        crossref_task = asyncio.create_task(
            self._search_many(self.crossref, queries, self.max_per_provider)
        )
        broad_task = asyncio.create_task(self._retrieve_broad(queries))

        wiki_run, openalex_run, crossref_run, broad_run = await asyncio.gather(
            wiki_task,
            openalex_task,
            crossref_task,
            broad_task,
        )

        exact_crossref = await self._validate_openalex_dois(openalex_run.items)
        crossref_run.items.extend(exact_crossref.items)
        crossref_run.errors.extend(exact_crossref.errors)

        normalized: list[ProvenanceSource] = []
        normalized.extend(_from_wikipedia(item, queries) for item in wiki_run.items)
        normalized.extend(_from_openalex(item, queries) for item in openalex_run.items)
        normalized.extend(_from_crossref(item, queries) for item in crossref_run.items)
        normalized.extend(broad_run.items)

        merged = _merge_duplicate_sources(normalized)
        raw_query_tokens = set(
            re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)
        )
        academic_mode = bool(raw_query_tokens & _ACADEMIC_MARKERS)
        ranked = [
            replace(
                source,
                relevance_score=_rank_source(source, queries, academic_mode),
            )
            for source in merged
        ]
        ranked.sort(key=lambda source: (-source.relevance_score, source.title.casefold()))
        bounded_result_count = max(1, min(int(max_results), 30))
        ranked = [
            source
            for source in ranked
            if _source_query_fit(source, queries) >= _MIN_QUERY_FIT
        ][:bounded_result_count]

        encyclopedic = tuple(
            item
            for item in ranked
            if item.source_class == "ENCYCLOPEDIC"
            and item.link_state != "DISCOVERY_ONLY"
        )
        academic = tuple(
            item
            for item in ranked
            if item.source_class == "ACADEMIC"
            and item.link_state != "DISCOVERY_ONLY"
        )
        institutional = tuple(
            item
            for item in ranked
            if item.source_class
            in {"OFFICIAL_GOVERNMENT", "INSTITUTIONAL", "PUBLISHER"}
            and item.link_state != "DISCOVERY_ONLY"
        )
        broad = tuple(
            item
            for item in ranked
            if item.link_state == "DISCOVERY_ONLY"
        )
        errors = _unique_strings(
            wiki_run.errors
            + openalex_run.errors
            + crossref_run.errors
            + broad_run.errors
        )
        provider_counts = {
            "wikipedia": len(wiki_run.items),
            "openalex": len(openalex_run.items),
            "crossref": len(_dedupe_provider_items(crossref_run.items)),
            "broad_web": len(broad_run.items),
        }
        provider_telemetry = {
            "wikipedia_requests": wiki_run.request_count,
            "wikipedia_cache_hits": wiki_run.cache_hits,
            "wikipedia_cache_misses": wiki_run.cache_misses,
            "openalex_requests": openalex_run.request_count,
            "openalex_cache_hits": openalex_run.cache_hits,
            "openalex_cache_misses": openalex_run.cache_misses,
            "crossref_requests": crossref_run.request_count + exact_crossref.request_count,
            "crossref_cache_hits": crossref_run.cache_hits + exact_crossref.cache_hits,
            "crossref_cache_misses": crossref_run.cache_misses + exact_crossref.cache_misses,
            "brave_requests": broad_run.request_count,
            "brave_cache_hits": broad_run.cache_hits,
            "brave_cache_misses": broad_run.cache_misses,
            "web_candidate_count": broad_run.candidate_count,
            "fetched_page_count": len(broad_run.items),
            "page_cache_hits": broad_run.page_cache_hits,
            "page_cache_misses": broad_run.page_cache_misses,
        }
        return HistoryRetrievalResult(
            query=query,
            generated_queries=tuple(queries),
            sources=tuple(ranked),
            encyclopedic_sources=encyclopedic,
            academic_sources=academic,
            institutional_sources=institutional,
            broad_web_sources=broad,
            errors=tuple(errors),
            provider_counts=provider_counts,
            provider_telemetry=provider_telemetry,
            retrieved_at=retrieved_at,
        )

    async def search(
        self,
        query: str,
        *,
        generated_queries: Sequence[str] | None = None,
        max_results: int = 12,
    ) -> HistoryRetrievalResult:
        return await self.retrieve(
            query,
            generated_queries=generated_queries,
            max_results=max_results,
        )

    async def _search_many(
        self,
        provider: Any,
        queries: Sequence[str],
        limit: int,
    ) -> _ProviderRun:
        run = _ProviderRun()
        for query in queries:
            try:
                items = await provider.search(query, limit=limit)
            except Exception as exc:  # Provider isolation is deliberate.
                run.errors.append(
                    f"{getattr(provider, 'provider_id', 'provider')} failed: "
                    f"{type(exc).__name__}."
                )
                continue
            if isinstance(items, list):
                run.items.extend(items)
            run.errors.extend(getattr(provider, "last_errors", []) or [])
            run.request_count += int(getattr(provider, "request_count", 0) or 0)
            run.cache_hits += int(getattr(provider, "cache_hits", 0) or 0)
            run.cache_misses += int(getattr(provider, "cache_misses", 0) or 0)
        run.items = _dedupe_provider_items(run.items)
        run.errors = _unique_strings(run.errors)
        return run

    async def _validate_openalex_dois(self, works: Sequence[Any]) -> _ProviderRun:
        run = _ProviderRun()
        if self.max_doi_validations <= 0 or not hasattr(self.crossref, "lookup_doi"):
            return run
        dois = _unique_strings(
            [
                doi
                for work in works
                if isinstance(work, OpenAlexWork)
                and (doi := normalise_doi(work.doi)) is not None
            ]
        )[: self.max_doi_validations]
        # Sequential exact lookups keep the public Crossref traffic polite.
        for doi in dois:
            try:
                item = await self.crossref.lookup_doi(doi)
            except Exception as exc:
                run.errors.append(
                    f"Crossref DOI validation failed: {type(exc).__name__}."
                )
                continue
            if item is not None:
                run.items.append(item)
            run.errors.extend(getattr(self.crossref, "last_errors", []) or [])
            run.request_count += int(getattr(self.crossref, "request_count", 0) or 0)
            run.cache_hits += int(getattr(self.crossref, "cache_hits", 0) or 0)
            run.cache_misses += int(getattr(self.crossref, "cache_misses", 0) or 0)
        run.items = _dedupe_provider_items(run.items)
        run.errors = _unique_strings(run.errors)
        return run

    async def _retrieve_broad(self, queries: Sequence[str]) -> _ProviderRun:
        run = _ProviderRun()
        if self.broad_web_provider is None or self.page_retriever is None:
            return run
        try:
            batch = await self.broad_web_provider.search(
                list(queries),
                max_requests=min(2, len(queries)),
            )
        except Exception as exc:
            run.errors.append(f"Broad web discovery failed: {type(exc).__name__}.")
            return run

        run.errors.extend(getattr(batch, "errors", []) or [])
        hits = list(getattr(batch, "hits", []) or [])
        run.candidate_count = len(hits)
        run.request_count = int(getattr(batch, "brave_request_count", 0) or 0)
        run.cache_hits = int(getattr(batch, "cache_hits", 0) or 0)
        run.cache_misses = int(getattr(batch, "cache_misses", 0) or 0)
        hits.sort(
            key=lambda hit: _hit_relevance(hit, queries),
            reverse=True,
        )
        outcomes = await asyncio.gather(
            *(
                self.page_retriever.fetch(hit, relevance_queries=list(queries))
                for hit in hits[: self.max_broad_pages]
            ),
            return_exceptions=True,
        )
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                run.errors.append(
                    f"Broad web page retrieval failed: {type(outcome).__name__}."
                )
                continue
            if bool(getattr(outcome, "cache_hit", False)):
                run.page_cache_hits += 1
            else:
                run.page_cache_misses += 1
            page = getattr(outcome, "result", None)
            if page is not None:
                source = _from_web_page(page, queries)
                if source is not None:
                    run.items.append(source)
            elif getattr(outcome, "error", None):
                run.errors.append(str(outcome.error))
        run.errors = _unique_strings(run.errors)
        return run


def _empty_result(
    query: str,
    queries: Sequence[str],
    errors: Sequence[str],
    retrieved_at: datetime,
) -> HistoryRetrievalResult:
    return HistoryRetrievalResult(
        query=query,
        generated_queries=tuple(queries),
        sources=(),
        encyclopedic_sources=(),
        academic_sources=(),
        institutional_sources=(),
        broad_web_sources=(),
        errors=tuple(errors),
        provider_counts={
            "wikipedia": 0,
            "openalex": 0,
            "crossref": 0,
            "broad_web": 0,
        },
        provider_telemetry={},
        retrieved_at=retrieved_at,
    )


def _clean_query(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _unique_queries(values: Iterable[str], limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean_query(value)
        key = clean.casefold()
        if clean and key not in seen:
            seen.add(key)
            output.append(clean)
        if len(output) >= limit:
            break
    return output


def _unique_strings(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").strip()
        if clean and clean.casefold() not in seen:
            seen.add(clean.casefold())
            output.append(clean)
    return output


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize_concepts(value)
        if len(token) > 1 and token not in _QUESTION_WORDS
    }


def _value(value: Any) -> str:
    return str(getattr(value, "value", value or ""))


def _from_wikipedia(
    article: MediaWikiArticle,
    queries: Sequence[str],
) -> ProvenanceSource:
    return ProvenanceSource(
        title=article.title,
        provider_ids=(article.provider_id,),
        provider=article.provider,
        source_class="ENCYCLOPEDIC",
        source_url=article.canonical_url,
        resolved_url=article.canonical_url,
        link_state="VERIFIED_PROVIDER",
        validation_timestamp=article.retrieved_at,
        summary=article.extract,
        content=article.extract,
        language=article.language,
        retrieval_queries=tuple(queries),
        authority_scope="ENCYCLOPEDIC_SECONDARY_NOT_RELIGIOUS_AUTHORITY",
        metadata={"page_id": article.page_id},
    )


def _from_openalex(work: OpenAlexWork, queries: Sequence[str]) -> ProvenanceSource:
    return ProvenanceSource(
        title=work.title,
        provider_ids=(work.provider_id,),
        provider=work.provider,
        source_class="ACADEMIC",
        source_url=work.landing_page_url,
        resolved_url=work.landing_page_url,
        link_state="VERIFIED_PROVIDER",
        validation_timestamp=work.retrieved_at,
        summary=work.abstract,
        authors=work.authors,
        journal=work.source_name,
        year=work.publication_year,
        publication_date=work.publication_date,
        doi=work.doi,
        oa_status=work.oa_status,
        is_open_access=work.is_open_access,
        retrieval_queries=tuple(queries),
        authority_scope=work.authority_scope,
        metadata={
            "openalex_id": work.openalex_id,
            "canonical_doi_url": work.canonical_doi_url,
            "oa_url": work.oa_url,
            "work_type": work.work_type,
        },
    )


def _from_crossref(work: CrossrefWork, queries: Sequence[str]) -> ProvenanceSource:
    return ProvenanceSource(
        title=work.title,
        provider_ids=(work.provider_id,),
        provider=work.provider,
        source_class="ACADEMIC",
        source_url=work.source_url,
        resolved_url=work.source_url,
        link_state="VERIFIED_PROVIDER",
        validation_timestamp=work.retrieved_at,
        summary=work.abstract,
        authors=work.authors,
        publisher=work.publisher,
        journal=work.journal,
        year=work.publication_year,
        publication_date=work.publication_date,
        doi=work.doi,
        retrieval_queries=tuple(queries),
        authority_scope=work.authority_scope,
        metadata={
            "canonical_doi_url": work.canonical_doi_url,
            "work_type": work.work_type,
            "full_text_available": False,
            "crossref_validation_method": work.validation_method,
            "doi_lookup_validated": work.validation_method == "DOI_LOOKUP",
        },
    )


def _from_web_page(page: Any, queries: Sequence[str]) -> ProvenanceSource | None:
    title = str(getattr(page, "page_title", "") or "").strip()
    source_url = str(getattr(page, "source_url", "") or "").strip()
    resolved_url = str(getattr(page, "resolved_url", "") or "").strip()
    content = str(getattr(page, "content_excerpt", "") or "").strip()
    validation_timestamp = (
        getattr(page, "link_validated_at", None)
        or getattr(page, "retrieved_at", None)
    )
    # A search snippet is not evidence. Missing fetched content or validation
    # timestamp therefore excludes the candidate from the result entirely.
    if (
        not title
        or not source_url
        or not resolved_url
        or not content
        or not isinstance(validation_timestamp, datetime)
    ):
        return None
    author = str(getattr(page, "author", "") or "").strip()
    publisher = str(getattr(page, "publisher", "") or "").strip() or None
    institution = str(getattr(page, "institution", "") or "").strip() or None
    return ProvenanceSource(
        title=title,
        provider_ids=(str(getattr(page, "link_provider", "") or "brave_web_discovery"),),
        provider="Brave Search + fetched page",
        source_class=_value(getattr(page, "source_class", "UNKNOWN")),
        source_url=source_url,
        resolved_url=resolved_url,
        link_state="DISCOVERY_ONLY",
        validation_timestamp=validation_timestamp,
        summary=content,
        content=content,
        authors=(author,) if author else (),
        publisher=publisher,
        institution=institution,
        publication_date=(
            str(getattr(page, "publication_date", "") or "").strip() or None
        ),
        retrieval_queries=tuple(
            _unique_strings(
                [*queries, *(getattr(page, "retrieval_queries", []) or [])]
            )
        ),
        authority_scope="WEB_DISCOVERY_NOT_RELIGIOUS_AUTHORITY",
        metadata={
            "http_status": getattr(page, "http_status", None),
            "source_domain": getattr(page, "source_domain", None),
        },
    )


def _dedupe_provider_items(items: Sequence[Any]) -> list[Any]:
    output: list[Any] = []
    positions: dict[str, int] = {}
    for item in items:
        doi = normalise_doi(getattr(item, "doi", None))
        identifier = (
            doi
            or str(getattr(item, "canonical_url", "") or "").casefold()
            or str(getattr(item, "openalex_id", "") or "").casefold()
            or str(getattr(item, "source_url", "") or "").casefold()
            or str(getattr(item, "title", "") or "").casefold()
        )
        if not identifier:
            continue
        existing_position = positions.get(identifier)
        if existing_position is None:
            positions[identifier] = len(output)
            output.append(item)
            continue
        # An exact Crossref DOI response is stronger metadata validation than
        # a bibliographic-search hit, while remaining non-full-text evidence.
        if (
            getattr(item, "validation_method", None) == "DOI_LOOKUP"
            and getattr(output[existing_position], "validation_method", None)
            != "DOI_LOOKUP"
        ):
            output[existing_position] = item
    return output


def _merge_duplicate_sources(sources: Sequence[ProvenanceSource]) -> list[ProvenanceSource]:
    merged: dict[str, ProvenanceSource] = {}
    order: list[str] = []
    for source in sources:
        base_key = (
            f"doi:{source.doi.casefold()}"
            if source.doi
            else f"url:{source.resolved_url.rstrip('/').casefold()}"
        )
        key = base_key
        existing = merged.get(base_key)
        # A fetched Brave page and structured metadata may legitimately point
        # to the same URL, but their evidence boundaries differ. Keep them as
        # separate provenance records: discovery text must never inherit a
        # provider-validated state through deduplication.
        if (
            existing is not None
            and (existing.link_state == "DISCOVERY_ONLY")
            != (source.link_state == "DISCOVERY_ONLY")
        ):
            key = f"{base_key}:provenance:{source.link_state.casefold()}"
        if key not in merged:
            merged[key] = source
            order.append(key)
        else:
            merged[key] = _merge_source_pair(merged[key], source)
    return [merged[key] for key in order]


def _merge_source_pair(
    first: ProvenanceSource,
    second: ProvenanceSource,
) -> ProvenanceSource:
    provider_ids = tuple(_unique_strings([*first.provider_ids, *second.provider_ids]))
    provider_names = {
        "wikipedia": "Wikipedia",
        "openalex": "OpenAlex",
        "crossref": "Crossref",
        "brave_web_discovery": "Brave/fetched page",
    }
    provider = " + ".join(provider_names.get(item, item) for item in provider_ids)
    metadata = {**dict(first.metadata), **dict(second.metadata)}
    if {"openalex", "crossref"}.issubset(set(provider_ids)):
        similarity = SequenceMatcher(
            None,
            first.title.casefold(),
            second.title.casefold(),
        ).ratio()
        metadata["crossref_doi_validated"] = bool(
            metadata.get("doi_lookup_validated")
        )
        metadata["crossref_title_match"] = round(similarity, 4)
        metadata["crossref_title_validation"] = (
            "MATCH" if similarity >= 0.80 else "POSSIBLE_MISMATCH"
        )

    doi = first.doi or second.doi
    doi_url = f"https://doi.org/{doi}" if doi else None
    source_url = doi_url or first.source_url or second.source_url
    preferred_class = _preferred_source_class(first.source_class, second.source_class)
    summary_candidates = [item for item in (first.summary, second.summary) if item]
    content_candidates = [item for item in (first.content, second.content) if item]
    return ProvenanceSource(
        title=first.title,
        provider_ids=provider_ids,
        provider=provider,
        source_class=preferred_class,
        source_url=source_url,
        resolved_url=source_url,
        link_state=(
            "VERIFIED_PROVIDER"
            if "DISCOVERY_ONLY" not in {first.link_state, second.link_state}
            or any(item in {"wikipedia", "openalex", "crossref"} for item in provider_ids)
            else "DISCOVERY_ONLY"
        ),
        validation_timestamp=max(
            first.validation_timestamp,
            second.validation_timestamp,
        ),
        summary=max(summary_candidates, key=len) if summary_candidates else None,
        content=max(content_candidates, key=len) if content_candidates else None,
        language=first.language or second.language,
        authors=tuple(_unique_strings([*first.authors, *second.authors])),
        publisher=first.publisher or second.publisher,
        institution=first.institution or second.institution,
        journal=first.journal or second.journal,
        year=first.year or second.year,
        publication_date=first.publication_date or second.publication_date,
        doi=doi,
        oa_status=first.oa_status or second.oa_status,
        is_open_access=(
            first.is_open_access
            if first.is_open_access is not None
            else second.is_open_access
        ),
        retrieval_queries=tuple(
            _unique_strings([*first.retrieval_queries, *second.retrieval_queries])
        ),
        authority_scope=(
            "SCHOLARLY_DISCOVERY_AND_METADATA_NOT_RELIGIOUS_AUTHORITY"
            if preferred_class == "ACADEMIC"
            else first.authority_scope
        ),
        metadata=metadata,
    )


def _preferred_source_class(first: str, second: str) -> str:
    priority = {
        "ACADEMIC": 5,
        "ENCYCLOPEDIC": 4,
        "OFFICIAL_GOVERNMENT": 3,
        "INSTITUTIONAL": 2,
        "PUBLISHER": 2,
        "GENERAL_WEB": 1,
        "COMMUNITY": 0,
        "UNKNOWN": -1,
    }
    return first if priority.get(first, -1) >= priority.get(second, -1) else second


def _rank_source(
    source: ProvenanceSource,
    queries: Sequence[str],
    academic_mode: bool,
) -> float:
    best_fit = _source_query_fit(source, queries)
    metadata_fields = (
        bool(source.authors),
        bool(source.year),
        bool(source.doi),
        bool(source.publisher or source.journal or source.institution),
    )
    metadata_completeness = sum(metadata_fields) / len(metadata_fields)
    fit_bonus = 0.0
    if academic_mode and source.source_class == "ACADEMIC":
        fit_bonus = 0.10
    elif not academic_mode and source.source_class == "ENCYCLOPEDIC":
        fit_bonus = 0.08
    elif source.source_class in {"OFFICIAL_GOVERNMENT", "INSTITUTIONAL"}:
        fit_bonus = 0.04
    # This is relevance/provenance fitness only; it is not a truth score.
    return round(min(1.0, (0.86 * best_fit) + (0.06 * metadata_completeness) + fit_bonus), 4)


def _source_query_fit(
    source: ProvenanceSource,
    queries: Sequence[str],
) -> float:
    """Measure semantic/lexical fit before any provenance bonus is applied."""

    title_tokens = _tokens(source.title)
    body = " ".join(part for part in (source.summary, source.content) if part)[:6000]
    body_tokens = _tokens(body)
    # Generated scholarly queries contain broad process words such as
    # "research", "development", and "knowledge". Those terms alone must not
    # admit an unrelated paper. Require at least one distinctive topic token
    # from the original user query whenever one is available.
    anchor_tokens = (
        _tokens(queries[0]) - _ACADEMIC_MARKERS - _GENERIC_TOPIC_TOKENS
        if queries
        else set()
    )
    if anchor_tokens and not _fuzzy_token_coverage(
        anchor_tokens,
        title_tokens | body_tokens,
    ):
        return 0.0
    best_fit = 0.0
    for query in queries:
        query_tokens = _tokens(query)
        if not query_tokens:
            continue
        title_coverage = _fuzzy_token_coverage(query_tokens, title_tokens)
        body_coverage = _fuzzy_token_coverage(query_tokens, body_tokens)
        fuzzy = SequenceMatcher(None, query.casefold(), source.title.casefold()).ratio()
        # Whole-string similarity alone is too easily inflated by generic
        # words such as "history" or "war". It may refine an existing token
        # match, but cannot admit a candidate with no distinctive overlap.
        fuzzy_component = fuzzy if title_coverage or body_coverage else 0.0
        best_fit = max(
            best_fit,
            (0.55 * title_coverage)
            + (0.25 * body_coverage)
            + (0.20 * fuzzy_component),
        )
    return round(min(1.0, best_fit), 4)


def _fuzzy_token_coverage(query_tokens: set[str], target_tokens: set[str]) -> float:
    """Tolerate short transliteration variants without mapping an answer."""

    if not query_tokens or not target_tokens:
        return 0.0
    matched = 0
    for query_token in query_tokens:
        if query_token in target_tokens or any(
            len(query_token) >= 4
            and len(target_token) >= 4
            and SequenceMatcher(None, query_token, target_token).ratio() >= 0.86
            for target_token in target_tokens
        ):
            matched += 1
    return matched / len(query_tokens)


def _hit_relevance(hit: Any, queries: Sequence[str]) -> float:
    text = " ".join(
        [
            str(getattr(hit, "page_title", "") or ""),
            str(getattr(hit, "snippet", "") or ""),
        ]
    )
    text_tokens = _tokens(text)
    score = 0.0
    for query in queries:
        query_tokens = _tokens(query)
        if query_tokens:
            score = max(score, len(query_tokens & text_tokens) / len(query_tokens))
    rank = getattr(hit, "rank", 0)
    return score + (0.01 / max(1, rank if isinstance(rank, int) else 1))


HistoryPipeline = IslamicHistoryPipeline
AcademicHistoryPipeline = IslamicHistoryPipeline
