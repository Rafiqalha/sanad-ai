from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sanad_core.config import settings


def yn(x):
    return "CONFIGURED" if x else "MISSING"


print("SANAD.AI setup check")
print("====================")
print("OPENAI_API_KEY:", yn(settings.openai_api_key))
print("OPENAI_MODEL:", yn(settings.openai_model))
print("BRAVE_SEARCH_API_KEY:", yn(settings.brave_search_api_key))
print("HADITH_API_KEY:", yn(settings.hadith_api_key))
print("SUNNAH_API_KEY:", yn(settings.sunnah_api_key))
print("QURAN_FOUNDATION_CLIENT_ID:", yn(settings.quran_foundation_client_id))
print("QURAN_FOUNDATION_CLIENT_SECRET:", yn(settings.quran_foundation_client_secret))
print("OPENALEX_API_KEY:", yn(settings.openalex_api_key), "(optional)")
print("WIKIPEDIA_LANGS:", settings.wikipedia_langs)
print("CROSSREF_MAILTO:", yn(settings.crossref_mailto), "(optional/recommended)")
print("CROSSREF_USER_AGENT:", settings.crossref_user_agent)
print("Quran Foundation environment:", settings.quran_foundation_env)
print("HTTP timeout:", settings.sanad_http_timeout)
print("Max web results:", settings.sanad_max_web_results)
print("HadithAPI page size:", settings.sanad_hadith_api_page_size)
print("Quran max results:", settings.sanad_quran_max_results)
print("Scholarly max results:", settings.sanad_scholarly_max_results)
print("Max Brave requests per query:", settings.sanad_max_brave_requests)
print("Max fetched web pages:", settings.sanad_max_web_pages)
print("Broad web discovery enabled:", settings.sanad_enable_broad_web_discovery)
print(
    "History/academic retrieval enabled:",
    settings.sanad_enable_history_academic_retrieval,
)
print("Remote semantic API enabled:", settings.sanad_enable_remote_semantic)
print("Semantic rerank enabled:", settings.sanad_enable_semantic_rerank)

if not settings.brave_search_api_key:
    print("\nBLOCKER: live web discovery is unavailable.")
if not settings.hadith_api_key:
    print("BLOCKER: temporary HadithAPI curated search is unavailable.")
if not settings.sunnah_api_key:
    print("BLOCKER: official Sunnah API validation is unavailable.")
if not (
    settings.quran_foundation_client_id
    and settings.quran_foundation_client_secret
):
    print("BLOCKER: Quran Foundation live retrieval is unavailable.")
if not (settings.openai_api_key and settings.openai_model):
        print("NOTE: intent/query generation uses the local semantic/concept engine.")

if settings.hadith_api_key and settings.brave_search_api_key:
    print("\nTemporary provider path is credential-ready.")

if settings.brave_search_api_key and settings.sunnah_api_key:
    print("\nCore live hadith provider path is credential-ready.")

if (
    settings.quran_foundation_client_id
    and settings.quran_foundation_client_secret
):
    print("\nQuran Foundation provider path is credential-ready.")
