from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import json

from sanad_core.orchestrator import SanadOrchestrator
from sanad_core.config import settings
from sanad_core.evidence import eligible_for_primary_evidence
from sanad_core.providers.sunnah import parse_sunnah_reference
from sanad_core.schemas import (
    Domain,
    EvidenceItem,
    EvidenceRelation,
    FinalResponse,
    FinalStatus,
    LinkState,
)


QUERY = (
    "Katanya kalau orang mencari ilmu dimudahkan jalan menuju surga, "
    "hadisnya dari mana?"
)


def _has_coherent_direct_reference(item: EvidenceItem) -> bool:
    candidate = item.candidate
    if not candidate.collection or not candidate.item_number:
        return False
    expected = (
        candidate.collection.strip().casefold(),
        candidate.item_number.strip(),
    )
    final_url = item.link.final_url or item.link.original_url
    return bool(
        parse_sunnah_reference(final_url) == expected
        and candidate.source_identifier == f"{expected[0]}:{expected[1]}"
    )


def smoke_gate_failures(result: FinalResponse) -> list[str]:
    failures: list[str] = []
    if result.domain != Domain.HADITH:
        failures.append("The smoke query was not routed to HADITH.")
    if result.status not in {
        FinalStatus.SUCCESS,
        FinalStatus.PARTIAL_PROVIDER_FAILURE,
    }:
        failures.append(f"Final status is not live-ready: {result.status.value}.")

    qualified = []
    for item in result.evidence:
        coherent = _has_coherent_direct_reference(item)
        eligible = eligible_for_primary_evidence(item.candidate, item.link)
        if item.link.state == LinkState.VERIFIED_DIRECT and not (
            coherent and eligible
        ):
            failures.append(
                "An item was labeled VERIFIED_DIRECT without coherent provenance."
            )
        if (
            item.relationship
            in {
                EvidenceRelation.DIRECT_MATCH,
                EvidenceRelation.STRONG_RELATED_MATCH,
            }
            and coherent
            and eligible
        ):
            qualified.append(item)

    if not qualified:
        failures.append("No qualified verified-direct evidence was produced.")
    return failures


async def main():
    print("SANAD.AI live smoke test")
    print("========================")
    print("Query:", QUERY)

    if not settings.brave_search_api_key:
        raise SystemExit("Missing BRAVE_SEARCH_API_KEY.")
    if not settings.sunnah_api_key:
        raise SystemExit("Missing SUNNAH_API_KEY.")

    result = await SanadOrchestrator().search(QUERY)

    print("\nStructured result:")
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))

    verified = [
        e for e in result.evidence
        if e.link.state.value == "VERIFIED_DIRECT"
    ]

    print("\nSmoke-test summary:")
    print("Status:", result.status.value)
    print("Evidence count:", len(result.evidence))
    print("Verified direct links:", len(verified))
    print("Provider errors:", len(result.provider_errors))

    if result.provider_errors:
        print("\nProvider errors:")
        for err in result.provider_errors:
            print("-", err)

    failures = smoke_gate_failures(result)
    if failures:
        print("\nGate: FAIL")
        for failure in failures:
            print("-", failure)
        raise SystemExit(1)

    gate = "PASS_WITH_PROVIDER_ERRORS" if result.provider_errors else "PASS"
    print("\nGate:", gate)


if __name__ == "__main__":
    asyncio.run(main())
