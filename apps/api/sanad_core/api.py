from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import settings
from .history_pipeline import IslamicHistoryPipeline
from .orchestrator import SanadOrchestrator
from .providers.broad_web import BroadWebDiscoveryProvider, WebPageRetriever
from .providers.crossref import CrossrefProvider
from .providers.mediawiki import MediaWikiProvider
from .providers.openalex import OpenAlexProvider
from .web_retrieval import WebDiscoveryPipeline


app = FastAPI(
    title="SANAD.AI Core",
    version="0.1.0",
    description="Intent-preserving source provenance retrieval proof-of-concept.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)

_broad_provider = BroadWebDiscoveryProvider()
_page_retriever = WebPageRetriever()
_web_retrieval = WebDiscoveryPipeline(
    provider=_broad_provider,
    page_retriever=_page_retriever,
)
_history_retrieval = None
if settings.sanad_enable_history_academic_retrieval:
    _history_retrieval = IslamicHistoryPipeline(
        mediawiki=MediaWikiProvider(
            languages=settings.wikipedia_langs,
            timeout=settings.sanad_http_timeout,
            max_results=settings.sanad_scholarly_max_results,
            cache_ttl_seconds=settings.sanad_knowledge_cache_ttl_seconds,
        ),
        openalex=OpenAlexProvider(
            api_key=settings.openalex_api_key,
            timeout=settings.sanad_http_timeout,
            max_results=settings.sanad_scholarly_max_results,
            cache_ttl_seconds=settings.sanad_knowledge_cache_ttl_seconds,
        ),
        crossref=CrossrefProvider(
            mailto=settings.crossref_mailto,
            user_agent=settings.crossref_user_agent,
            timeout=settings.sanad_http_timeout,
            max_results=settings.sanad_scholarly_max_results,
            cache_ttl_seconds=settings.sanad_knowledge_cache_ttl_seconds,
        ),
        broad_web_provider=_broad_provider,
        page_retriever=_page_retriever,
        max_queries=2,
        max_per_provider=settings.sanad_scholarly_max_results,
        max_broad_pages=settings.sanad_max_web_pages,
    )

orchestrator = SanadOrchestrator(
    web_retrieval=_web_retrieval,
    history_retrieval=_history_retrieval,
)
WEB_ROOT = Path(__file__).resolve().parent / "web"


class SearchRequest(BaseModel):
    text: str


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(WEB_ROOT / "index.html", media_type="text/html")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.post("/v1/search")
async def search(req: SearchRequest):
    result = await orchestrator.search(req.text)
    return result.model_dump(mode="json")
