from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse
import httpx

from .config import settings
from .providers.sunnah import parse_sunnah_reference
from .schemas import Candidate, LinkState, LinkValidation
from .source_registry import REGISTRY


_QURAN_DIRECT_PATH = re.compile(
    r"^/(?P<chapter>[1-9]|[1-9]\d|1[01]\d|11[0-4])/"
    r"(?P<verse>[1-9]\d{0,2})/?$"
)


def parse_quran_direct_reference(url: str) -> str | None:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() not in {"quran.com", "www.quran.com"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return None
    match = _QURAN_DIRECT_PATH.fullmatch(parsed.path)
    return (
        f"{match.group('chapter')}:{match.group('verse')}" if match else None
    )


class SourceLinkResolver:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    async def validate(self, candidate: Candidate) -> LinkValidation:
        url = candidate.source_url
        registration = REGISTRY.get(candidate.provider_id)

        if registration is None:
            return LinkValidation(
                state=LinkState.UNVERIFIED,
                original_url=url,
                provider_domain_match=False,
                link_provider=candidate.provider_id,
                notes=["Provider is not registered."],
            )

        parsed_url = urlparse(url)
        host = (parsed_url.hostname or "").lower()
        try:
            port = parsed_url.port
        except ValueError:
            port = -1
        if (
            parsed_url.scheme.lower() != "https"
            or parsed_url.username is not None
            or parsed_url.password is not None
            or port not in {None, 443}
        ):
            return LinkValidation(
                state=LinkState.UNVERIFIED,
                original_url=url,
                provider_domain_match=False,
                link_provider=candidate.provider_id,
                notes=["Candidate URL is not an approved HTTPS provider origin."],
            )

        if candidate.provider_id == "brave":
            sunnah_registration = REGISTRY.get("sunnah")
            target_match = bool(
                sunnah_registration and host in sunnah_registration.domains
            )
            return LinkValidation(
                state=LinkState.DISCOVERY_ONLY,
                original_url=url,
                provider_domain_match=target_match,
                link_provider=candidate.provider_id,
                notes=[
                    "Search-engine result only; not promoted to primary evidence."
                ],
            )

        if candidate.provider_id == "hadithapi":
            domain_match = host in registration.domains
            endpoint_match = (
                parsed_url.path.rstrip("/") == "/public/api/hadiths"
            )
            if not domain_match or not endpoint_match:
                return LinkValidation(
                    state=LinkState.UNVERIFIED,
                    original_url=url,
                    provider_domain_match=domain_match,
                    link_provider=candidate.provider_id,
                    notes=["HadithAPI provider link is outside the registered endpoint."],
                )
            if (
                candidate.provider_api_validated
                and candidate.metadata_complete
                and candidate.source_identifier
            ):
                return LinkValidation(
                    state=LinkState.VERIFIED_PROVIDER,
                    original_url=url,
                    final_url=url,
                    http_status=200,
                    provider_domain_match=True,
                    link_provider=candidate.provider_id,
                    notes=[
                        "Authenticated HadithAPI search returned this metadata.",
                        "The provider documents no canonical direct-item URL; "
                        "this is a provider-level link only.",
                    ],
                )
            return LinkValidation(
                state=LinkState.UNVERIFIED,
                original_url=url,
                provider_domain_match=True,
                link_provider=candidate.provider_id,
                notes=["HadithAPI metadata has not passed provider validation."],
            )

        domain_match = host in registration.domains
        if not domain_match:
            return LinkValidation(
                state=LinkState.UNVERIFIED,
                original_url=url,
                provider_domain_match=False,
                link_provider=candidate.provider_id,
                notes=["Candidate URL does not match the registered provider domain."],
            )

        try:
            async with httpx.AsyncClient(
                timeout=settings.sanad_http_timeout,
                follow_redirects=False,
                headers={"User-Agent": "SANAD-AI-Prototype/0.1"},
                transport=self._transport,
            ) as client:
                current_url = url
                for _ in range(6):
                    response = await client.get(current_url)
                    if not (300 <= response.status_code < 400):
                        break
                    location = response.headers.get("location")
                    if not location:
                        break
                    next_url = urljoin(str(response.url), location)
                    next_parsed = urlparse(next_url)
                    next_host = (next_parsed.hostname or "").lower()
                    try:
                        next_port = next_parsed.port
                    except ValueError:
                        next_port = -1
                    if (
                        next_parsed.scheme.lower() != "https"
                        or next_parsed.username is not None
                        or next_parsed.password is not None
                        or next_port not in {None, 443}
                        or next_host not in registration.domains
                    ):
                        return LinkValidation(
                            state=LinkState.UNVERIFIED,
                            original_url=url,
                            final_url=next_url,
                            http_status=response.status_code,
                            provider_domain_match=False,
                            link_provider=candidate.provider_id,
                            notes=[
                                "Link redirected outside the registered provider."
                            ],
                        )
                    current_url = next_url
                else:
                    return LinkValidation(
                        state=LinkState.UNVERIFIED,
                        original_url=url,
                        final_url=current_url,
                        provider_domain_match=True,
                        link_provider=candidate.provider_id,
                        notes=["Link exceeded the permitted redirect limit."],
                    )

                final_url = str(response.url)
                status = response.status_code
                final_host = (response.url.host or "").lower()
                final_match = final_host in registration.domains
                final_scheme = response.url.scheme.lower()
        except Exception as exc:
            return LinkValidation(
                state=LinkState.UNVERIFIED,
                original_url=url,
                provider_domain_match=True,
                link_provider=candidate.provider_id,
                notes=[f"Link check failed: {type(exc).__name__}: {exc}"],
            )

        if status == 200 and final_match and final_scheme == "https":
            notes: list[str] = []
            state = LinkState.VERIFIED_PROVIDER

            if candidate.provider_id == "sunnah":
                expected_ref = None
                if candidate.collection and candidate.item_number:
                    expected_ref = (
                        candidate.collection.strip().casefold(),
                        candidate.item_number.strip(),
                    )
                original_ref = parse_sunnah_reference(url)
                final_ref = parse_sunnah_reference(final_url)
                expected_identifier = (
                    f"{expected_ref[0]}:{expected_ref[1]}" if expected_ref else None
                )
                exact_item_match = bool(
                    expected_ref
                    and original_ref == expected_ref
                    and final_ref == expected_ref
                    and candidate.source_identifier == expected_identifier
                )
                if (
                    exact_item_match
                    and candidate.official_api_validated
                    and candidate.metadata_complete
                ):
                    state = LinkState.VERIFIED_DIRECT
                else:
                    notes.append(
                        "Provider page resolved, but exact item identity was not verified."
                    )
            elif candidate.provider_id == "quran_foundation":
                expected_key = candidate.verse_key
                response_body = response.text
                final_ref = parse_quran_direct_reference(final_url)
                # Quran.com may redirect a numeric chapter/verse route to a
                # human-readable slug. In that case, require an explicit
                # same-verse marker in the live page instead of trusting the
                # redirect target alone.
                page_identity_match = bool(
                    expected_key
                    and re.search(
                        rf"(?:data-verse-key=[\"']|[\"']verse_key[\"']\s*:\s*[\"'])"
                        rf"{re.escape(expected_key)}[\"']",
                        response_body,
                        re.IGNORECASE,
                    )
                )
                exact_item_match = bool(
                    expected_key
                    and parse_quran_direct_reference(url) == expected_key
                    and (final_ref == expected_key or page_identity_match)
                    and candidate.source_identifier == f"quran:{expected_key}"
                )
                if (
                    exact_item_match
                    and candidate.canonical_provider_validated
                    and candidate.metadata_complete
                ):
                    state = LinkState.VERIFIED_DIRECT
                else:
                    notes.append(
                        "Halaman Quran.com aktif, tetapi identitas ayat langsung "
                        "belum tervalidasi."
                    )

            return LinkValidation(
                state=state,
                original_url=url,
                final_url=final_url,
                http_status=status,
                provider_domain_match=True,
                link_provider=candidate.provider_id,
                exact_identity_match=(state == LinkState.VERIFIED_DIRECT),
                notes=notes,
            )

        return LinkValidation(
            state=LinkState.BROKEN if status >= 400 else LinkState.UNVERIFIED,
            original_url=url,
            final_url=final_url,
            http_status=status,
            provider_domain_match=final_match,
            link_provider=candidate.provider_id,
            notes=["Direct link did not pass validation."],
        )


# Backward-compatible name retained for existing integrations and gold tests.
DirectLinkValidator = SourceLinkResolver
