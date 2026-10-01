import httpx
import pytest

from sanad_core.link_validator import DirectLinkValidator
from sanad_core.schemas import Candidate, LinkState


def _candidate(**changes):
    values = {
        "candidate_id": "synthetic",
        "provider_id": "sunnah",
        "provider_name": "Sunnah.com Official API",
        "source_type": "hadith",
        "trust_tier": 1,
        "collection": "testcollection",
        "item_number": "123",
        "retrieved_text": "Synthetic fixture body.",
        "source_url": "https://sunnah.com/testcollection:123",
        "source_identifier": "testcollection:123",
        "metadata_complete": True,
        "official_api_validated": True,
    }
    values.update(changes)
    return Candidate(**values)


def _transport(status=200, redirect_to=None):
    def handler(request: httpx.Request):
        if redirect_to and str(request.url) != redirect_to:
            return httpx.Response(302, headers={"Location": redirect_to})
        return httpx.Response(status)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_exact_final_item_can_be_verified_direct():
    result = await DirectLinkValidator(transport=_transport()).validate(_candidate())
    assert result.state == LinkState.VERIFIED_DIRECT


@pytest.mark.asyncio
async def test_provider_homepage_is_never_verified_direct():
    candidate = _candidate(source_url="https://sunnah.com/")
    result = await DirectLinkValidator(transport=_transport()).validate(candidate)
    assert result.state == LinkState.VERIFIED_PROVIDER


@pytest.mark.asyncio
async def test_redirect_to_different_item_is_not_verified_direct():
    target = "https://sunnah.com/testcollection:124"
    result = await DirectLinkValidator(
        transport=_transport(redirect_to=target)
    ).validate(_candidate())
    assert result.state == LinkState.VERIFIED_PROVIDER
    assert result.final_url == target


@pytest.mark.asyncio
async def test_same_provider_redirect_to_exact_item_can_be_verified_direct():
    candidate = _candidate(source_url="https://www.sunnah.com/testcollection:123")
    target = "https://sunnah.com/testcollection:123"
    result = await DirectLinkValidator(
        transport=_transport(redirect_to=target)
    ).validate(candidate)
    assert result.state == LinkState.VERIFIED_DIRECT
    assert result.final_url == target


@pytest.mark.asyncio
async def test_cross_domain_redirect_is_unverified():
    target = "https://example.com/elsewhere"
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": target})

    result = await DirectLinkValidator(transport=httpx.MockTransport(handler)).validate(
        _candidate()
    )
    assert result.state == LinkState.UNVERIFIED
    assert result.provider_domain_match is False
    assert len(requests) == 1
    assert requests[0].url.host == "sunnah.com"


@pytest.mark.asyncio
async def test_identifier_mismatch_is_not_verified_direct():
    candidate = _candidate(source_identifier="testcollection:999")
    result = await DirectLinkValidator(transport=_transport()).validate(candidate)
    assert result.state == LinkState.VERIFIED_PROVIDER


@pytest.mark.asyncio
async def test_broken_exact_item_is_broken():
    result = await DirectLinkValidator(transport=_transport(status=404)).validate(
        _candidate()
    )
    assert result.state == LinkState.BROKEN


@pytest.mark.asyncio
async def test_no_content_response_is_not_verified_direct():
    result = await DirectLinkValidator(transport=_transport(status=204)).validate(
        _candidate()
    )
    assert result.state == LinkState.UNVERIFIED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://user@sunnah.com/testcollection:123",
        "https://sunnah.com:8443/testcollection:123",
    ],
)
async def test_noncanonical_origin_is_unverified(url):
    result = await DirectLinkValidator(transport=_transport()).validate(
        _candidate(source_url=url)
    )
    assert result.state == LinkState.UNVERIFIED


@pytest.mark.asyncio
async def test_discovery_lookalike_domain_does_not_match_provider():
    candidate = Candidate(
        candidate_id="discovery",
        provider_id="brave",
        provider_name="Brave Search",
        source_type="web_discovery",
        source_url="https://evil-sunnah.com/testcollection:123",
    )
    result = await DirectLinkValidator().validate(candidate)
    assert result.state == LinkState.DISCOVERY_ONLY
    assert result.provider_domain_match is False
