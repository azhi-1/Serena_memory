"""Embedding and rerank provider adapters.

The vector layer keeps external model APIs behind small, testable interfaces so
memory services do not depend on provider-specific payload details.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Optional, Protocol

import httpx


DEFAULT_SILICONFLOW_EMBEDDING_ENDPOINT = "https://api.siliconflow.cn/v1/embeddings"
DEFAULT_SILICONFLOW_RERANK_ENDPOINT = "https://api.siliconflow.cn/v1/rerank"
DEFAULT_SILICONFLOW_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_SILICONFLOW_RERANK_MODEL = "Qwen/Qwen3-Reranker-8B"


class ProviderConfigError(ValueError):
    """Raised when a provider is missing required configuration."""


class ProviderHTTPError(RuntimeError):
    """Raised when a provider returns a non-success HTTP response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Provider request failed with HTTP {status_code}: {detail}")


class ProviderResponseError(RuntimeError):
    """Raised when a provider response cannot be normalized safely."""


class AsyncHTTPClient(Protocol):
    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> Any:
        ...


@dataclass(frozen=True)
class RerankResult:
    index: int
    relevance_score: float
    document: Optional[str] = None


def _resolve_api_key(explicit_api_key: Optional[str]) -> str:
    api_key = (explicit_api_key or os.environ.get("SILICONFLOW_API_KEY") or "").strip()
    if not api_key:
        raise ProviderConfigError(
            "SiliconFlow API key is required. Set SILICONFLOW_API_KEY or pass api_key explicitly."
        )
    return api_key


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _finite_float_vector(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    vector: list[float] = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError):
            return []
        if number != number or number in (float("inf"), float("-inf")):
            return []
        vector.append(number)
    return vector


async def _post_json(
    client: Optional[AsyncHTTPClient],
    endpoint: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
) -> Any:
    if client is not None:
        response = await client.post(endpoint, headers=headers, json=payload, timeout=timeout)
    else:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=timeout,
            )

    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code < 200 or status_code >= 300:
        try:
            detail = response.text
        except Exception:
            detail = ""
        raise ProviderHTTPError(status_code, detail[:500])

    try:
        return response.json()
    except Exception as exc:
        raise ProviderResponseError("Provider response was not valid JSON.") from exc


@dataclass(frozen=True)
class SiliconFlowEmbeddingProvider:
    """OpenAI-compatible SiliconFlow embedding adapter."""

    endpoint: str = DEFAULT_SILICONFLOW_EMBEDDING_ENDPOINT
    model: str = DEFAULT_SILICONFLOW_EMBEDDING_MODEL
    api_key: Optional[str] = None
    timeout: float = 30.0
    client: Optional[AsyncHTTPClient] = None

    async def embed(self, texts: list[str], *, dimensions: Optional[int] = None) -> list[list[float]]:
        normalized_texts = [str(text) for text in texts if str(text)]
        if not normalized_texts:
            return []

        endpoint = self.endpoint.strip()
        model = self.model.strip()
        if not endpoint:
            raise ProviderConfigError("Embedding endpoint is required.")
        if not model:
            raise ProviderConfigError("Embedding model is required.")

        payload: dict[str, Any] = {
            "model": model,
            "input": normalized_texts,
        }
        if dimensions is not None:
            if dimensions <= 0:
                raise ProviderConfigError("Embedding dimensions must be positive.")
            payload["dimensions"] = dimensions

        payload_json = await _post_json(
            self.client,
            endpoint,
            _auth_headers(_resolve_api_key(self.api_key)),
            payload,
            self.timeout,
        )
        return _normalize_embedding_response(
            payload_json,
            expected_count=len(normalized_texts),
            expected_dimensions=dimensions,
        )


