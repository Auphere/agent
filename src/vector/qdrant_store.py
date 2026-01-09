from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from langchain_openai import OpenAIEmbeddings

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger


logger = get_logger("qdrant-store")


def _is_valid_http_url(value: str) -> bool:
    v = (value or "").strip()
    if not v:
        return False
    try:
        parsed = urlparse(v)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.netloc:
        return False
    return True


def _distance_from_string(value: str) -> qmodels.Distance:
    v = (value or "").lower().strip()
    if v == "dot":
        return qmodels.Distance.DOT
    if v == "euclid":
        return qmodels.Distance.EUCLID
    return qmodels.Distance.COSINE


@dataclass(frozen=True)
class PlanVectorDoc:
    id: str
    user_id: str
    title: str
    city: Optional[str]
    tags: List[str]
    stop_names: List[str]
    updated_at: Optional[str]

    def to_text(self) -> str:
        parts: List[str] = []
        if self.title:
            parts.append(f"Título: {self.title}")
        if self.city:
            parts.append(f"Ciudad: {self.city}")
        if self.tags:
            parts.append("Tags: " + ", ".join(self.tags))
        if self.stop_names:
            parts.append("Paradas: " + " → ".join(self.stop_names))
        return "\n".join(parts).strip()

    def to_payload(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "plan_id": self.id,
            "title": self.title,
            "city": self.city,
            "tags": self.tags,
            "stop_names": self.stop_names,
            "updated_at": self.updated_at,
            "doc_type": "plan",
        }


class QdrantStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        qdrant_url = (self.settings.qdrant_url or "").strip()
        self.enabled = bool(self.settings.qdrant_enabled and _is_valid_http_url(qdrant_url) and self.settings.openai_api_key)

        self._client: Optional[QdrantClient] = None
        self._embeddings: Optional[OpenAIEmbeddings] = None

        if self.settings.qdrant_enabled and not self.enabled:
            logger.warning(
                "qdrant-disabled",
                reason="invalid_config_or_missing_openai_key",
                qdrant_url=self.settings.qdrant_url,
                has_openai_api_key=bool(self.settings.openai_api_key),
            )

        if self.enabled:
            self._client = QdrantClient(
                url=qdrant_url,
                api_key=self.settings.qdrant_api_key,
                timeout=5.0,
            )
            self._embeddings = OpenAIEmbeddings(
                model=self.settings.embeddings_model,
                api_key=self.settings.openai_api_key,
            )

    def disable(self, reason: str, exc: Exception | None = None) -> None:
        """
        Disable Qdrant for this process.
        Qdrant is an optional dependency; we must never block the service startup on it.
        """
        self.enabled = False
        self._client = None
        self._embeddings = None
        logger.warning(
            "qdrant-disabled-runtime",
            reason=reason,
            qdrant_url=self.settings.qdrant_url,
            error=str(exc) if exc else None,
        )

    def ensure_collections(self) -> None:
        """Idempotent setup for required collections."""
        if not self.enabled or not self._client:
            return

        try:
            distance = _distance_from_string(self.settings.qdrant_distance)

            def _ensure(name: str) -> None:
                try:
                    self._client.get_collection(name)
                    return
                except UnexpectedResponse as exc:
                    # Treat 404 as "needs creation"; bubble up other cases
                    if getattr(exc, "status_code", None) != 404:
                        raise
                except Exception:
                    # Older client/server mismatches may throw other errors; fall through to create
                    pass

                try:
                    self._client.create_collection(
                        collection_name=name,
                        vectors_config=qmodels.VectorParams(
                            size=int(self.settings.embeddings_dimensions),
                            distance=distance,
                        ),
                    )
                except UnexpectedResponse as exc:
                    # If the collection already exists, consider it a success (idempotent ensure)
                    if getattr(exc, "status_code", None) != 409:
                        raise

            _ensure(self.settings.qdrant_collection_plans)
            _ensure(self.settings.qdrant_collection_user_profiles)
            _ensure(self.settings.qdrant_collection_places)

            logger.info(
                "qdrant-ready",
                url=self.settings.qdrant_url,
                collections={
                    "plans": self.settings.qdrant_collection_plans,
                    "user_profiles": self.settings.qdrant_collection_user_profiles,
                    "places": self.settings.qdrant_collection_places,
                },
                model=self.settings.embeddings_model,
                dims=self.settings.embeddings_dimensions,
                distance=self.settings.qdrant_distance,
            )
        except Exception as exc:
            # Do not crash the application lifecycle if Qdrant is down/misconfigured.
            self.disable(reason="ensure_collections_failed", exc=exc)
            return

    def upsert_plan(self, doc: PlanVectorDoc) -> None:
        if not self.enabled or not self._client or not self._embeddings:
            return

        text = doc.to_text()
        vector = self._embeddings.embed_query(text)
        if len(vector) != int(self.settings.embeddings_dimensions):
            raise ValueError("Embeddings dimension mismatch")

        self._client.upsert(
            collection_name=self.settings.qdrant_collection_plans,
            points=[
                qmodels.PointStruct(
                    id=doc.id,
                    vector=vector,
                    payload=doc.to_payload(),
                )
            ],
        )

    def search_plans(self, user_id: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        if not self.enabled or not self._client or not self._embeddings:
            return []

        vector = self._embeddings.embed_query(query)
        hits = self._client.search(
            collection_name=self.settings.qdrant_collection_plans,
            query_vector=vector,
            limit=max(1, min(int(limit), 25)),
            query_filter=qmodels.Filter(
                must=[qmodels.FieldCondition(key="user_id", match=qmodels.MatchValue(value=user_id))]
            ),
        )

        results: List[Dict[str, Any]] = []
        for h in hits:
            payload = h.payload or {}
            results.append(
                {
                    "plan_id": payload.get("plan_id") or str(h.id),
                    "title": payload.get("title"),
                    "city": payload.get("city"),
                    "tags": payload.get("tags") or [],
                    "score": float(h.score) if h.score is not None else None,
                }
            )
        return results


_STORE: Optional[QdrantStore] = None


def get_qdrant_store(settings: Settings | None = None) -> QdrantStore:
    global _STORE
    if _STORE is None:
        _STORE = QdrantStore(settings=settings)
    return _STORE


