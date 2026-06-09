import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def up(engine: AsyncEngine):
    """
    Version: v3.1.0
    Add remote_summary_batches and remote_summary_sources tables
    for settled long-term memory summaries with source provenance.
    """
    async with engine.begin() as conn:
        await conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS remote_summary_batches (
                id TEXT PRIMARY KEY,
                namespace TEXT NOT NULL DEFAULT '',
                domain TEXT NOT NULL DEFAULT 'core',
                title TEXT NOT NULL DEFAULT '',
                summary_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active', 'superseded')),
                source_count INTEGER NOT NULL DEFAULT 0,
                summary_model TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
            """
        ))

        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_remote_summary_batches_namespace "
            "ON remote_summary_batches(namespace)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_remote_summary_batches_domain "
            "ON remote_summary_batches(domain)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_remote_summary_batches_status "
            "ON remote_summary_batches(status)"
        ))

        await conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS remote_summary_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL
                    REFERENCES remote_summary_batches(id) ON DELETE CASCADE,
                namespace TEXT NOT NULL DEFAULT '',
                source_node_uuid TEXT NOT NULL,
                source_memory_id INTEGER NOT NULL,
                source_domain TEXT NOT NULL DEFAULT 'core',
                source_path TEXT NOT NULL DEFAULT '',
                source_uri TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(batch_id, source_node_uuid, source_memory_id, namespace)
            )
            """
        ))

        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_remote_summary_sources_batch_id "
            "ON remote_summary_sources(batch_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_remote_summary_sources_source_node_uuid "
            "ON remote_summary_sources(source_node_uuid)"
        ))

    logger.info("Migration 016: created remote_summary_batches and remote_summary_sources tables")