def _normalize_embedding_response(
    payload: Any,
    *,
    expected_count: int,
    expected_dimensions: Optional[int],
) -> list[list[float]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ProviderResponseError("Embedding response is missing data list.")

    by_index: dict[int, list[float]] = {}
    for fallback_index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ProviderResponseError("Embedding response item must be an object.")
        raw_index = item.get("index", fallback_index)
        if not isinstance(raw_index, int):
            raise ProviderResponseError("Embedding response item index must be an integer.")
        vector = _finite_float_vector(item.get("embedding"))
        if not vector:
            raise ProviderResponseError("Embedding response item has no valid embedding vector.")
        if expected_dimensions is not None and len(vector) != expected_dimensions:
            raise ProviderResponseError(
                f"Embedding dimension mismatch: expected {expected_dimensions}, got {len(vector)}."
            )
        by_index[raw_index] = vector

    missing = [index for index in range(expected_count) if index not in by_index]
    if missing:
        raise ProviderResponseError(f"Embedding response missing indexes: {missing}.")
    return [by_index[index] for index in range(expected_count)]


@dataclass(frozen=True)
class SiliconFlowRerankProvider:
    """SiliconFlow rerank adapter."""

    endpoint: str = DEFAULT_SILICONFLOW_RERANK_ENDPOINT
    model: str = DEFAULT_SILICONFLOW_RERANK_MODEL
    api_key: Optional[str] = None
    timeout: float = 30.0
    client: Optional[AsyncHTTPClient] = None

    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: Optional[int] = None,
        instruction: Optional[str] = None,
    ) -> list[RerankResult]:
        query_text = str(query or "").strip()
        normalized_documents = [str(document) for document in documents if str(document)]
        if not query_text or not normalized_documents:
            return []

        endpoint = self.endpoint.strip()
        model = self.model.strip()
        if not endpoint:
            raise ProviderConfigError("Rerank endpoint is required.")
        if not model:
            raise ProviderConfigError("Rerank model is required.")

        payload: dict[str, Any] = {
            "model": model,
            "query": query_text,
            "documents": normalized_documents,
        }
        if top_n is not None:
            if top_n <= 0:
                raise ProviderConfigError("Rerank top_n must be positive.")
            payload["top_n"] = top_n
        if instruction:
            payload["instruction"] = instruction

        payload_json = await _post_json(
            self.client,
            endpoint,
            _auth_headers(_resolve_api_key(self.api_key)),
            payload,
            self.timeout,
        )
        return _normalize_rerank_response(payload_json, document_count=len(normalized_documents))


def _normalize_rerank_response(payload: Any, *, document_count: int) -> list[RerankResult]:
    if not isinstance(payload, dict):
        raise ProviderResponseError("Rerank response must be an object.")
    raw_results = payload.get("results")
    if raw_results is None and isinstance(payload.get("data"), dict):
        raw_results = payload["data"].get("results")
    if raw_results is None:
        raw_results = payload.get("data")
    if not isinstance(raw_results, list):
        raise ProviderResponseError("Rerank response is missing results list.")

    normalized: list[RerankResult] = []
    for fallback_index, item in enumerate(raw_results):
        if not isinstance(item, dict):
            raise ProviderResponseError("Rerank result item must be an object.")
        raw_index = item.get("index", item.get("document_index", fallback_index))
        try:
            index = int(raw_index)
        except (TypeError, ValueError) as exc:
            raise ProviderResponseError("Rerank result index must be an integer.") from exc
        if index < 0 or index >= document_count:
            raise ProviderResponseError(f"Rerank result index out of range: {index}.")

        raw_score = item.get("relevance_score", item.get("relevanceScore", item.get("score")))
        try:
            score = float(raw_score)
        except (TypeError, ValueError) as exc:
            raise ProviderResponseError("Rerank result relevance_score must be numeric.") from exc
        if score != score or score in (float("inf"), float("-inf")):
            raise ProviderResponseError("Rerank result relevance_score must be finite.")

        document_value = item.get("document")
        normalized.append(
            RerankResult(
                index=index,
                relevance_score=score,
                document=str(document_value) if document_value is not None else None,
            )
        )
    return normalized
