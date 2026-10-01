from __future__ import annotations

from fastapi.testclient import TestClient

import sanad_core.api as api_module
from sanad_core.intent import IntentEngine
from sanad_core.query_generator import QueryGenerator


client = TestClient(api_module.app)


def _provider_payload():
    return {
        "understood_intent": "Menelusuri sumber hadis tentang mencari ilmu.",
        "reconstructed_claim": "Mencari sumber riwayat tentang ilmu dan surga.",
        "domain": "HADITH",
        "evidence": [
            {
                "candidate": {
                    "candidate_id": "hadithapi-fixture",
                    "provider_id": "hadithapi",
                    "provider_name": "HadithAPI",
                    "source_type": "hadith_curated_secondary",
                    "trust_tier": 2,
                    "title": "Chapter on Knowledge",
                    "collection": "al-tirmidhi",
                    "chapter": "Chapter on Knowledge",
                    "item_number": "2646",
                    "language": "en+ar",
                    "retrieved_text": "Synthetic English fixture.",
                    "retrieved_texts": {
                        "en": "Synthetic English fixture.",
                        "ar": "نص تجريبي",
                    },
                    "source_url": "https://www.hadithapi.com/public/api/hadiths",
                    "source_identifier": "hadithapi:al-tirmidhi:2646",
                    "retrieval_queries": ["knowledge path paradise"],
                    "metadata_complete": True,
                    "provider_api_validated": True,
                    "official_api_validated": False,
                    "raw": {
                        "book_name": "Jami' Al-Tirmidhi",
                        "status": "sahih",
                    },
                },
                "ranking": {
                    "lexical_overlap": 0.8,
                    "semantic_similarity": 0.7,
                    "attribution_match": 0.0,
                    "metadata_match": 1.0,
                    "multi_query_agreement": 0.66,
                    "relevance_score": 0.68,
                },
                "link": {
                    "state": "VERIFIED_PROVIDER",
                    "original_url": "https://www.hadithapi.com/public/api/hadiths",
                    "final_url": "https://www.hadithapi.com/public/api/hadiths",
                    "http_status": 200,
                    "provider_domain_match": True,
                    "notes": ["Provider-level link only."],
                },
                "relationship": "PARTIAL_MATCH",
                "limitations": ["Not eligible for primary evidence."],
            }
        ],
        "limited_clarification": "Provider-level candidate only.",
        "expert_review_note": "Further interpretation requires an expert.",
        "status": "SOURCE_FOUND_LINK_UNVERIFIED",
        "provider_errors": [],
    }


class _Result:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, mode="python"):
        assert mode == "json"
        return self.payload


class _FakeOrchestrator:
    def __init__(self, payload):
        self.payload = payload
        self.received = []

    async def search(self, text):
        self.received.append(text)
        return _Result(self.payload)


def test_root_serves_required_ui():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    for expected in (
        "SANAD.AI",
        "Memahami maksud, menelusuri sumber, memperkuat tabayyun.",
        "Apa yang ingin Anda telusuri?",
        "Katanya kalau orang mencari ilmu dimudahkan jalan menuju surga",
        "Telusuri Sumber",
    ):
        assert expected in response.text


def test_root_is_independent_of_working_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "SANAD.AI" in response.text


def test_existing_health_and_search_routes_remain_reachable(monkeypatch):
    payload = _provider_payload()
    fake = _FakeOrchestrator(payload)
    monkeypatch.setattr(api_module, "orchestrator", fake)

    assert client.get("/health").json() == {"status": "ok", "version": "0.1.0"}
    response = client.post("/v1/search", json={"text": "fixture question"})

    assert response.status_code == 200
    assert response.json() == payload
    assert fake.received == ["fixture question"]


def test_search_api_preserves_provider_evidence_boundary(monkeypatch):
    payload = _provider_payload()
    monkeypatch.setattr(api_module, "orchestrator", _FakeOrchestrator(payload))

    response = client.post("/v1/search", json={"text": "fixture question"})
    candidate = response.json()["evidence"][0]["candidate"]
    link = response.json()["evidence"][0]["link"]

    assert candidate["collection"] == "al-tirmidhi"
    assert candidate["item_number"] == "2646"
    assert candidate["retrieved_texts"] == {
        "en": "Synthetic English fixture.",
        "ar": "نص تجريبي",
    }
    assert candidate["raw"]["status"] == "sahih"
    assert candidate["provider_name"] == "HadithAPI"
    assert candidate["official_api_validated"] is False
    assert link["state"] == "VERIFIED_PROVIDER"
    assert link["state"] != "VERIFIED_DIRECT"


def test_no_result_response_is_honest(monkeypatch):
    payload = {
        "understood_intent": "Menelusuri sumber yang dimaksud pengguna.",
        "reconstructed_claim": "Potongan yang belum dapat diidentifikasi.",
        "domain": "HADITH",
        "evidence": [],
        "limited_clarification": "Belum ditemukan sumber yang cukup relevan.",
        "expert_review_note": None,
        "status": "NO_RELIABLE_SOURCE_FOUND",
        "provider_errors": [],
    }
    monkeypatch.setattr(api_module, "orchestrator", _FakeOrchestrator(payload))

    body = client.post("/v1/search", json={"text": "unknown fixture"}).json()

    assert body["status"] == "NO_RELIABLE_SOURCE_FOUND"
    assert body["evidence"] == []
    serialized = str(body)
    assert "https://" not in serialized
    assert "hadithNumber" not in serialized


