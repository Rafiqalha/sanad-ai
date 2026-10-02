from __future__ import annotations

import re
from rapidfuzz.fuzz import token_set_ratio

from .config import settings
from .schemas import Candidate, RankingFeatures, ReconstructedClaim, RetrievalMode


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\b[\w'-]+\b", (text or "").casefold()))


class Reranker:
    def __init__(self):
        self._semantic_model = None
        if settings.sanad_enable_semantic_rerank:
            try:
                from sentence_transformers import SentenceTransformer
                self._semantic_model = SentenceTransformer(settings.sanad_semantic_model)
            except Exception:
                self._semantic_model = None

    def rank(
        self,
        claim: ReconstructedClaim,
        candidates: list[Candidate],
    ) -> list[tuple[Candidate, RankingFeatures]]:
        if not candidates:
            return []

        semantic_scores: list[float] = [0.0] * len(candidates)
        if self._semantic_model is not None:
            texts = [c.retrieved_text or c.title or "" for c in candidates]
            try:
                import numpy as np
                q_emb = self._semantic_model.encode(
                    [claim.reconstructed_claim], normalize_embeddings=True
                )[0]
                d_emb = self._semantic_model.encode(
                    texts, normalize_embeddings=True
                )
                semantic_scores = [
                    float(max(0.0, min(1.0, np.dot(q_emb, emb))))
                    for emb in d_emb
                ]
            except Exception:
                semantic_scores = [0.0] * len(candidates)

        ranked = []

        for i, c in enumerate(candidates):
            text = c.retrieved_text or c.title or ""
            comparison_queries = [claim.reconstructed_claim] + c.retrieval_queries
            lexical = max(
                token_set_ratio(query, text) / 100.0
                for query in comparison_queries
            )

            semantic = semantic_scores[i] if self._semantic_model else lexical
            reference_match = (
                1.0
                if c.retrieval_mode == RetrievalMode.EXACT_REFERENCE
                and c.verse_key
                and c.source_identifier == f"quran:{c.verse_key}"
                else 0.0
            )
            if reference_match:
                lexical = max(lexical, 1.0)
                semantic = max(semantic, 1.0)

            candidate_tokens = _tokens(text)
            concept_overlap = max(
                len(_tokens(query) & candidate_tokens) / max(1, len(_tokens(query)))
                for query in comparison_queries
            )

            hypothesis_tokens = _tokens(claim.user_attribution_hypothesis or "")
            candidate_metadata_tokens = _tokens(
                " ".join(
                    value
                    for value in (c.collection, c.title, c.provider_name)
                    if value
                )
            )
            attribution_match = (
                len(hypothesis_tokens & candidate_metadata_tokens)
                / max(1, len(hypothesis_tokens))
                if hypothesis_tokens
                else 0.0
            )
            metadata_match = 1.0 if c.metadata_complete else 0.5
            multi_query = min(1.0, len(set(c.retrieval_queries)) / 3.0)

            score = (
                0.40 * semantic
                + 0.25 * max(lexical, concept_overlap)
                + 0.15 * attribution_match
                + 0.10 * metadata_match
                + 0.10 * multi_query
            )

            features = RankingFeatures(
                lexical_overlap=round(max(lexical, concept_overlap), 4),
                semantic_similarity=round(semantic, 4),
                attribution_match=attribution_match,
                metadata_match=metadata_match,
                multi_query_agreement=round(multi_query, 4),
                reference_match=reference_match,
                relevance_score=round(score, 4),
            )
            ranked.append((c, features))

        ranked.sort(key=lambda x: x[1].relevance_score, reverse=True)
        return ranked
