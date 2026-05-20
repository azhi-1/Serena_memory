"""
Browse API - Clean URI-based memory navigation

This replaces the old Entity/Relation/Chapter conceptual split with a simple
hierarchical browser. Every path is just a node with content and children.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import config
from db import get_graph_service, get_glossary_service, get_db_manager, get_search_indexer
from db.models import Path as PathModel, Edge as EdgeModel, ROOT_NODE_UUID
from db.namespace import get_namespace
from sqlalchemy import select, distinct
import re

router = APIRouter(prefix="/browse", tags=["browse"])


class NodeUpdate(BaseModel):
    content: str | None = None
    priority: int | None = None
    disclosure: str | None = None


class GlossaryAdd(BaseModel):
    keyword: str
    node_uuid: str


class GlossaryRemove(BaseModel):
    keyword: str
    node_uuid: str


class CreateMemoryRequest(BaseModel):
    parent_path: str
    content: str
    priority: int
    disclosure: str
    title: str | None = None
    domain: str = "core"


class CreateAliasRequest(BaseModel):
    new_path: str
    target_path: str
    disclosure: str
    new_domain: str = "core"
    target_domain: str = "core"
    priority: int = 0


@router.get("/namespaces")
async def list_namespaces():
    """Return all distinct namespaces that exist in the paths table.

    Used by the Admin Dashboard namespace selector so the user can switch
    between agent memory spaces without knowing the exact strings upfront.
    An empty-string namespace is returned as "" and corresponds to the
    default (single-agent) namespace.
    """
    db = get_db_manager()
    async with db.session() as session:
        result = await session.execute(
            select(distinct(PathModel.namespace)).order_by(PathModel.namespace)
        )
        return [row[0] for row in result.all()]


@router.get("/domains")
async def list_domains():
    """Return all domains that contain at least one root-level path."""
    from sqlalchemy import func, distinct

    db = get_db_manager()
    async with db.session() as session:
        result = await session.execute(
            select(
                PathModel.domain,
                func.count(distinct(PathModel.path)).label("node_count"),
            )
            .where(PathModel.namespace == get_namespace())
            .where(~PathModel.path.contains("/"))
            .group_by(PathModel.domain)
            .order_by(PathModel.domain)
        )
        return [
            {"domain": row.domain, "root_count": row.node_count}
            for row in result.all()
        ]


@router.get("/node")
async def get_node(
    path: str = Query("", description="URI path like 'nocturne' or 'nocturne/salem'"),
    domain: str = Query("core"),
    nav_only: bool = Query(False, description="Skip expensive processing if only navigating tree")
):
    """
    Get a node's content and its direct children.
    
    This is the only read endpoint you need - it gives you:
    - The current node's full content (or virtual root)
    - Preview of all children (next level)
    - Breadcrumb trail for navigation
    """
    graph = get_graph_service()
    
    if not path:
        # Check if there is an actual memory stored at the root path
        memory = await graph.get_memory_by_path("", domain=domain, namespace=get_namespace())
        
        children_raw = await graph.get_children(
            ROOT_NODE_UUID,
            context_domain=domain,
            context_path=path,
            namespace=get_namespace()
        )
        
        if memory:
            # Hide the actual root node from the root directory listing.
            children_raw = [
                c for c in children_raw
                if c.get("node_uuid") != memory["node_uuid"]
            ]
        else:
            # Virtual Root Node
            memory = {
                "content": "",
                "priority": 0,
                "disclosure": None,
                "created_at": None,
                "node_uuid": ROOT_NODE_UUID,
            }
            
        breadcrumbs = [{"path": "", "label": "root"}]
    else:
        # Get the node itself
        memory = await graph.get_memory_by_path(path, domain=domain, namespace=get_namespace())
        
        if not memory:
            raise HTTPException(status_code=404, detail=f"Path not found: {domain}://{path}")
        
        children_raw = await graph.get_children(
            memory["node_uuid"],
            context_domain=domain,
            context_path=path,
            namespace=get_namespace()
        )
        
        # Build breadcrumbs
        segments = path.split("/")
        breadcrumbs = [{"path": "", "label": "root"}]
        accumulated = ""
        for seg in segments:
            accumulated = f"{accumulated}/{seg}" if accumulated else seg
            breadcrumbs.append({"path": accumulated, "label": seg})
    
    children = [
        {
            "domain": c["domain"],
            "path": c["path"],
            "uri": f"{c['domain']}://{c['path']}",
            "name": c["path"].split("/")[-1],  # Last segment
            "priority": c["priority"],
            "disclosure": c.get("disclosure"),
            "content_snippet": c["content_snippet"],
            "approx_children_count": c.get("approx_children_count", 0)
        }
        for c in children_raw
        if c["domain"] == domain
    ]
    children.sort(key=lambda x: (x["priority"] if x["priority"] is not None else 999, x["path"]))
    
    # Get all aliases (other paths pointing to the same node)
    aliases = []
    if memory.get("node_uuid") and memory["node_uuid"] != ROOT_NODE_UUID:
        async with get_db_manager().session() as session:
            result = await session.execute(
                select(PathModel.domain, PathModel.path)
                .select_from(PathModel)
                .join(EdgeModel, PathModel.edge_id == EdgeModel.id)
                .where(PathModel.namespace == get_namespace())
                .where(EdgeModel.child_uuid == memory["node_uuid"])
            )
            aliases = [
                f"{row[0]}://{row[1]}"
                for row in result.all()
                if not (row[0] == domain and row[1] == path)
            ]
    
    # Get glossary keywords for this node
    glossary_keywords = []
    glossary_matches = []
    node_uuid = memory.get("node_uuid")

    if not nav_only:
        _glossary = get_glossary_service()
        if node_uuid and node_uuid != ROOT_NODE_UUID:
            glossary_keywords = await _glossary.get_glossary_for_node(node_uuid, namespace=get_namespace())

        # Get all glossary matches for the node content using Aho-Corasick
        if memory.get("content"):
            matches_dict = await _glossary.find_glossary_in_content(memory["content"], namespace=get_namespace())
            if matches_dict:
                glossary_matches = [
                    {"keyword": kw, "nodes": nodes}
                    for kw, nodes in matches_dict.items()
                ]

    return {
        "node": {
            "path": path,
            "domain": domain,
            "uri": f"{domain}://{path}",
            "name": path.split("/")[-1] if path else "root",
            "content": memory["content"],
            "priority": memory["priority"],
            "disclosure": memory["disclosure"],
            "created_at": memory["created_at"],
            "is_virtual": memory.get("created_at") is None,
            "aliases": aliases,
            "node_uuid": node_uuid,
            "glossary_keywords": glossary_keywords,
            "glossary_matches": glossary_matches,
        },
        "children": children,
        "breadcrumbs": breadcrumbs
    }


@router.put("/node")
async def update_node(
    path: str = Query(...),
    domain: str = Query("core"),
    body: NodeUpdate = ...
):
    """
    Update a node's content.
    """
    graph = get_graph_service()
    
    # Check exists
    memory = await graph.get_memory_by_path(path, domain=domain, namespace=get_namespace())
    if not memory:
        raise HTTPException(status_code=404, detail=f"Path not found: {domain}://{path}")
    
    # Update (creates new version if content changed, updates path metadata otherwise)
    try:
        result = await graph.update_memory(
            path=path,
            domain=domain,
            content=body.content,
            priority=body.priority,
            disclosure=body.disclosure,
            namespace=get_namespace(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    
    return {"success": True, "memory_id": result["new_memory_id"]}


@router.post("/node")
async def create_node(body: CreateMemoryRequest):
    """
    Create a new memory node.

    Human-facing direct edit endpoint: intentionally bypasses changeset/review.
    """
    graph = get_graph_service()

    if not body.disclosure:
        raise HTTPException(status_code=422, detail="disclosure must not be empty")

    if body.title is not None and not re.match(r'^[a-zA-Z0-9_-]+$', body.title):
        raise HTTPException(status_code=422, detail="Title can only contain letters, numbers, hyphens, and underscores")

    try:
        result = await graph.create_memory(
            parent_path=body.parent_path,
            content=body.content,
            priority=body.priority,
            title=body.title,
            disclosure=body.disclosure,
            domain=body.domain,
            namespace=get_namespace(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"success": True, "uri": result["uri"], "memory_id": result["id"]}


@router.post("/node/alias")
async def create_alias(body: CreateAliasRequest):
    """
    Add an alias (alternate path) to an existing node.

    Human-facing direct edit endpoint: intentionally bypasses changeset/review.
    """
    graph = get_graph_service()

    if not body.disclosure:
        raise HTTPException(status_code=422, detail="disclosure must not be empty")

    try:
        await graph.add_path(
            new_path=body.new_path,
            target_path=body.target_path,
            new_domain=body.new_domain,
            target_domain=body.target_domain,
            priority=body.priority,
            disclosure=body.disclosure,
            namespace=get_namespace(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"success": True, "uri": f"{body.new_domain}://{body.new_path}"}


class RenameRequest(BaseModel):
    path: str
    new_name: str
    domain: str = "core"


@router.post("/node/rename")
async def rename_node(body: RenameRequest):
    """
    Rename a memory by changing the last segment of its URI path.

    Like renaming a folder: the node and all its children are moved
    to the new path via add_path cascade + remove_path cleanup.

    Human-facing direct edit endpoint: intentionally bypasses changeset/review.
    """
    graph = get_graph_service()

    if not re.match(r'^[a-zA-Z0-9_-]+$', body.new_name):
        raise HTTPException(
            status_code=422,
            detail="new_name must contain only alphanumeric characters, hyphens, and underscores",
        )

    old_path = body.path
    old_uri = f"{body.domain}://{old_path}"

    if "/" in old_path:
        parent = old_path.rsplit("/", 1)[0]
        new_path = f"{parent}/{body.new_name}"
    else:
        new_path = body.new_name
    new_uri = f"{body.domain}://{new_path}"

    if old_path == new_path:
        return {"success": True, "old_uri": old_uri, "new_uri": new_uri, "unchanged": True}

    memory = await graph.get_memory_by_path(old_path, domain=body.domain, namespace=get_namespace())
    if not memory:
        raise HTTPException(status_code=404, detail=f"Path not found: {old_uri}")

    try:
        await graph.add_path(
            new_path=new_path,
            target_path=old_path,
            new_domain=body.domain,
            target_domain=body.domain,
            priority=memory.get("priority", 0),
            disclosure=memory.get("disclosure"),
            namespace=get_namespace(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Remove old path. If this fails, roll back the new path to avoid
    # leaving the node in a silent dual-path state the user won't notice.
    try:
        await graph.remove_path(old_path, body.domain, namespace=get_namespace())
    except Exception as e:
        try:
            await graph.remove_path(new_path, body.domain, namespace=get_namespace())
        except Exception:
            pass  # best-effort rollback
        raise HTTPException(
            status_code=500,
            detail=f"Rename partially failed: old path removal error ({e}). New path rolled back.",
        )

    old_prefix = old_uri + "/"
    new_prefix = new_uri + "/"
    ns = get_namespace()
    boot_uris = config.get_boot_uris(ns)
    rewritten = []
    for u in boot_uris:
        if u == old_uri:
            rewritten.append(new_uri)
        elif u.startswith(old_prefix):
            rewritten.append(new_prefix + u[len(old_prefix):])
        else:
            rewritten.append(u)
    if rewritten != boot_uris:
        config.set_boot_uris(rewritten, ns)

    return {
        "success": True,
        "old_uri": old_uri,
        "new_uri": new_uri,
        "old_path": old_path,
        "new_path": new_path,
    }


# =============================================================================
# Glossary Endpoints
# =============================================================================


@router.get("/glossary")
async def get_glossary():
    """Get all glossary keywords with their associated nodes."""
    glossary = get_glossary_service()
    raw_entries = await glossary.get_all_glossary(namespace=get_namespace(), search_all_namespaces=False)
    
    return {"glossary": raw_entries}


@router.post("/glossary")
async def add_glossary_keyword(body: GlossaryAdd):
    """Bind a keyword to a node."""
    # Human-facing direct edit endpoint: intentionally bypasses changeset/review.
    # The review queue tracks AI-authored mutations only.
    glossary = get_glossary_service()
    try:
        result = await glossary.add_glossary_keyword(body.keyword, body.node_uuid, namespace=get_namespace())
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/glossary")
async def remove_glossary_keyword(body: GlossaryRemove):
    """Remove a keyword binding from a node."""
    # Human-facing direct edit endpoint: intentionally bypasses changeset/review.
    # The review queue tracks AI-authored mutations only.
    glossary = get_glossary_service()
    result = await glossary.remove_glossary_keyword(body.keyword, body.node_uuid, namespace=get_namespace())
    if not result.get("success"):
        raise HTTPException(status_code=404, detail="Keyword binding not found")
    return {"success": True}


# =============================================================================
# Delete Endpoint
# =============================================================================


@router.delete("/node")
async def delete_node(
    path: str = Query(...),
    domain: str = Query("core"),
):
    """
    Delete a memory by removing its URI path.

    Human-facing direct delete: bypasses changeset/review queue.
    Calls graph.remove_path() which handles orphan prevention.
    """
    graph = get_graph_service()

    memory = await graph.get_memory_by_path(path, domain=domain, namespace=get_namespace())
    if not memory:
        raise HTTPException(status_code=404, detail=f"Path not found: {domain}://{path}")

    try:
        await graph.remove_path(path, domain, namespace=get_namespace())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    deleted_uri = f"{domain}://{path}"
    subtree_prefix = deleted_uri + "/"
    ns = get_namespace()
    boot_uris = config.get_boot_uris(ns)
    cleaned = [u for u in boot_uris if u != deleted_uri and not u.startswith(subtree_prefix)]
    if len(cleaned) != len(boot_uris):
        config.set_boot_uris(cleaned, ns)

    return {"success": True, "uri": deleted_uri}


# =============================================================================
# Search Endpoint
# =============================================================================


@router.get("/search")
async def search_memories(
    q: str = Query(..., min_length=1, description="Search query"),
    domain: Optional[str] = Query(None, description="Optional domain filter"),
    limit: int = Query(20, ge=1, le=100),
):
    """Full-text search across memories using the FTS index."""
    search = get_search_indexer()
    results = await search.search(q, limit=limit, domain=domain, namespace=get_namespace())
    return {"query": q, "results": results, "count": len(results)}