def test_backend_exception_is_sanitized(monkeypatch):
    class _FailingOrchestrator:
        async def search(self, text):
            raise RuntimeError("sentinel-private-secret")

    monkeypatch.setattr(api_module, "orchestrator", _FailingOrchestrator())
    isolated_client = TestClient(api_module.app, raise_server_exceptions=False)

    response = isolated_client.post("/v1/search", json={"text": "fixture"})

    assert response.status_code == 500
    assert "sentinel-private-secret" not in response.text


def test_frontend_uses_same_origin_backend_without_secrets_or_html_injection():
    html = client.get("/").text

    assert 'fetch("/v1/search"' in html
    for forbidden in (
        "HADITH_API_KEY",
        "BRAVE_SEARCH_API_KEY",
        "SUNNAH_API_KEY",
        "apiKey",
        "Authorization",
        "innerHTML",
        "insertAdjacentHTML",
        "document.write",
    ):
        assert forbidden not in html


def test_frontend_contains_required_evidence_copy_and_direct_link_guard():
    html = client.get("/").text

    assert "Terverifikasi pada provider" in html
    assert "Kandidat hasil penelusuran" in html
    assert "Belum ditemukan sumber yang memadai" in html
    assert "Sumber telah dicocokkan pada provider hadis terstruktur" in html
    assert 'link.state === "VERIFIED_DIRECT"' in html
    assert "candidate.official_api_validated === true" in html
    assert "candidate.canonical_provider_validated === true" in html
    assert "Boolean(link.link_validated_at)" in html
    assert "hadis pasti benar" not in html.casefold()


def test_frontend_is_indonesian_first_for_hadith_and_quran_cards():
    html = client.get("/").text

    for expected in (
        "Kitab",
        "Nomor hadis",
        "Grade/status provider",
        "Nama surah",
        "Nomor surah",
        "Nomor ayat",
        "Teks Arab",
        "Terjemahan Bahasa Indonesia",
        "Lihat teks Inggris provider (provenance)",
        "Sumber Qur’an belum dapat diakses saat ini.",
    ):
        assert expected in html
    assert "Top evidence" not in html


def test_frontend_never_contains_quran_credentials_or_token_headers():
    html = client.get("/").text

    for forbidden in (
        "QURAN_FOUNDATION_CLIENT_ID",
        "QURAN_FOUNDATION_CLIENT_SECRET",
        "x-auth-token",
        "x-client-id",
        "access_token",
    ):
        assert forbidden not in html


def test_v2_visual_contract_uses_requested_palette_and_simple_hero():
    html = client.get("/").text

    for color in ("#0e3b2e", "#216b52", "#a9c8b5", "#f7f6f0", "#ffffff"):
        assert color in html.casefold()
    assert '<h1 id="page-title">SANAD.AI</h1>' in html
    assert "Memahami maksud, menelusuri sumber, memperkuat tabayyun." in html
    for removed_copy in (
        "Maksud pengguna dipertahankan",
        "Status evidence ditampilkan apa adanya",
        "Evidence kurang akan dinyatakan jujur",
    ):
        assert removed_copy not in html


def test_v2_ui_maps_machine_states_to_plain_indonesian_labels():
    html = client.get("/").text

    for mapping in (
        'VERIFIED_DIRECT: "Sumber terverifikasi"',
        'VERIFIED_PROVIDER: "Terverifikasi pada provider"',
        'DISCOVERY_ONLY: "Hasil penelusuran web"',
        'NO_RELIABLE_SOURCE_FOUND: "Belum dapat diverifikasi"',
    ):
        assert mapping in html
    assert 'evidenceLabels[state] || "Status belum tersedia"' in html
    assert 'relationshipLabels[item?.relationship] || "Kandidat terkait"' in html


def test_v2_history_academic_cards_accept_provider_shape_and_guard_links():
    html = client.get("/").text

    for expected in (
        "Rujukan akademik dan ensiklopedis",
        "Sumber ensiklopedis sekunder",
        "Sumber akademik ini digunakan untuk konteks",
        "source?.page_title || source?.title",
        "source?.content_excerpt || source?.summary || source?.content",
        "Array.isArray(source?.authors)",
        "source?.validation_timestamp",
        "source?.canonical_url || source?.source_url",
        'sourceState === "DISCOVERY_ONLY"',
        "source?.http_status === 200",
        'rel = "noopener noreferrer"',
    ):
        assert expected in html


def test_v2_ui_has_desktop_mobile_and_arabic_readability_guards():
    html = client.get("/").text

    assert "@media (max-width: 720px)" in html
    assert "@media (max-width: 420px)" in html
    assert "@media (prefers-reduced-motion: reduce)" in html
    assert 'font-family: "Noto Naskh Arabic", Amiri, "Geeza Pro"' in html
    assert 'textNode.dir = "rtl"' in html
    assert 'textNode.setAttribute("translate", "no")' in html


def test_invalid_search_payload_is_rejected():
    assert client.post("/v1/search", json={}).status_code == 422


def test_main_demo_query_has_bounded_hadithapi_phrase_refinement():
    text = (
        "Katanya kalau orang mencari ilmu dimudahkan jalan menuju surga, "
        "hadisnya dari mana?"
    )
    intent_engine = IntentEngine()
    intent_engine._client = None
    query_generator = QueryGenerator()
    query_generator._client = None

    claim = intent_engine.reconstruct(intent_engine.analyze(text))
    bundle = query_generator.generate(claim)

    assert "path to Paradise" in bundle.english_queries
    assert len(bundle.english_queries) <= 2
