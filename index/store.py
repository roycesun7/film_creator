"""Supabase-based media index with pgvector search.

Stores media metadata, Claude Vision descriptions, and embeddings.
Provides cosine-distance search via pgvector and metadata filtering.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from supabase import create_client, Client

from config import (
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_ANON_KEY,
    EMBEDDING_DIM,
    USE_TWELVELABS,
)

logger = logging.getLogger(__name__)

_client: Client | None = None


def _get_client() -> Client:
    """Return a cached Supabase client."""
    global _client
    if _client is None:
        key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
        _client = create_client(SUPABASE_URL, key)
    return _client


def init_db() -> None:
    """Verify Supabase connection. Tables are managed via migrations."""
    client = _get_client()
    resp = client.table("media").select("uuid", count="exact").limit(0).execute()
    logger.info("Supabase connected — media table has %s rows", resp.count)


def _embedding_to_list(embedding: Optional[np.ndarray]) -> Optional[list[float]]:
    """Convert numpy embedding to a list for pgvector."""
    if embedding is None:
        return None
    return embedding.astype(float).tolist()


def _list_to_embedding(data) -> Optional[np.ndarray]:
    """Convert pgvector list/string back to numpy array."""
    if data is None:
        return None
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse embedding string: %s", data[:80] if len(data) > 80 else data)
            return None
    return np.array(data, dtype=np.float32)


def _row_to_dict(row: dict) -> dict:
    """Normalize a Supabase row into the format the rest of the app expects."""
    d = dict(row)

    # JSONB fields come back as native Python objects from supabase-py
    for key in ("albums", "labels", "persons"):
        if d.get(key) is None:
            d[key] = []

    if d.get("description") is None:
        d["description"] = {}

    # Convert pgvector embedding to numpy
    d["embedding"] = _list_to_embedding(d.get("embedding"))

    # Remove clip_embedding from the dict (internal column)
    d.pop("clip_embedding", None)

    return d


def upsert_media(item: dict) -> None:
    """Insert or update a media record."""
    client = _get_client()

    embedding = item.get("embedding")
    embedding_list = _embedding_to_list(embedding) if embedding is not None else None

    # Determine which column to store the embedding in.
    # Use the USE_TWELVELABS flag rather than dimension, because Marengo 3.0
    # and CLIP both produce 512-d vectors.
    emb_col = "embedding"
    clip_emb_val = None
    if embedding is not None:
        if USE_TWELVELABS:
            pass  # Twelve Labs embeddings go in 'embedding' column
        else:
            emb_col = "clip_embedding"
            clip_emb_val = embedding_list
            embedding_list = None

    record = {
        "uuid": item.get("uuid"),
        "path": item.get("path"),
        "media_type": item.get("media_type"),
        "date": item.get("date"),
        "lat": item.get("lat"),
        "lon": item.get("lon"),
        "albums": item.get("albums", []),
        "labels": item.get("labels", []),
        "persons": item.get("persons", []),
        "width": item.get("width"),
        "height": item.get("height"),
        "duration": item.get("duration"),
        "description": item.get("description", {}),
        "quality_score": item.get("quality_score"),
        "indexed_at": item.get("indexed_at", datetime.now(timezone.utc).isoformat()),
    }

    if embedding_list is not None:
        record["embedding"] = embedding_list
    if clip_emb_val is not None:
        record["clip_embedding"] = clip_emb_val

    client.table("media").upsert(record, on_conflict="uuid").execute()


def update_embedding(media_uuid: str, embedding: np.ndarray) -> None:
    """Update just the embedding for an existing media record."""
    client = _get_client()
    emb_list = _embedding_to_list(embedding)

    if USE_TWELVELABS:
        client.table("media").update({"embedding": emb_list}).eq("uuid", media_uuid).execute()
    else:
        client.table("media").update({"clip_embedding": emb_list}).eq("uuid", media_uuid).execute()


def search_by_text(
    query_embedding: np.ndarray,
    limit: int = 20,
) -> list[dict]:
    """Find media items most similar to a query embedding via pgvector cosine distance."""
    client = _get_client()
    emb_list = _embedding_to_list(query_embedding)

    # Choose the RPC based on the active embedding engine, not dimension
    # (Marengo 3.0 and CLIP both produce 512-d vectors).
    rpc_name = "match_media" if USE_TWELVELABS else "match_media_clip"

    try:
        resp = client.rpc(rpc_name, {
            "query_embedding": emb_list,
            "match_limit": limit,
        }).execute()

        results = []
        for row in resp.data:
            rec = _row_to_dict(row)
            rec["similarity"] = row.get("similarity", 0.0)
            results.append(rec)
        return results
    except Exception as exc:
        logger.warning("pgvector RPC search failed, using fallback: %s", exc)
        return _search_by_text_fallback(query_embedding, limit)


def _search_by_text_fallback(
    query_embedding: np.ndarray,
    limit: int,
) -> list[dict]:
    """Fallback: load embeddings and compute cosine similarity in Python."""
    uuids, embedding_matrix = get_all_embeddings()
    if len(uuids) == 0:
        return []

    query = query_embedding.astype(np.float32).reshape(1, -1)
    similarities = (embedding_matrix @ query.T).squeeze(1)

    top_indices = np.argsort(similarities)[::-1][:limit]
    top_uuids = [uuids[i] for i in top_indices]
    top_scores = [float(similarities[i]) for i in top_indices]

    records = get_media_by_uuids(top_uuids)
    uuid_to_record = {r["uuid"]: r for r in records}

    results = []
    for uid, score in zip(top_uuids, top_scores):
        if uid in uuid_to_record:
            rec = uuid_to_record[uid]
            rec["similarity"] = score
            results.append(rec)

    return results


def search_by_metadata(
    albums: Optional[list[str]] = None,
    persons: Optional[list[str]] = None,
    date_range: Optional[tuple[str, str]] = None,
    min_quality: Optional[float] = None,
) -> list[dict]:
    """Filter media records by metadata fields."""
    client = _get_client()
    query = client.table("media").select("*")

    if date_range is not None:
        query = query.gte("date", date_range[0]).lte("date", date_range[1])

    if min_quality is not None:
        query = query.gte("quality_score", min_quality)

    query = query.order("date", desc=True)
    resp = query.execute()
    results = [_row_to_dict(row) for row in resp.data]

    # Post-filter on JSONB array fields
    if albums is not None:
        album_set = set(albums)
        results = [
            r for r in results if album_set & set(r.get("albums", []))
        ]

    if persons is not None:
        person_set = set(persons)
        results = [
            r for r in results if person_set & set(r.get("persons", []))
        ]

    return results


def get_indexed_uuids() -> set[str]:
    """Return all UUIDs currently stored in the database."""
    client = _get_client()
    resp = client.table("media").select("uuid").execute()
    return {row["uuid"] for row in resp.data}


def get_all_embeddings() -> tuple[list[str], np.ndarray]:
    """Load all stored embeddings for batch operations.

    Returns matching embeddings for the active engine dimension.
    """
    client = _get_client()

    if USE_TWELVELABS:
        col = "embedding"
    else:
        col = "clip_embedding"
    dim = EMBEDDING_DIM

    resp = client.table("media").select(f"uuid, {col}").not_.is_(col, "null").execute()

    if not resp.data:
        return [], np.empty((0, dim), dtype=np.float32)

    uuids: list[str] = []
    embeddings: list[np.ndarray] = []
    for row in resp.data:
        emb = _list_to_embedding(row.get(col))
        if emb is not None and emb.shape == (dim,):
            uuids.append(row["uuid"])
            embeddings.append(emb)

    if not embeddings:
        return [], np.empty((0, dim), dtype=np.float32)

    matrix = np.stack(embeddings, axis=0)
    return uuids, matrix


def list_media(limit: int = 20, offset: int = 0, sort_by: str = "date",
               media_type: str | None = None,
               date_from: str | None = None,
               date_to: str | None = None) -> list[dict]:
    """List indexed media with pagination and sorting."""
    client = _get_client()

    sort_map = {
        "date": ("date", True),
        "quality": ("quality_score", True),
        "recent": ("indexed_at", True),
    }
    col, desc = sort_map.get(sort_by, ("date", True))

    query = (
        client.table("media")
        .select("*")
        .order(col, desc=desc, nullsfirst=False)
    )
    if media_type:
        query = query.eq("media_type", media_type)
    if date_from:
        query = query.gte("date", date_from)
    if date_to:
        query = query.lte("date", date_to + "T23:59:59")
    resp = query.range(offset, offset + limit - 1).execute()
    return [_row_to_dict(row) for row in resp.data]


def delete_media(uuid: str) -> bool:
    """Delete a single media record by UUID."""
    client = _get_client()
    resp = client.table("media").delete().eq("uuid", uuid).execute()
    return len(resp.data) > 0


def delete_all_media() -> int:
    """Delete all media records from the database."""
    client = _get_client()
    # Get count first
    count_resp = client.table("media").select("uuid", count="exact").execute()
    count = count_resp.count or 0
    if count > 0:
        # Delete all by selecting everything (supabase-py needs a filter for delete)
        client.table("keyframe_embeddings").delete().neq("id", -1).execute()
        client.table("media").delete().neq("uuid", "").execute()
    return count


def count_media(media_type: str | None = None,
                date_from: str | None = None,
                date_to: str | None = None) -> int:
    """Return the total number of media records in the database."""
    client = _get_client()
    query = client.table("media").select("uuid", count="exact")
    if media_type:
        query = query.eq("media_type", media_type)
    if date_from:
        query = query.gte("date", date_from)
    if date_to:
        query = query.lte("date", date_to + "T23:59:59")
    resp = query.limit(0).execute()
    return resp.count or 0


def search_by_description(query: str, limit: int = 20) -> list[dict]:
    """Text search over descriptions, labels, and persons.

    Uses Postgres text search via ilike for simplicity.
    """
    words = query.lower().split()
    if not words:
        return []

    client = _get_client()
    # Fetch all media and score in Python (supabase-py doesn't support complex scoring)
    resp = client.table("media").select("*").execute()
    all_rows = [_row_to_dict(row) for row in resp.data]

    scored = []
    for row in all_rows:
        score = 0
        desc_text = json.dumps(row.get("description", {})).lower()
        labels_text = json.dumps(row.get("labels", [])).lower()
        persons_text = json.dumps(row.get("persons", [])).lower()
        searchable = desc_text + " " + labels_text + " " + persons_text
        for word in words:
            if word in searchable:
                score += 1
        if score > 0:
            row["relevance_score"] = float(score)
            scored.append(row)

    scored.sort(key=lambda r: r["relevance_score"], reverse=True)
    return scored[:limit]


def get_media_by_uuids(uuids: list[str]) -> list[dict]:
    """Fetch full media records for a list of UUIDs."""
    if not uuids:
        return []

    client = _get_client()
    resp = client.table("media").select("*").in_("uuid", uuids).execute()
    return [_row_to_dict(row) for row in resp.data]


# ---------------------------------------------------------------------------
# Keyframe embedding operations
# ---------------------------------------------------------------------------

def upsert_keyframe_embedding(
    media_uuid: str,
    keyframe_index: int,
    timestamp: float | None,
    embedding: np.ndarray,
) -> None:
    """Insert or update a single keyframe embedding."""
    client = _get_client()
    emb_list = _embedding_to_list(embedding)

    record = {
        "media_uuid": media_uuid,
        "keyframe_index": keyframe_index,
        "timestamp_sec": timestamp,
        "embedding": emb_list,
    }
    client.table("keyframe_embeddings").upsert(
        record, on_conflict="media_uuid,keyframe_index"
    ).execute()


def search_keyframes_by_text(
    query_embedding: np.ndarray,
    limit: int = 20,
) -> list[dict]:
    """Cosine-similarity search across all keyframe embeddings.

    Returns the single best-matching keyframe per video.
    """
    client = _get_client()

    if not USE_TWELVELABS:
        # Keyframe embeddings are Twelve Labs only
        return []

    emb_list = _embedding_to_list(query_embedding)

    try:
        # Fetch more than limit since we'll deduplicate per video
        resp = client.rpc("match_keyframes", {
            "query_embedding": emb_list,
            "match_limit": limit * 3,
        }).execute()

        if not resp.data:
            return []

        # Keep best keyframe per media_uuid
        best: dict[str, dict] = {}
        for row in resp.data:
            uid = row["media_uuid"]
            sim = row.get("similarity", 0.0)
            entry = {
                "media_uuid": uid,
                "keyframe_index": row["keyframe_index"],
                "timestamp": row.get("timestamp_sec"),
                "similarity": sim,
            }
            if uid not in best or sim > best[uid]["similarity"]:
                best[uid] = entry

        results = sorted(best.values(), key=lambda r: r["similarity"], reverse=True)
        return results[:limit]

    except Exception as exc:
        logger.warning("Keyframe RPC search failed: %s", exc)
        return []


def delete_keyframe_embeddings(media_uuid: str) -> None:
    """Delete all keyframe embeddings for a given media item."""
    client = _get_client()
    client.table("keyframe_embeddings").delete().eq("media_uuid", media_uuid).execute()
