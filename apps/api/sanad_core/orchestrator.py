from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import re
from time import perf_counter
from urllib.parse import urlparse

from .config import settings
from .evidence import build_evidence
from .history_pipeline import IslamicHistoryPipeline, ProvenanceSource
from .improvement import ImprovementCategory, ImprovementTracker
from .intent import IntentEngine
from .query_generator import QueryGenerator
from .reranker import Reranker
from .retrieval import HadithRetrievalPipeline, QuranRetrievalPipeline
from .source_link_resolver import SourceLinkResolver
from .web_retrieval import WebDiscoveryPipeline
from .schemas import (
    Domain,
    CacheState,
    EvidenceRelation,
    FinalResponse,
    FinalStatus,
    RetrievalMode,
    RetrievalTelemetry,
    SourceClass,
    LinkState,
    WebSourceResult,
)


class SanadOrchestrator:
    def __init__(
        self,
        intent_engine: IntentEngine | None = None,
        query_generator: QueryGenerator | None = None,
        retrieval: HadithRetrievalPipeline | None = None,
        quran_retrieval: QuranRetrievalPipeline | None = None,
        reranker: Reranker | None = None,
        link_validator: SourceLinkResolver | None = None,
        web_retrieval: WebDiscoveryPipeline | None = None,
        history_retrieval: IslamicHistoryPipeline | None = None,
        improvement_tracker: ImprovementTracker | None = None,
    ):
        self.intent_engine = intent_engine or IntentEngine()
        self.query_generator = query_generator or QueryGenerator()
        self.retrieval = retrieval or HadithRetrievalPipeline()
        self.quran_retrieval = quran_retrieval or QuranRetrievalPipeline()
        self.reranker = reranker or Reranker()
        self.link_validator = link_validator or SourceLinkResolver()
        # Kept opt-in at the class boundary so existing embedded/test callers
        # retain their exact behavior. The FastAPI/CLI application enables it.
        self.web_retrieval = web_retrieval
        # Knowledge providers are also opt-in at the class boundary so unit
        # tests and embedded callers never make surprise network requests.
        self.history_retrieval = history_retrieval
        self.improvement_tracker = improvement_tracker or ImprovementTracker()

    async def search(self, text: str) -> FinalResponse:
        started_at = perf_counter()
        result = await self._search(text)
        result.raw_user_input = text
        result.response_time_ms = round((perf_counter() - started_at) * 1000, 2)
        self._record_improvement_signals(text, result)
        return result

    async def _search(self, text: str) -> FinalResponse:
        intent = self.intent_engine.analyze(text)
        routing = {
            "routing_method": intent.routing_method,
            "routing_confidence": intent.routing_confidence,
        }

        if intent.needs_clarification:
            return FinalResponse(
                understood_intent=intent.primary_intent,
                reconstructed_claim=None,
                domain=intent.domain_candidate,
                evidence=[],
                limited_clarification=intent.clarification_question,
                expert_review_note=None,
                status=FinalStatus.NEEDS_CLARIFICATION,
                **routing,
            )

        claim = self.intent_engine.reconstruct(intent)
        if claim.domain in {
            Domain.ISLAMIC_HISTORY,
            Domain.ACADEMIC_ISLAMIC_STUDIES,
        }:
            queries = self.query_generator.generate(claim)
            return await self._search_history_and_academic(
                intent=intent,
                claim=claim,
                queries=queries,
                routing=routing,
            )

        if claim.domain not in {Domain.HADITH, Domain.QURAN}:
            if claim.domain == Domain.GENERAL_ISLAMIC:
                message = (
                    "Jenis sumber belum cukup spesifik. Pilih hadis, ayat Al-Qur'an, "
                    "atau sumber keislaman lain agar penelusuran tidak dipaksakan."
                )
                status = FinalStatus.NEEDS_CLARIFICATION
            else:
                message = (
                    "Pertanyaan ini berada di luar cakupan penelusuran sumber Islam "
                    "atau sinyal domainnya belum cukup."
                )
                status = FinalStatus.NO_RELIABLE_SOURCE_FOUND
            return FinalResponse(
                understood_intent=intent.primary_intent,
                reconstructed_claim=claim.reconstructed_claim,
                domain=claim.domain,
                evidence=[],
                limited_clarification=message,
                expert_review_note=None,
                status=status,
                user_attribution_hypothesis=claim.user_attribution_hypothesis,
                **routing,
            )

        queries = self.query_generator.generate(claim)
        retrieval_mode: RetrievalMode | None = None
        if claim.domain == Domain.QURAN:
            candidates, provider_errors, retrieval_mode = (
                await self.quran_retrieval.retrieve(claim, queries)
            )
        else:
            candidates, provider_errors = await self.retrieval.retrieve(queries)
            retrieval_mode = RetrievalMode.SEMANTIC_SEARCH

        structured_errors = list(provider_errors)
        web_results = []
        legacy_brave_result = any(
            candidate.provider_id == "brave" for candidate in candidates
        )
        legacy_cache_hits = int(
            getattr(self.retrieval, "last_brave_cache_hits", 0) or 0
        )
        legacy_cache_misses = int(
            getattr(self.retrieval, "last_brave_cache_misses", 0) or 0
        )
        legacy_request_count = int(
            getattr(self.retrieval, "last_brave_request_count", 0) or 0
        )
        legacy_brave_used = bool(
            legacy_brave_result
            or legacy_request_count
            or legacy_cache_hits
            or legacy_cache_misses
        )
        if legacy_cache_hits and legacy_cache_misses:
            legacy_cache_state = CacheState.PARTIAL
        elif legacy_cache_hits:
            legacy_cache_state = CacheState.HIT
        elif legacy_cache_misses:
            legacy_cache_state = CacheState.MISS
        else:
            legacy_cache_state = CacheState.NOT_USED
        telemetry = RetrievalTelemetry(
            structured_candidate_count=(0 if legacy_brave_result else len(candidates)),
            web_candidate_count=(len(candidates) if legacy_brave_result else 0),
            brave_request_count=legacy_request_count,
            brave_request_limit=(
                settings.sanad_max_brave_requests if legacy_brave_used else 0
            ),
            search_cache_hits=legacy_cache_hits,
            search_cache_misses=legacy_cache_misses,
            cache_state=legacy_cache_state,
        )
        # Web discovery is an independent, optional provenance path. It runs
        # for a concrete hadith claim even when the structured provider found
        # evidence, but never promotes or replaces that evidence. Quran
        # structured success stays provider-first to avoid unnecessary cost.
        should_run_web = bool(
            self.web_retrieval is not None
            and queries.web_queries
            and (
                (
                    claim.domain == Domain.HADITH
                    and candidates
                    and not legacy_brave_result
                )
                or (
                    claim.domain == Domain.QURAN
                    and not candidates
                    and retrieval_mode == RetrievalMode.SEMANTIC_SEARCH
                )
            )
        )
        if should_run_web:
            web_results, web_errors, telemetry = await self.web_retrieval.retrieve(
                claim,
                queries,
            )
            telemetry.structured_candidate_count = len(candidates)
            provider_errors = list(dict.fromkeys(provider_errors + web_errors))
            if (
                claim.domain == Domain.QURAN
                and not candidates
                and web_results
            ):
                retrieval_mode = RetrievalMode.DISCOVERY_FALLBACK

        if not candidates:
            quran_unavailable = bool(
                claim.domain == Domain.QURAN and provider_errors
            )
            if quran_unavailable:
                clarification = "Sumber Qur’an belum dapat diakses saat ini."
            else:
                clarification = (
                    "Belum ditemukan sumber yang cukup relevan melalui provider "
                    "yang saat ini tersedia."
                )
            return FinalResponse(
                understood_intent=intent.primary_intent,
                reconstructed_claim=claim.reconstructed_claim,
                domain=claim.domain,
                evidence=[],
                limited_clarification=clarification,
                expert_review_note=(
                    "Interpretasi keagamaan tidak dibuat ketika evidence tidak tersedia."
                ),
                status=FinalStatus.NO_RELIABLE_SOURCE_FOUND,
                generated_queries=queries.all_queries,
                generated_structured_queries=queries.all_queries,
                generated_web_queries=queries.web_queries,
                web_results=web_results,
                retrieval_telemetry=telemetry,
                retrieval_mode=retrieval_mode,
                user_attribution_hypothesis=claim.user_attribution_hypothesis,
                provider_errors=provider_errors,
                **routing,
            )

        ranked = self.reranker.rank(claim, candidates)[:5]
        link_results = await asyncio.gather(
            *(self.link_validator.validate(candidate) for candidate, _ in ranked)
        )

        source_classes = {
            "quran_foundation": SourceClass.PRIMARY_RELIGIOUS_SOURCE,
            "sunnah": SourceClass.PRIMARY_RELIGIOUS_SOURCE,
            "hadithapi": SourceClass.INSTITUTIONAL,
            "brave": SourceClass.UNKNOWN,
        }
        for (candidate, _), link in zip(ranked, link_results):
            candidate.resolved_url = link.final_url
            candidate.source_domain = candidate.source_domain or (
                urlparse(link.final_url or candidate.source_url).hostname or ""
            ).casefold()
            candidate.page_title = candidate.page_title or candidate.title
            candidate.source_class = candidate.source_class or source_classes.get(
                candidate.provider_id,
                SourceClass.UNKNOWN,
            )
            candidate.retrieved_at = candidate.retrieved_at or datetime.now(timezone.utc)

        evidence = [
            build_evidence(candidate, features, link)
            for (candidate, features), link in zip(ranked, link_results)
        ]
        self._attach_matching_public_sources(evidence, web_results)

        strong = [
            item
            for item in evidence
            if item.relationship
            in {
                EvidenceRelation.DIRECT_MATCH,
                EvidenceRelation.STRONG_RELATED_MATCH,
            }
        ]

        if strong:
            clarification = (
                "Sumber di atas adalah kandidat yang paling kuat berdasarkan "
                "maksud yang dipahami, hasil retrieval, validasi provider, dan "
                "kecocokan evidence. SANAD.AI tidak menetapkan kesimpulan "
                "keagamaan final dari sumber tersebut."
            )
            status = (
                FinalStatus.PARTIAL_PROVIDER_FAILURE
                if structured_errors
                else FinalStatus.SUCCESS
            )
        elif any(
            item.relationship
            in {
                EvidenceRelation.PARTIAL_MATCH,
                EvidenceRelation.ATTRIBUTION_MISMATCH,
            }
            for item in evidence
        ):
            clarification = (
                "Kandidat terkait ditemukan, tetapi bukti atau tautan langsung "
                "belum cukup kuat untuk dianggap sebagai identifikasi sumber definitif."
            )
            status = FinalStatus.SOURCE_FOUND_LINK_UNVERIFIED
        else:
            clarification = (
                "Sumber pernyataan ini belum diketahui atau belum dapat diverifikasi "
                "dari sumber yang berhasil ditelusuri."
            )
            status = FinalStatus.NO_RELIABLE_SOURCE_FOUND

        return FinalResponse(
            understood_intent=intent.primary_intent,
            reconstructed_claim=claim.reconstructed_claim,
            domain=claim.domain,
            evidence=evidence,
            limited_clarification=clarification,
            expert_review_note=(
                "Penafsiran, penetapan hukum, atau kesimpulan keilmuan lebih lanjut "
                "tetap memerlukan guru/ahli yang kompeten."
            ),
            status=status,
            generated_queries=queries.all_queries,
            generated_structured_queries=queries.all_queries,
            generated_web_queries=queries.web_queries,
            web_results=web_results,
            retrieval_telemetry=telemetry,
            retrieval_mode=retrieval_mode,
            user_attribution_hypothesis=claim.user_attribution_hypothesis,
            provider_errors=provider_errors,
            **routing,
        )

    async def _search_history_and_academic(
        self,
        *,
        intent,
        claim,
        queries,
        routing: dict,
    ) -> FinalResponse:
        """Run encyclopedic/scholarly retrieval without religious promotion."""

        if self.history_retrieval is None:
            return FinalResponse(
                understood_intent=intent.primary_intent,
                reconstructed_claim=claim.reconstructed_claim,
                domain=claim.domain,
                evidence=[],
                limited_clarification=(
                    "Sumber sejarah dan akademik belum dapat diakses saat ini."
                ),
                expert_review_note=None,
                status=FinalStatus.NO_RELIABLE_SOURCE_FOUND,
                generated_queries=queries.all_queries,
                generated_structured_queries=queries.all_queries,
                generated_web_queries=queries.web_queries,
                retrieval_mode=RetrievalMode.SEMANTIC_SEARCH,
                user_attribution_hypothesis=claim.user_attribution_hypothesis,
                **routing,
            )

        history_result = await self.history_retrieval.retrieve(
            claim.source_text or claim.reconstructed_claim,
            generated_queries=[
                *queries.english_queries,
                *queries.web_queries,
                *queries.indonesian_queries,
            ],
        )
        web_results = [
            self._history_source_to_web_result(source)
            for source in history_result.sources
        ]
        provider_telemetry = dict(history_result.provider_telemetry)
        cache_hits = (
            provider_telemetry.get("brave_cache_hits", 0)
            + provider_telemetry.get("wikipedia_cache_hits", 0)
            + provider_telemetry.get("openalex_cache_hits", 0)
            + provider_telemetry.get("crossref_cache_hits", 0)
        )
        cache_misses = (
            provider_telemetry.get("brave_cache_misses", 0)
            + provider_telemetry.get("wikipedia_cache_misses", 0)
            + provider_telemetry.get("openalex_cache_misses", 0)
            + provider_telemetry.get("crossref_cache_misses", 0)
        )
        cache_state = CacheState.NOT_USED
        if cache_hits and cache_misses:
            cache_state = CacheState.PARTIAL
        elif cache_hits:
            cache_state = CacheState.HIT
        elif cache_misses:
            cache_state = CacheState.MISS
        telemetry = RetrievalTelemetry(
            structured_candidate_count=sum(
                count
                for provider, count in history_result.provider_counts.items()
                if provider != "broad_web"
            ),
            web_candidate_count=provider_telemetry.get(
                "web_candidate_count",
                history_result.provider_counts.get("broad_web", 0),
            ),
            fetched_page_count=provider_telemetry.get(
                "fetched_page_count",
                history_result.provider_counts.get("broad_web", 0),
            ),
            brave_request_count=provider_telemetry.get("brave_requests", 0),
            brave_request_limit=settings.sanad_max_brave_requests,
            search_cache_hits=cache_hits,
            search_cache_misses=cache_misses,
            page_cache_hits=provider_telemetry.get("page_cache_hits", 0),
            page_cache_misses=provider_telemetry.get("page_cache_misses", 0),
            cache_state=cache_state,
        )

        if not web_results:
            return FinalResponse(
                understood_intent=intent.primary_intent,
                reconstructed_claim=claim.reconstructed_claim,
                domain=claim.domain,
                evidence=[],
                limited_clarification=history_result.failure_message,
                expert_review_note=(
                    "SANAD.AI tidak membuat kesimpulan sejarah atau akademik "
                    "tanpa sumber yang berhasil ditelusuri."
                ),
                status=FinalStatus.NO_RELIABLE_SOURCE_FOUND,
                generated_queries=queries.all_queries,
                generated_structured_queries=list(history_result.generated_queries),
                generated_web_queries=queries.web_queries,
                web_results=[],
                retrieval_telemetry=telemetry,
                retrieval_mode=RetrievalMode.SEMANTIC_SEARCH,
                user_attribution_hypothesis=claim.user_attribution_hypothesis,
                provider_errors=list(history_result.errors),
                **routing,
            )

        domain_note = (
            "Wikipedia ditampilkan sebagai sumber ensiklopedis sekunder; "
            "OpenAlex dan Crossref sebagai penemuan serta metadata akademik."
            if claim.domain == Domain.ISLAMIC_HISTORY
            else "OpenAlex dan Crossref menyediakan penemuan serta metadata "
            "akademik, bukan otoritas keagamaan atau penyedia full-text."
        )
        return FinalResponse(
            understood_intent=intent.primary_intent,
            reconstructed_claim=claim.reconstructed_claim,
            domain=claim.domain,
            evidence=[],
            limited_clarification=domain_note,
            expert_review_note=(
                "Klasifikasi sumber menunjukkan provenance, bukan skor "
                "kebenaran agama."
            ),
            status=(
                FinalStatus.PARTIAL_PROVIDER_FAILURE
                if history_result.errors
                else FinalStatus.SUCCESS
            ),
            generated_queries=queries.all_queries,
            generated_structured_queries=list(history_result.generated_queries),
            generated_web_queries=queries.web_queries,
            web_results=web_results,
            retrieval_telemetry=telemetry,
            retrieval_mode=RetrievalMode.SEMANTIC_SEARCH,
            user_attribution_hypothesis=claim.user_attribution_hypothesis,
            provider_errors=list(history_result.errors),
            **routing,
        )

    @staticmethod
    def _history_source_to_web_result(source: ProvenanceSource) -> WebSourceResult:
        try:
            source_class = SourceClass(source.source_class)
        except ValueError:
            source_class = SourceClass.UNKNOWN
        try:
            link_state = LinkState(source.link_state)
        except ValueError:
            link_state = LinkState.UNVERIFIED
        source_domain = (
            urlparse(source.resolved_url or source.source_url).hostname or ""
        ).casefold().removeprefix("www.")
        http_status = source.metadata.get("http_status")
        is_fetched_web_page = (
            link_state == LinkState.DISCOVERY_ONLY
            and isinstance(http_status, int)
        )
        return WebSourceResult(
            source_url=source.source_url,
            resolved_url=source.resolved_url,
            canonical_url=source.resolved_url,
            source_domain=source_domain,
            page_title=source.title,
            source_class=source_class,
            provider=source.provider,
            publisher=source.publisher,
            institution=source.institution,
            author=source.author,
            journal=source.journal,
            year=source.year,
            doi=source.doi,
            language=source.language,
            open_access=source.is_open_access,
            oa_status=source.oa_status,
            authority_scope=source.authority_scope,
            publication_date=source.publication_date,
            snippet=source.summary,
            content_excerpt=(source.content or source.summary or "")[:1200] or None,
            relevance_score=source.relevance_score,
            evidence_state=link_state,
            link_state=link_state,
            link_provider="+".join(source.provider_ids),
            retrieved_at=source.validation_timestamp,
            # Provider metadata timestamps are not HTTP liveness checks.
            # Only a page that was actually fetched may expose this field.
            link_validated_at=(
                source.validation_timestamp if is_fetched_web_page else None
            ),
            http_status=http_status if isinstance(http_status, int) else None,
            retrieval_queries=list(source.retrieval_queries),
        )

    @staticmethod
    def _attach_matching_public_sources(evidence, web_results) -> None:
        """Associate a fetched public page without changing evidence status.

        HadithAPI exposes structured metadata but no documented canonical item
        URL. A Brave-discovered page is therefore attached only when it was
        actually fetched, belongs to a primary religious source, and contains
        both the collection identity and exact hadith number. The structured
        item remains VERIFIED_PROVIDER; the public page remains discovery.
        """

        for item in evidence:
            candidate = item.candidate
            if candidate.provider_id != "hadithapi" or not candidate.item_number:
                continue
            collection = " ".join(
                re.findall(
                    r"[\w]+",
                    str(candidate.collection or "").replace("-", " ").casefold(),
                )
            )
            book_name = " ".join(
                re.findall(
                    r"[\w]+",
                    str(candidate.raw.get("book_name") or "").casefold(),
                )
            )
            collection_terms = [term for term in collection.split() if len(term) > 3]
            aliases = {value for value in (collection, book_name) if value}
            if collection_terms:
                aliases.add(collection_terms[-1])
            number_pattern = re.compile(
                rf"(?<![\w]){re.escape(str(candidate.item_number).casefold())}(?![\w])"
            )

            for source in web_results:
                if (
                    source.source_class != SourceClass.PRIMARY_RELIGIOUS_SOURCE
                    or source.link_state != LinkState.DISCOVERY_ONLY
                    or source.http_status != 200
                    or source.link_validated_at is None
                ):
                    continue
                public_url = source.resolved_url or source.source_url
                parsed = urlparse(public_url)
                if (
                    parsed.scheme.casefold() != "https"
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or parsed.port not in {None, 443}
                ):
                    continue
                searchable = " ".join(
                    [
                        source.page_title,
                        source.content_excerpt or "",
                        public_url,
                    ]
                ).casefold()
                normalized_searchable = " ".join(
                    re.findall(r"[\w]+", searchable.replace("-", " "))
                )
                if not number_pattern.search(searchable):
                    continue
                if aliases and not any(
                    alias in normalized_searchable for alias in aliases
                ):
                    continue
                candidate.raw.update(
                    {
                        "public_source_url": public_url,
                        "public_source_http_status": source.http_status,
                        "public_source_link_validated_at": (
                            source.link_validated_at.isoformat()
                        ),
                        "public_source_class": source.source_class.value,
                        "public_source_link_state": source.link_state.value,
                    }
                )
                break

    def _record_improvement_signals(
        self,
        raw_text: str,
        result: FinalResponse,
    ) -> None:
        """Aggregate sanitized patterns; never train or update production."""

        metadata = {
            "domain": result.domain.value,
            "status": result.status.value,
            "routing_method": (
                result.routing_method.value if result.routing_method else "unknown"
            ),
        }
        categories: list[ImprovementCategory] = []
        if result.status == FinalStatus.NO_RELIABLE_SOURCE_FOUND:
            categories.extend(
                [
                    ImprovementCategory.FAILED_QUERY,
                    ImprovementCategory.NO_RESULT_PATTERN,
                ]
            )
        if result.domain == Domain.UNKNOWN:
            categories.append(ImprovementCategory.UNKNOWN_MISROUTE)
        if result.provider_errors:
            categories.append(ImprovementCategory.RETRIEVAL_FAILURE)
        if (
            result.routing_method is not None
            and result.routing_method.value == "LOCAL_SEMANTIC"
        ):
            categories.append(ImprovementCategory.INDONESIAN_PARAPHRASE)
        if result.user_attribution_hypothesis and any(
            item.relationship == EvidenceRelation.ATTRIBUTION_MISMATCH
            for item in result.evidence
        ):
            categories.append(ImprovementCategory.WRONG_ATTRIBUTION)
        if result.evidence and not any(
            item.relationship
            in {
                EvidenceRelation.DIRECT_MATCH,
                EvidenceRelation.STRONG_RELATED_MATCH,
            }
            for item in result.evidence
        ):
            categories.append(ImprovementCategory.RANKING_FAILURE)

        for category in dict.fromkeys(categories):
            self.improvement_tracker.record(
                category,
                raw_text,
                metadata=metadata,
            )
