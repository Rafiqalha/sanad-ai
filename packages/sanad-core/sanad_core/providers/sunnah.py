from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from ..config import settings
from ..schemas import Candidate, SourceClass
from .base import EvidenceProvider


COLON_REF = re.compile(
    r"^/(?P<collection>[A-Za-z0-9_-]+):(?P<number>[A-Za-z0-9_.-]+)/?$"
)
COLLECTION_COMPONENT = re.compile(r"^[A-Za-z0-9_-]+$")
NUMBER_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def _normalize_reference_components(collection: str, number: str) -> tuple[str, str]:
    normalized_collection = collection.strip().casefold()
    normalized_number = number.strip()
    if not COLLECTION_COMPONENT.fullmatch(normalized_collection):
        raise ValueError("Invalid Sunnah collection reference component.")
    if not NUMBER_COMPONENT.fullmatch(normalized_number):
        raise ValueError("Invalid Sunnah hadith-number reference component.")
    return normalized_collection, normalized_number


def parse_sunnah_reference(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return None
    if host not in {"sunnah.com", "www.sunnah.com", "beta.sunnah.com"}:
        return None
    m = COLON_REF.match(parsed.path)
    if not m:
        return None
    return m.group("collection").lower(), m.group("number")


class SunnahAPIProvider(EvidenceProvider):
    provider_id = "sunnah"
    base_url = "https://api.sunnah.com/v1"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    async def fetch_by_reference(
        self, collection: str, hadith_number: str
    ) -> list[Candidate]:
        if not settings.sunnah_api_key:
            raise RuntimeError("SUNNAH_API_KEY is not configured.")

        collection, hadith_number = _normalize_reference_components(
            collection, hadith_number
        )

        endpoint = (
            f"{self.base_url}/collections/{collection}/hadiths/{hadith_number}"
        )
        headers = {"X-API-Key": settings.sunnah_api_key}

        async with httpx.AsyncClient(
            timeout=settings.sanad_http_timeout,
            follow_redirects=False,
            transport=self._transport,
        ) as client:
            response = await client.get(endpoint, headers=headers)
            if response.status_code == 404:
                return []
            response.raise_for_status()
            payload = response.json()

        return self._normalize(payload, collection, hadith_number)

    def _normalize(
        self, payload: dict, collection: str, hadith_number: str
    ) -> list[Candidate]:
        if not isinstance(payload, dict):
            raise ValueError("Sunnah API response must be a JSON object.")

        payload_collection = payload.get("collection")
        payload_number = payload.get("hadithNumber")
        if not isinstance(payload_collection, str) or not payload_collection.strip():
            raise ValueError("Sunnah API response is missing collection metadata.")
        if not isinstance(payload_number, str) or not payload_number.strip():
            raise ValueError("Sunnah API response is missing hadithNumber metadata.")

        normalized_collection, normalized_number = _normalize_reference_components(
            collection, hadith_number
        )
        if payload_collection.strip().casefold() != normalized_collection:
            raise ValueError("Sunnah API collection does not match the requested reference.")
        if payload_number.strip() != normalized_number:
            raise ValueError(
                "Sunnah API hadithNumber does not match the requested reference."
            )

        bodies = payload.get("hadith")
        if not isinstance(bodies, list) or not bodies:
            raise ValueError("Sunnah API response contains no hadith entries.")

        canonical_identifier = f"{normalized_collection}:{normalized_number}"
        direct_url = f"https://sunnah.com/{canonical_identifier}"
        out: list[Candidate] = []

        for entry in bodies:
            if not isinstance(entry, dict):
                continue
            lang = entry.get("lang")
            body = entry.get("body")
            if not isinstance(lang, str) or not lang.strip():
                continue
            if not isinstance(body, str) or not body.strip():
                continue
            urn = entry.get("urn")
            grades = entry.get("grades") or []
            cid_src = f"{canonical_identifier}:{lang}:{urn}"
            cid = hashlib.sha1(cid_src.encode("utf-8")).hexdigest()[:16]
            out.append(
                Candidate(
                    candidate_id=f"sunnah-{cid}",
                    provider_id="sunnah",
                    provider_name="Sunnah.com Official API",
                    source_type="hadith",
                    trust_tier=1,
                    title=None,
                    collection=normalized_collection,
                    chapter=entry.get("chapterTitle"),
                    item_number=normalized_number,
                    language=lang.strip(),
                    retrieved_text=body.strip(),
                    source_url=direct_url,
                    source_domain="sunnah.com",
                    source_class=SourceClass.PRIMARY_RELIGIOUS_SOURCE,
                    retrieved_at=datetime.now(timezone.utc),
                    source_identifier=canonical_identifier,
                    metadata_complete=True,
                    official_api_validated=True,
                    raw={
                        "urn": urn,
                        "grades": grades,
                        "bookNumber": payload.get("bookNumber"),
                        "chapterId": payload.get("chapterId"),
                        "api_payload": payload,
                    },
                )
            )
        if not out:
            raise ValueError("Sunnah API response contains no usable hadith entries.")
        return out
