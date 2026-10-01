from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sanad_core.config import settings
from sanad_core.intent import IntentEngine
from sanad_core.orchestrator import SanadOrchestrator
from sanad_core.query_generator import QueryGenerator


QUERIES = [
    (
        "Katanya kalau orang mencari ilmu dimudahkan jalan menuju surga, "
        "hadisnya dari mana?"
    ),
    "Ada hadis tentang amal tergantung niat?",
    "Hadis yang bilang agama itu nasihat apa sumbernya?",
    "Ada hadis bahwa Allah melihat hati dan amal, bukan penampilan?",
    "Hadis yang ada kata dunia penjara orang mukmin itu apa ya?",
    "Yang tentang orang kuat bukan yang menang bergulat itu hadis mana?",
]


def _candidate_summary(item):
    candidate = item.candidate
    return {
        "provider": candidate.provider_id,
        "source_identifier": candidate.source_identifier,
        "collection": candidate.collection,
        "chapter": candidate.chapter,
        "item_number": candidate.item_number,
        "language": candidate.language,
        "title": candidate.title,
        "retrieved_text": candidate.retrieved_text,
        "retrieved_texts": candidate.retrieved_texts,
        "provider_metadata": candidate.raw,
        "provider_api_validated": candidate.provider_api_validated,
        "official_api_validated": candidate.official_api_validated,
        "ranking": item.ranking.model_dump(mode="json"),
        "evidence_relation": item.relationship.value,
        "link_state": item.link.state.value,
        "provider_link": item.link.final_url or item.link.original_url,
        "link_notes": item.link.notes,
        "limitations": item.limitations,
    }


async def main():
    print("SANAD.AI temporary HadithAPI provider smoke test")
    print("================================================")
    print(
        "HADITH_API_KEY:",
        "CONFIGURED" if settings.hadith_api_key else "MISSING",
    )
    print(
        "BRAVE_SEARCH_API_KEY:",
        "CONFIGURED" if settings.brave_search_api_key else "MISSING",
    )
    print(
        "SUNNAH_API_KEY:",
        "CONFIGURED" if settings.sunnah_api_key else "MISSING",
    )

    # Stop before constructing/running the network pipeline. This guarantees no
    # Brave fallback or other API request occurs when HadithAPI is unconfigured.
    if not settings.hadith_api_key:
        raise SystemExit(
            "LIVE_BLOCKED: HADITH_API_KEY is missing; no API call was made."
        )

    intent_engine = IntentEngine()
    query_generator = QueryGenerator()
    orchestrator = SanadOrchestrator(
        intent_engine=intent_engine,
        query_generator=query_generator,
    )
    results = []
    total_started = time.perf_counter()

    for text in QUERIES:
        intent = intent_engine.analyze(text)
        claim = intent_engine.reconstruct(intent)
        bundle = query_generator.generate(claim)
        started = time.perf_counter()
        response = await orchestrator.search(text)
        elapsed_ms = (time.perf_counter() - started) * 1000
        results.append(
            {
                "input": text,
                "understood_intent": intent.primary_intent,
                "reconstructed_claim": claim.reconstructed_claim,
                "domain": claim.domain.value,
                "queries": {
                    "indonesian": bundle.indonesian_queries,
                    "english_for_hadithapi": bundle.english_queries,
                    "arabic_for_hadithapi": bundle.arabic_queries,
                    "concept": bundle.concept_queries,
                    "attribution_neutral": bundle.attribution_neutral_queries,
                    "attribution_signal": bundle.attribution_signal_queries,
                },
                "response_time_ms": round(elapsed_ms, 2),
                "final_status": response.status.value,
                "provider_errors": response.provider_errors,
                "evidence": [_candidate_summary(item) for item in response.evidence],
            }
        )

    print(
        json.dumps(
            {
                "total_response_time_ms": round(
                    (time.perf_counter() - total_started) * 1000, 2
                ),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
