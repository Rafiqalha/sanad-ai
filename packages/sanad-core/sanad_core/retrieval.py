from __future__ import annotations

import asyncio
from collections import defaultdict

from .config import settings
from .schemas import Candidate, QueryBundle, ReconstructedClaim, RetrievalMode
from .providers.brave import BraveDiscoveryProvider
from .providers.hadithapi import HadithAPIProvider, HadithAPISearchRequest
from .providers.quran import QuranProvider, QuranProviderError, QuranProviderUnavailable
from .providers.sunnah import SunnahAPIProvider, parse_sunnah_reference


_DEFAULT_HADITH_API = object()
_DEFAULT_QURAN_PROVIDER = object()


class QuranRetrievalPipeline:
    """Quran Foundation-only structured retrieval.

    Brave is intentionally not used here: an unavailable Quran provider yields
    an honest unavailable state instead of an unvalidated web result.
    """

    def __init__(
        self,
        provider: QuranProvider | None | object = _DEFAULT_QURAN_PROVIDER,
    ):
        self.provider = (
            QuranProvider() if provider is _DEFAULT_QURAN_PROVIDER else provider
        )

    async def retrieve(
        self,
        claim: ReconstructedClaim,
        queries: QueryBundle,
    ) -> tuple[list[Candidate], list[str], RetrievalMode]:
        source_text = claim.source_text or claim.reconstructed_claim
        from .quran_reference import detect_exact_reference

        mode = (
            RetrievalMode.EXACT_REFERENCE
            if detect_exact_reference(source_text)
            else RetrievalMode.SEMANTIC_SEARCH
        )
        if self.provider is None:
            return [], ["Quran Foundation credentials are not configured."], mode
        try:
            result = await self.provider.retrieve(source_text, queries)
            return result.candidates, result.errors, result.mode
        except QuranProviderUnavailable as exc:
            return [], [str(exc)], mode
        except QuranProviderError as exc:
            return [], [f"Quran Foundation gagal: {exc}"], mode
        except Exception as exc:
            return [], [
                "Quran Foundation gagal karena respons internal tidak terduga: "
                f"{type(exc).__name__}."
            ], mode


