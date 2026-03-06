"""Hybrid search combining CLIP embedding similarity with metadata filtering."""

from __future__ import annotations

import logging

import numpy as np

from index import clip_embeddings, store
import config

logger = logging.getLogger(__name__)


def _embed_query(query: str) -> np.ndarray:
    """Embed a text query using the best available engine."""
    if config.USE_TWELVELABS:
        from index.twelvelabs_embed import embed_text
        emb = embed_text(query)
        if emb is not None:
            return emb
        logger.warning("Twelve Labs text embedding failed, falling back to CLIP")
    return clip_embeddings.embed_text(query)


def hybrid_search(
    query: str,
    albums: list[str] | None = None,
    persons: list[str] | None = None,
    date_range: tuple[str, str] | None = None,
    min_quality: float | None = None,
    limit: int = 30,
) -> list[dict]:
    """Return media items ranked by fused embedding-similarity and metadata relevance.

    Items appearing in both the embedding search and the metadata search receive a
    boosted score.  Items from only one source keep their individual score.

    Each returned dict carries an added ``relevance_score`` field.
    """
    query_embedding = _embed_query(query)

    # Cast the limit wider so fusion has room to work before we trim.
    fetch_limit = limit * 3

    embedding_results = store.search_by_text(query_embedding, limit=fetch_limit)

    has_metadata_filters = any(v is not None for v in (albums, persons, date_range, min_quality))
    metadata_results = (
        store.search_by_metadata(
            albums=albums,
            persons=persons,
            date_range=date_range,
            min_quality=min_quality,
        )
        if has_metadata_filters
        else []
    )

    # Search keyframe embeddings for videos that match via later keyframes
    keyframe_results = store.search_keyframes_by_text(query_embedding, limit=fetch_limit)

    fused = _fuse_results(embedding_results, metadata_results, fetch_limit)

    # Merge keyframe results into the fused set
    if keyframe_results:
        kf_uuids = [kr["media_uuid"] for kr in keyframe_results]
        kf_records = store.get_media_by_uuids(kf_uuids)
        kf_record_map = {r["uuid"]: r for r in kf_records}

        k = 60  # Same RRF constant
        fused_by_uuid = {r["uuid"]: r for r in fused}
        for rank, kr in enumerate(keyframe_results):
            uid = kr["media_uuid"]
            kf_score = 1.0 / (k + rank)
            if uid in fused_by_uuid:
                # Boost existing entry
                fused_by_uuid[uid]["relevance_score"] += kf_score
            elif uid in kf_record_map:
                # New entry found only via keyframe
                rec = {**kf_record_map[uid], "relevance_score": kf_score}
                fused_by_uuid[uid] = rec
                fused.append(rec)

    if min_quality is not None:
        fused = [r for r in fused if (r.get("quality_score") or 0) >= min_quality]

    fused.sort(key=lambda r: r["relevance_score"], reverse=True)
    return fused[:limit]


def find_similar(uuid: str, limit: int = 10) -> list[dict]:
    """Find media items visually similar to the item identified by *uuid*."""
    all_uuids, embedding_matrix = store.get_all_embeddings()

    try:
        idx = all_uuids.index(uuid)
    except ValueError:
        logger.warning("UUID %s not found in embedding store", uuid)
        return []

    query_vec = embedding_matrix[idx]  # already normalised by the index layer
    similarities = embedding_matrix @ query_vec  # cosine similarity (vectors are L2-normed)

    # Exclude the query item itself, then pick top-k.
    ranked_indices = np.argsort(similarities)[::-1]
    selected_uuids: list[str] = []
    for i in ranked_indices:
        if all_uuids[i] == uuid:
            continue
        selected_uuids.append(all_uuids[i])
        if len(selected_uuids) >= limit:
            break

    results = store.get_media_by_uuids(selected_uuids)

    # Attach a relevance_score derived from cosine similarity.
    sim_by_uuid = {
        all_uuids[i]: float(similarities[i]) for i in range(len(all_uuids))
    }
    for item in results:
        item["relevance_score"] = sim_by_uuid.get(item["uuid"], 0.0)

    results.sort(key=lambda r: r["relevance_score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fuse_results(
    embedding_results: list[dict],
    metadata_results: list[dict],
    fetch_limit: int,
) -> list[dict]:
    """Reciprocal-rank fusion of two ranked lists.

    Each source assigns a score of ``1 / (k + rank)`` where *k* is a constant
    (60 is standard for RRF).  Items present in both lists receive the sum of
    their two scores; items in only one list keep their single score.
    """
    k = 60  # RRF smoothing constant

    scored: dict[str, dict] = {}

    for rank, item in enumerate(embedding_results):
        uid = item["uuid"]
        score = 1.0 / (k + rank)
        scored[uid] = {**item, "relevance_score": score}

    for rank, item in enumerate(metadata_results):
        uid = item["uuid"]
        score = 1.0 / (k + rank)
        if uid in scored:
            scored[uid]["relevance_score"] += score  # boost
        else:
            scored[uid] = {**item, "relevance_score": score}

    return list(scored.values())
