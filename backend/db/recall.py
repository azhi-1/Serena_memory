"""
Recall Service — unified token-bounded recall package for agents.

Merges semantic vector search and lexical FTS search with deterministic
Reciprocal Rank Fusion, formats a compact recall package with source URIs,
and enforces a character-based token budget.
"""

from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .search import SearchIndexer
    from .vector_index import VectorIndexer
    from .remote_summary import RemoteSummaryService


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 3)


class RecallService:

    def __init__(
        self,
        search_indexer: "SearchIndexer",
        vector_indexer: "VectorIndexer",
        remote_summary_service: Optional["RemoteSummaryService"] = None,
    ):
        self._search = search_indexer
        self._vector = vector_indexer
        self._remote = remote_summary_service

    async def recall(
        self,
        query: str,
        *,
        domain: Optional[str] = None,
        semantic_limit: int = 5,
        lexical_limit: int = 5,
        token_budget: int = 2000,
        namespace: str = "",
    ) -> str:
        semantic_results: list[dict[str, Any]] = []
        lexical_results: list[dict[str, Any]] = []
        remote_results: list[dict[str, Any]] = []

        try:
            semantic_results = await self._vector.search(
                query,
                limit=semantic_limit,
                domain=domain,
                namespace=namespace,
                source_type="active_memory",
            )
        except Exception:
            pass

        try:
            lexical_results = await self._search.search(
                query, limit=lexical_limit, domain=domain, namespace=namespace,
            )
        except Exception:
            pass

        try:
            remote_raw = await self._vector.search(
                query,
                limit=semantic_limit,
                domain=domain,
                namespace=namespace,
                source_type="remote_summary",
            )
            if self._remote is not None:
                for item in remote_raw:
                    batch = await self._remote.get_batch(
                        item["node_uuid"], namespace=namespace,
                    )
                    if batch is not None and batch.get("status") == "active":
                        item["batch_title"] = batch.get("title", "")
                        item["batch_source_count"] = batch.get("source_count", 0)
                        item["batch_model"] = batch.get("summary_model", "")
                        remote_results.append(item)
            else:
                remote_results = remote_raw
        except Exception:
            pass

        if not semantic_results and not lexical_results and not remote_results:
            return (
                f'=== RECALL RESULTS for "{query}" ===\n'
                f"No memories found — neither semantic, lexical, nor remote "
                f"summary search returned results.\n"
                f"Consider creating memories first or trying a different query.\n"
            )

        ranked = self._merge_rrf(semantic_results, lexical_results, remote_results)
        return self._format_package(ranked, token_budget, query)

    def _merge_rrf(
        self,
        semantic_results: list[dict[str, Any]],
        lexical_results: list[dict[str, Any]],
        remote_results: list[dict[str, Any]] | None = None,
    ) -> list[tuple[float, dict[str, Any], str]]:
        candidates: dict[str, dict[str, Any]] = {}
        sem_count = len(semantic_results)
        lex_count = len(lexical_results)
        remote_results = remote_results or []

        for rank, item in enumerate(semantic_results):
            node_uuid = item["node_uuid"]
            candidates[node_uuid] = {
                "item": item,
                "mode": "SEMANTIC",
                "sem_rank": rank,
                "lex_rank": None,
                "rem_rank": None,
            }

        for rank, item in enumerate(lexical_results):
            node_uuid = item.get("node_uuid")
            if not node_uuid:
                continue
            lex_rank = rank + sem_count
            if node_uuid in candidates:
                info = candidates[node_uuid]
                info["mode"] = "BOTH"
                info["lex_rank"] = lex_rank
                info["item"]["snippet"] = item.get("snippet", "")
                info["item"]["priority"] = item.get("priority", 0)
                info["item"]["disclosure"] = item.get("disclosure", "")
            else:
                candidates[node_uuid] = {
                    "item": item,
                    "mode": "LEXICAL",
                    "sem_rank": None,
                    "lex_rank": lex_rank,
                    "rem_rank": None,
                }

        for rank, item in enumerate(remote_results):
            node_uuid = item.get("node_uuid")
            if not node_uuid:
                continue
            rem_rank = rank + sem_count + lex_count
            candidates[node_uuid] = {
                "item": item,
                "mode": "REMOTE",
                "sem_rank": None,
                "lex_rank": None,
                "rem_rank": rem_rank,
            }

        K = 60
        scored: list[tuple[float, dict[str, Any], str]] = []
        for _node_uuid, info in candidates.items():
            rrf = 0.0
            if info["sem_rank"] is not None:
                rrf += 1.0 / (K + info["sem_rank"])
            if info["lex_rank"] is not None:
                rrf += 1.0 / (K + info["lex_rank"])
            if info["rem_rank"] is not None:
                rrf += 1.0 / (K + info["rem_rank"])
            scored.append((rrf, info["item"], info["mode"]))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def _format_package(
        self,
        ranked: list[tuple[float, dict[str, Any], str]],
        token_budget: int,
        query: str,
    ) -> str:
        per_item_cap = max(1, token_budget // 5)
        header_prefix = f'=== RECALL RESULTS for "{query}" ===\n'
        footer_template = "--- end recall ({n} items, budget: {used}/{total} tokens) ---\n"

        item_texts: list[str] = []
        for _rrf_score, item, mode in ranked:
            item_texts.append(self._format_item(item, mode, per_item_cap))

        if not item_texts:
            return header_prefix + (
                "No memories found — neither semantic nor lexical search "
                "returned results.\n"
                "Consider creating memories first or trying a different query.\n"
            )

        def _build(n: int) -> str:
            selected = "".join(item_texts[:n])
            header = header_prefix + f"[token_used: ? / {token_budget}]\n\n"
            footer = footer_template.format(n=n, used=0, total=token_budget)
            total = estimate_tokens(header) + estimate_tokens(selected) + estimate_tokens(footer)
            header = header_prefix + f"[token_used: {total} / {token_budget}]\n\n"
            footer = footer_template.format(n=n, used=total, total=token_budget)
            return header + selected + footer

        for n in range(len(item_texts), -1, -1):
            output = _build(n)
            if estimate_tokens(output) <= token_budget:
                return output

        return (
            f'=== RECALL RESULTS for "{query}" ===\n'
            f"[token_budget too small for any results (budget: {token_budget} tokens)]\n"
        )

    def _format_item(
        self,
        item: dict[str, Any],
        mode: str,
        per_item_cap: int,
    ) -> str:
        if mode == "SEMANTIC":
            return self._format_semantic_item(item, per_item_cap)
        elif mode == "BOTH":
            return self._format_both_item(item, per_item_cap)
        elif mode == "REMOTE":
            return self._format_remote_item(item, per_item_cap)
        else:
            return self._format_lexical_item(item, per_item_cap)

    def _format_semantic_item(
        self,
        item: dict[str, Any],
        per_item_cap: int,
    ) -> str:
        score = item.get("score", 0.0)
        uri = item.get("uri", "?")
        source = item.get("source_type", "active_memory")
        text = item.get("source_text", "")
        text = self._truncate_text(text, per_item_cap)

        lines = [
            f"[SEMANTIC] score={score:.3f}\n",
            f"  uri: {uri}\n",
            f"  source: {source}\n",
        ]
        if text:
            lines.append(f"  {text}\n")
        lines.append("\n")
        return "".join(lines)

    def _format_lexical_item(
        self,
        item: dict[str, Any],
        per_item_cap: int,
    ) -> str:
        uri = item.get("uri", "?")
        snippet = item.get("snippet", "")
        snippet = self._truncate_text(snippet, per_item_cap)
        priority = item.get("priority", 0)
        disclosure = item.get("disclosure", "")

        lines = [
            "[LEXICAL] snippet_match\n",
            f"  uri: {uri}\n",
        ]
        if snippet:
            lines.append(f"  snippet: {snippet}\n")
        lines.append(f"  priority: {priority}\n")
        if disclosure:
            lines.append(f"  disclosure: {disclosure}\n")
        lines.append("\n")
        return "".join(lines)

    def _format_both_item(
        self,
        item: dict[str, Any],
        per_item_cap: int,
    ) -> str:
        score = item.get("score", 0.0)
        uri = item.get("uri", "?")
        source = item.get("source_type", "active_memory")
        snippet = item.get("snippet", "")
        priority = item.get("priority", 0)

        lines = [
            f"[BOTH] score={score:.3f}\n",
            f"  uri: {uri}\n",
            f"  source: {source}\n",
        ]
        if snippet:
            snippet = self._truncate_text(snippet, per_item_cap)
            lines.append(f"  snippet: {snippet}\n")
        lines.append(f"  priority: {priority}\n")
        lines.append("\n")
        return "".join(lines)

    def _format_remote_item(
        self,
        item: dict[str, Any],
        per_item_cap: int,
    ) -> str:
        score = item.get("score", 0.0)
        batch_id = item.get("node_uuid", "?")
        title = item.get("batch_title", "")
        source_count = item.get("batch_source_count", 0)
        model = item.get("batch_model", "")
        summary = item.get("source_text", "")
        summary = self._truncate_text(summary, per_item_cap)

        lines = [
            f"[REMOTE] score={score:.3f}\n",
            f"  batch: {batch_id}\n",
        ]
        if title:
            lines.append(f"  title: {title}\n")
        lines.append(f"  sources: {source_count} memories\n")
        if model:
            lines.append(f"  model: {model}\n")
        if summary:
            lines.append(f"  summary: {summary}\n")
        lines.append("\n")
        return "".join(lines)

    @staticmethod
    def _truncate_text(text: str, per_item_cap: int) -> str:
        max_chars = per_item_cap * 3
        if len(text) > max_chars:
            return text[:max_chars] + "..."
        return text