class HadithRetrievalPipeline:
    def __init__(
        self,
        discovery: BraveDiscoveryProvider | None = None,
        hadith_api: HadithAPIProvider | None | object = _DEFAULT_HADITH_API,
        sunnah: SunnahAPIProvider | None = None,
    ):
        self.discovery = discovery or BraveDiscoveryProvider(site_domain="sunnah.com")
        self.hadith_api = (
            HadithAPIProvider() if settings.hadith_api_key else None
        ) if hadith_api is _DEFAULT_HADITH_API else hadith_api
        self.sunnah = sunnah or SunnahAPIProvider()
        self.last_brave_request_count = 0
        self.last_brave_cache_hits = 0
        self.last_brave_cache_misses = 0

    async def retrieve(
        self, queries: QueryBundle | list[str]
    ) -> tuple[list[Candidate], list[str]]:
        """Search HadithAPI first, then use Brave strictly as fallback.

        QueryBundle is the current contract because it keeps language provenance.
        A list remains supported for legacy callers and goes directly to the
        discovery fallback rather than being mislabeled as English or Arabic.
        """

        errors: list[str] = []
        self.last_brave_request_count = 0
        self.last_brave_cache_hits = 0
        self.last_brave_cache_misses = 0
        all_queries = queries.all_queries if isinstance(queries, QueryBundle) else queries

        if isinstance(queries, QueryBundle) and self.hadith_api is not None:
            curated, curated_errors = await self._search_hadith_api(queries)
            errors.extend(curated_errors)
            if curated:
                return curated, errors

        discovered, discovery_errors = await self._search_brave(all_queries)
        errors.extend(discovery_errors)
        if not discovered:
            return [], errors

        # Brave results remain discovery-only unless Sunnah.com Official API is
        # configured and successfully validates the exact parsed reference.
        if not settings.sunnah_api_key:
            return discovered, errors

        official, official_errors = await self._validate_with_sunnah(discovered)
        errors.extend(official_errors)
        return (official if official else discovered), errors

    async def _search_hadith_api(
        self, queries: QueryBundle
    ) -> tuple[list[Candidate], list[str]]:
        if self.hadith_api is None:
            return [], []

        english = list(dict.fromkeys(q.strip() for q in queries.english_queries if q.strip()))
        arabic = list(dict.fromkeys(q.strip() for q in queries.arabic_queries if q.strip()))
        if not english or not arabic:
            return [], [
                "HadithAPI search skipped: safe English and Arabic semantic queries "
                "are both required."
            ]

        jobs: list[tuple[str, HadithAPISearchRequest, str]] = []
        for query in english:
            jobs.append(
                (
                    "hadithEnglish",
                    HadithAPISearchRequest(
                        hadith_english=query,
                        paginate=settings.sanad_hadith_api_page_size,
                    ),
                    query,
                )
            )
        for query in arabic:
            jobs.append(
                (
                    "hadithArabic",
                    HadithAPISearchRequest(
                        hadith_arabic=query,
                        paginate=settings.sanad_hadith_api_page_size,
                    ),
                    query,
                )
            )

        async def fetch(kind: str, request: HadithAPISearchRequest, query: str):
            try:
                items = await self.hadith_api.search(request, [query])
                for item in items:
                    item.retrieval_queries = list(
                        dict.fromkeys(item.retrieval_queries + [query])
                    )
                return items, None
            except Exception as exc:
                return [], (
                    f"HadithAPI {kind} search failed: "
                    f"{type(exc).__name__}: {exc}"
                )

        responses = await asyncio.gather(*(fetch(*job) for job in jobs))
        merged: dict[str, Candidate] = {}
        errors: list[str] = []
        for items, error in responses:
            if error:
                errors.append(error)
                continue
            for item in items:
                key = item.source_identifier or item.candidate_id
                existing = merged.get(key)
                if existing:
                    existing.retrieval_queries = list(
                        dict.fromkeys(
                            existing.retrieval_queries + item.retrieval_queries
                        )
                    )
                else:
                    merged[key] = item
        return list(merged.values()), errors

    async def _search_brave(
        self, queries: list[str]
    ) -> tuple[list[Candidate], list[str]]:
        try:
            # This legacy, Sunnah-specific discovery fallback shares the same
            # paid-search budget principle as broad discovery.
            bounded = queries[: settings.sanad_max_brave_requests]
            candidates = await self.discovery.search(bounded)
            self.last_brave_request_count = int(
                getattr(self.discovery, "request_count", len(bounded)) or 0
            )
            self.last_brave_cache_hits = int(
                getattr(self.discovery, "cache_hits", 0) or 0
            )
            self.last_brave_cache_misses = int(
                getattr(self.discovery, "cache_misses", self.last_brave_request_count)
                or 0
            )
            return candidates, []
        except Exception as exc:
            self.last_brave_request_count = int(
                getattr(self.discovery, "request_count", 0) or 0
            )
            self.last_brave_cache_hits = int(
                getattr(self.discovery, "cache_hits", 0) or 0
            )
            self.last_brave_cache_misses = int(
                getattr(self.discovery, "cache_misses", self.last_brave_request_count)
                or 0
            )
            return [], [
                f"Discovery provider failed: {type(exc).__name__}: {exc}"
            ]

    async def _validate_with_sunnah(
        self, discovered: list[Candidate]
    ) -> tuple[list[Candidate], list[str]]:
        refs: set[tuple[str, str]] = set()
        discovery_by_ref: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
        for candidate in discovered:
            ref = parse_sunnah_reference(candidate.source_url)
            if ref:
                refs.add(ref)
                discovery_by_ref[ref].append(candidate)

        if not refs:
            return [], []

        async def fetch(ref: tuple[str, str]):
            collection, number = ref
            try:
                return ref, await self.sunnah.fetch_by_reference(collection, number), None
            except Exception as exc:
                return (
                    ref,
                    [],
                    f"Sunnah API validation failed for {collection}:{number}: "
                    f"{type(exc).__name__}: {exc}",
                )

        validated_results = await asyncio.gather(*(fetch(ref) for ref in refs))
        evidence: list[Candidate] = []
        errors: list[str] = []
        for ref, items, error in validated_results:
            if error:
                errors.append(error)
                continue
            discovery_queries: list[str] = []
            for discovery_candidate in discovery_by_ref.get(ref, []):
                discovery_queries.extend(discovery_candidate.retrieval_queries)
            for item in items:
                item.retrieval_queries = list(dict.fromkeys(discovery_queries))
                evidence.append(item)

        return evidence, errors
