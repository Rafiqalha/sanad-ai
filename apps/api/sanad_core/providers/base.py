from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..schemas import Candidate, QueryBundle


class DiscoveryProvider(ABC):
    @abstractmethod
    async def search(self, queries: list[str]) -> list[Candidate]:
        raise NotImplementedError


class EvidenceProvider(ABC):
    @abstractmethod
    async def fetch_by_reference(
        self, collection: str, hadith_number: str
    ) -> list[Candidate]:
        raise NotImplementedError


class CuratedSearchProvider(ABC):
    @abstractmethod
    async def search(self, request, retrieval_queries=None) -> list[Candidate]:
        raise NotImplementedError


class QuranEvidenceProvider(ABC):
    """Stable seam for Quran Foundation today and Kemenag/LPMQ later."""

    @abstractmethod
    async def retrieve(self, source_text: str, queries: QueryBundle) -> Any:
        raise NotImplementedError
