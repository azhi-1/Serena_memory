import pytest

from vector.providers import (
    ProviderConfigError,
    ProviderHTTPError,
    ProviderResponseError,
    SiliconFlowEmbeddingProvider,
    SiliconFlowRerankProvider,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def post(self, url, *, headers, json, timeout):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self.response


async def test_embedding_provider_returns_vectors_in_input_order():
    client = FakeClient(
        FakeResponse(
            payload={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0.3, 0.4]},
                    {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]},
                ],
                "usage": {"prompt_tokens": 7},
            }
        )
    )
    provider = SiliconFlowEmbeddingProvider(api_key="secret", client=client)

    vectors = await provider.embed(["first", "second"], dimensions=2)

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert client.calls[0]["json"] == {
        "model": "Qwen/Qwen3-Embedding-8B",
        "input": ["first", "second"],
        "dimensions": 2,
    }
    assert client.calls[0]["headers"]["Authorization"] == "Bearer secret"


async def test_embedding_provider_returns_empty_for_empty_input():
    client = FakeClient(FakeResponse(payload={"data": []}))
    provider = SiliconFlowEmbeddingProvider(api_key="secret", client=client)

    assert await provider.embed([]) == []
    assert client.calls == []


async def test_embedding_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    provider = SiliconFlowEmbeddingProvider(client=FakeClient(FakeResponse(payload={})))

    with pytest.raises(ProviderConfigError):
        await provider.embed(["hello"])


async def test_embedding_provider_raises_on_http_error():
    client = FakeClient(FakeResponse(status_code=401, payload={}, text="unauthorized"))
    provider = SiliconFlowEmbeddingProvider(api_key="secret", client=client)

    with pytest.raises(ProviderHTTPError) as exc:
        await provider.embed(["hello"])

    assert exc.value.status_code == 401


async def test_embedding_provider_rejects_malformed_response():
    client = FakeClient(FakeResponse(payload={"data": [{"index": 0, "embedding": ["bad"]}]}))
    provider = SiliconFlowEmbeddingProvider(api_key="secret", client=client)

    with pytest.raises(ProviderResponseError):
        await provider.embed(["hello"])


async def test_embedding_provider_rejects_dimension_mismatch():
    client = FakeClient(FakeResponse(payload={"data": [{"index": 0, "embedding": [0.1, 0.2]}]}))
    provider = SiliconFlowEmbeddingProvider(api_key="secret", client=client)

    with pytest.raises(ProviderResponseError):
        await provider.embed(["hello"], dimensions=3)


async def test_rerank_provider_normalizes_results():
    client = FakeClient(
        FakeResponse(
            payload={
                "id": "abc",
                "results": [
                    {"index": 0, "relevance_score": 0.91},
                    {"index": 1, "relevance_score": 0.22},
                ],
            }
        )
    )
    provider = SiliconFlowRerankProvider(api_key="secret", client=client)

    results = await provider.rerank(
        "query",
        ["doc-a", "doc-b", "doc-c"],
        top_n=2,
        instruction="prefer exact matches",
    )

    assert [(item.index, item.relevance_score) for item in results] == [(0, 0.91), (1, 0.22)]
    assert client.calls[0]["json"] == {
        "model": "Qwen/Qwen3-Reranker-8B",
        "query": "query",
        "documents": ["doc-a", "doc-b", "doc-c"],
        "top_n": 2,
        "instruction": "prefer exact matches",
    }


async def test_rerank_provider_returns_empty_without_query_or_documents():
    provider = SiliconFlowRerankProvider(api_key="secret", client=FakeClient(FakeResponse(payload={})))

    assert await provider.rerank("", ["doc"]) == []
    assert await provider.rerank("query", []) == []


async def test_rerank_provider_rejects_out_of_range_index():
    client = FakeClient(FakeResponse(payload={"results": [{"index": 3, "relevance_score": 0.8}]}))
    provider = SiliconFlowRerankProvider(api_key="secret", client=client)

    with pytest.raises(ProviderResponseError):
        await provider.rerank("query", ["doc-a"])
