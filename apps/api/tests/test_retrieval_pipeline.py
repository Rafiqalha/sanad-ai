import httpx
import pytest

from sanad_core.config import settings
from sanad_core.providers.sunnah import SunnahAPIProvider
from sanad_core.retrieval import HadithRetrievalPipeline
from sanad_core.schemas import Candidate


class FakeDiscovery:
    async def search(self, queries):
        return [
            Candidate(
                candidate_id="discovery",
                provider_id="brave",
                provider_name="Brave Search",
                source_type="web_discovery",
                trust_tier=4,
                title="Synthetic discovery result",
                source_url="https://sunnah.com/testcollection:123",
                retrieval_queries=queries,
                metadata_complete=True,
            )
        ]


def _transport(collection="testcollection", number="123"):
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "collection": collection,
                "hadithNumber": number,
                "hadith": [
                    {"lang": "en", "body": "Synthetic fixture body.", "urn": 999}
                ],
            },
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_pipeline_promotes_only_matching_official_payload(monkeypatch):
    monkeypatch.setattr(settings, "sunnah_api_key", "private-test-key")
    pipeline = HadithRetrievalPipeline(
        discovery=FakeDiscovery(),
        sunnah=SunnahAPIProvider(transport=_transport()),
    )

    candidates, errors = await pipeline.retrieve(["synthetic query"])

    assert errors == []
    assert len(candidates) == 1
    assert candidates[0].provider_id == "sunnah"
    assert candidates[0].official_api_validated is True
    assert candidates[0].source_identifier == "testcollection:123"
    assert candidates[0].retrieval_queries == ["synthetic query"]


@pytest.mark.asyncio
async def test_pipeline_keeps_mismatched_payload_discovery_only(monkeypatch):
    monkeypatch.setattr(settings, "sunnah_api_key", "private-test-key")
    pipeline = HadithRetrievalPipeline(
        discovery=FakeDiscovery(),
        sunnah=SunnahAPIProvider(transport=_transport(number="124")),
    )

    candidates, errors = await pipeline.retrieve(["synthetic query"])

    assert len(candidates) == 1
    assert candidates[0].provider_id == "brave"
    assert candidates[0].official_api_validated is False
    assert any("does not match" in error for error in errors)
