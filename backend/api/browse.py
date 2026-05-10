"""
Browse API - Clean URI-based memory navigation

This replaces the old Entity/Relation/Chapter conceptual split with a simple
hierarchical browser. Every path is just a node with content and children.
"""

import os
import re
from pathlib import Path as FilePath
from dotenv import dotenv_values, set_key

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from db import get_graph_service, get_glossary_service, get_db_manager
from db.models import Path as PathModel, Edge as EdgeModel, ROOT_NODE_UUID
from db.namespace import get_namespace
from sqlalchemy import select, distinct


def _get_dotenv_path() -> FilePath:
    """Resolve the .env file path (project root)."""
    backend_dir = FilePath(__file__).resolve().parent.parent
    root_dir = backend_dir.parent
    return root_dir / ".env"


def _boot_uris_env_key(namespace: str) -> str:
    """Return the .env key for boot URIs for a given namespace."""
    if namespace:
        return f"CORE_MEMORY_URIS__{namespace}"
    return "CORE_MEMORY_URIS"


def _read_boot_uris(namespace: str = "") -> list[str]:
    """Read boot URIs for the given namespace from .env or environment.

    Resolution order: CORE_MEMORY_URIS__{namespace} → CORE_MEMORY_URIS (fallback).
    """
    env_path = _get_dotenv_path()
    ns_key = _boot_uris_env_key(namespace)
    fallback_key = "CORE_MEMORY_URIS"

    env_vars = dotenv_values(env_path) if env_path.exists() else {}

    val = None

    if ns_key != fallback_key:
        if ns_key in env_vars:
            val = env_vars[ns_key]
        elif ns_key in os.environ:
            val = os.environ[ns_key]

    if val is None:
        if fallback_key in env_vars:
            val = env_vars[fallback_key]
        elif fallback_key in os.environ:
            val = os.environ[fallback_key]

    if not val:
        return []
    return [u.strip() for u in val.split(",") if u.strip()]


def _write_boot_uris(uris: list[str], namespace: str = "") -> None:
    """Write boot URIs for the given namespace to .env."""
    env_path = _get_dotenv_path()
    env_key = _boot_uris_env_key(namespace)
    new_value = ",".join(uris)

    if not env_path.exists():
        env_path.write_text("", encoding="utf-8")

    set_key(env_path, env_key, new_value)
    os.environ[env_key] = new_value

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
# Boot URI Management
# =============================================================================


class BootUriToggle(BaseModel):
    uri: str
    enabled: bool


@router.get("/boot-uris")
async def get_boot_uris():
    """Return boot URIs for the current namespace."""
    return {"uris": _read_boot_uris(get_namespace())}


@router.put("/boot-uris")
async def toggle_boot_uri(body: BootUriToggle):
    """Add or remove a URI from the boot list for the current namespace."""
    ns = get_namespace()
    current = _read_boot_uris(ns)
    uri = body.uri.strip()
    if not uri:
        raise HTTPException(status_code=422, detail="URI cannot be empty")

    if not re.match(r"^[a-zA-Z0-9_-]+://[a-zA-Z0-9_/\.-]*$", uri):
        raise HTTPException(status_code=422, detail="Invalid URI format")

    if body.enabled:
        if uri not in current:
            current.append(uri)
    else:
        current = [u for u in current if u != uri]

    _write_boot_uris(current, ns)
    return {"success": True, "uris": current}
