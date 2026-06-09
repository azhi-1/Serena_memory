import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def up(engine: AsyncEngine):
    """
    Version: v3.0.0
    Add memory_embeddings table for semantic vector search.

    Stores embeddings as BLOB columns for portability across
    SQLite and PostgreSQL without extension dependencies.
    Cosine similarity search is performed in Python.
    """
    async with engine.begin() as conn:
        await conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS memory_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                namespace TEXT NOT NULL DEFAULT '',
                node_uuid TEXT NOT NULL,
                source_memory_id INTEGER DEFAULT NULL,
                domain TEXT NOT NULL DEFAULT 'core',
                path TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT 'active_memory',
                source_text TEXT NOT NULL DEFAULT '',
                embedding_model TEXT NOT NULL DEFAULT '',
                embedding_dimension INTEGER NOT NULL DEFAULT 0,
                embedding BLOB DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
            """
        ))

        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_memory_embeddings_node_uuid "
            "ON memory_embeddings(node_uuid)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_memory_embeddings_namespace "
            "ON memory_embeddings(namespace)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_memory_embeddings_domain "
            "ON memory_embeddings(domain)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_embeddings_node "
            "ON memory_embeddings(node_uuid, namespace, source_type, embedding_model)"
        ))

    logger.info("Migration 015: created memory_embeddings table")
