"""
Serena Memory — DB package public API.

Provides per-service getters instead of a single god-object.
Services are lazily constructed on first access and share a
single DatabaseManager instance.
"""

from typing import Optional, TYPE_CHECKING

from .database import DatabaseManager
from .snapshot import ChangesetStore, get_changeset_store
from .namespace import get_namespace, set_namespace
from .models import (
    Base, ROOT_NODE_UUID, Node, Memory, Edge, Path,
    GlossaryKeyword, SearchDocument, ChangeCollector, Preset,
)

if TYPE_CHECKING:
    from .graph import GraphService
    from .search import SearchIndexer
    from .glossary import GlossaryService
    from .presets import PresetService
    from .vector_index import VectorIndexer
    from .recall import RecallService
    from .remote_summary import RemoteSummaryService, RemoteSummarySourceValidator

_db_manager: Optional[DatabaseManager] = None
_graph_service: Optional["GraphService"] = None
_search_indexer: Optional["SearchIndexer"] = None
_glossary_service: Optional["GlossaryService"] = None
_preset_service: Optional["PresetService"] = None
_vector_indexer: Optional["VectorIndexer"] = None
_recall_service: Optional["RecallService"] = None
_remote_summary_service: Optional["RemoteSummaryService"] = None
_source_validator: Optional["RemoteSummarySourceValidator"] = None


def _resolve_database_url() -> str:
    """Resolve DATABASE_URL from config.json."""
    import sys
    from pathlib import Path
    
    # Ensure backend directory is in sys.path so we can import config
    backend_dir = str(Path(__file__).resolve().parent.parent)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
        
    import config
    url = config.get("database_url")
    if not url:
        raise ValueError("database_url is not configured in config.json")
    return url


def _ensure_initialized():
    global _db_manager, _graph_service, _search_indexer, _glossary_service, _preset_service, _vector_indexer, _recall_service, _remote_summary_service, _source_validator
    if _db_manager is not None:
        return

    database_url = _resolve_database_url()

    from .search import SearchIndexer
    from .glossary import GlossaryService
    from .graph import GraphService
    from .presets import PresetService
    from .vector_index import VectorIndexer
    from .recall import RecallService
    from .remote_summary import RemoteSummaryService, RemoteSummarySourceValidator

    _db_manager = DatabaseManager(database_url)
    _search_indexer = SearchIndexer(_db_manager)
    _glossary_service = GlossaryService(_db_manager, _search_indexer)
    _graph_service = GraphService(_db_manager, _search_indexer)
    _preset_service = PresetService(_db_manager)

    embedding_provider = None
    try:
        import os
        if os.environ.get("SILICONFLOW_API_KEY"):
            from vector.providers import SiliconFlowEmbeddingProvider
            import config as _cfg
            embedding_provider = SiliconFlowEmbeddingProvider(
                model=_cfg.get("embedding_model") or "Qwen/Qwen3-Embedding-8B",
            )
    except Exception:
        pass
    _vector_indexer = VectorIndexer(_db_manager, embedding_provider=embedding_provider)

    _remote_summary_service = RemoteSummaryService(_db_manager, _vector_indexer)
    _source_validator = RemoteSummarySourceValidator(_graph_service)
    _recall_service = RecallService(_search_indexer, _vector_indexer, remote_summary_service=_remote_summary_service)


def get_db_manager() -> DatabaseManager:
    _ensure_initialized()
    return _db_manager  # type: ignore[return-value]


def get_graph_service() -> "GraphService":
    _ensure_initialized()
    return _graph_service  # type: ignore[return-value]


def get_search_indexer() -> "SearchIndexer":
    _ensure_initialized()
    return _search_indexer  # type: ignore[return-value]


def get_glossary_service() -> "GlossaryService":
    _ensure_initialized()
    return _glossary_service  # type: ignore[return-value]


def get_preset_service() -> "PresetService":
    _ensure_initialized()
    return _preset_service  # type: ignore[return-value]


def get_vector_indexer() -> "VectorIndexer":
    _ensure_initialized()
    return _vector_indexer  # type: ignore[return-value]


def get_recall_service() -> "RecallService":
    _ensure_initialized()
    return _recall_service  # type: ignore[return-value]


def get_remote_summary_service() -> "RemoteSummaryService":
    _ensure_initialized()
    return _remote_summary_service  # type: ignore[return-value]


def get_source_validator() -> "RemoteSummarySourceValidator":
    _ensure_initialized()
    return _source_validator  # type: ignore[return-value]


async def close_db():
    """Tear down all services and close the database connection."""
    global _db_manager, _graph_service, _search_indexer, _glossary_service, _preset_service, _vector_indexer, _recall_service, _remote_summary_service, _source_validator
    if _db_manager:
        await _db_manager.close()
    _db_manager = None
    _graph_service = None
    _search_indexer = None
    _glossary_service = None
    _preset_service = None
    _vector_indexer = None
    _recall_service = None
    _remote_summary_service = None
    _source_validator = None


__all__ = [
    "DatabaseManager",
    "get_db_manager", "get_graph_service",
    "get_search_indexer", "get_glossary_service",
    "get_preset_service", "get_vector_indexer",
    "get_recall_service", "get_remote_summary_service",
    "get_source_validator",
    "close_db",
    "ChangesetStore", "get_changeset_store",
    "get_namespace", "set_namespace",
    "Base", "ROOT_NODE_UUID", "Node", "Memory", "Edge", "Path",
    "GlossaryKeyword", "SearchDocument", "ChangeCollector", "Preset",
]
