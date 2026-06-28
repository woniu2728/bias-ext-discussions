from __future__ import annotations


def search_index_definitions():
    return (
        {
            "name": "discussions_title_slug_fts_idx",
            "drop": "DROP INDEX CONCURRENTLY IF EXISTS discussions_title_slug_fts_idx",
            "create": """
                CREATE INDEX CONCURRENTLY IF NOT EXISTS discussions_title_slug_fts_idx
                ON discussions
                USING GIN (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(slug, '')))
            """,
            "description": "为讨论标题和 slug 提供 PostgreSQL 全文搜索索引。",
        },
    )
