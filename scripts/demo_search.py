"""Demo: show the full search pipeline input/output at each step."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import json
import config
from index.store import get_all_embeddings

QUERY = "outdoor scenery"

# Step 1: Embed the text query
print("=== STEP 1: Embed the text query ===")
print(f"Input string: \"{QUERY}\"")
print()

if config.USE_TWELVELABS:
    from index.twelvelabs_embed import embed_text
    query_vec = embed_text(QUERY)
    engine = f"Twelve Labs Marengo ({config.TWELVELABS_MODEL})"
else:
    from index.clip_embeddings import embed_text as clip_embed_text
    query_vec = clip_embed_text(QUERY)
    engine = "CLIP ViT-B-32"

print(f"Engine: {engine}")
print(f"Output shape: {query_vec.shape}  dtype: {query_vec.dtype}")
floats_str = ", ".join(f"{v:.5f}" for v in query_vec[:8])
print(f"First 8 floats: [{floats_str}, ...]")
print(f"L2 norm: {np.linalg.norm(query_vec):.4f} (normalized to 1.0)")
print()

# Step 2: Load stored embeddings from SQLite
print("=== STEP 2: Load stored embeddings from SQLite ===")
uuids, matrix = get_all_embeddings()
print(f"Loaded {len(uuids)} embeddings, matrix shape: {matrix.shape}")
if len(uuids) > 0:
    stored_str = ", ".join(f"{v:.5f}" for v in matrix[0][:8])
    print(f"Stored embedding[0] first 8 floats: [{stored_str}, ...]")
print()

# Step 3: Cosine similarity
print("=== STEP 3: Cosine similarity (query_vec dot stored_vec) ===")
scores = matrix @ query_vec
for uid, score in zip(uuids, scores):
    print(f"  {uid[:12]}  cosine_similarity = {score:.4f}")
print()

# Step 4: Full hybrid search
print("=== STEP 4: hybrid_search() merged result ===")
from curate.search import hybrid_search
results = hybrid_search(query=QUERY, limit=5)
for r in results:
    r.pop("embedding", None)
    print(f"  uuid: {r['uuid'][:12]}")
    print(f"  type: {r['media_type']}")
    print(f"  score: {r.get('relevance_score', 'N/A')}")
    fname = r["path"].split("/")[-1] if r.get("path") else "?"
    print(f"  file: {fname}")
    print(f"  duration: {r.get('duration')}s  resolution: {r.get('width')}x{r.get('height')}")
    print()

# Step 5: API JSON response
print("=== STEP 5: What POST /api/search returns ===")
print(f"Request body: {json.dumps({'query': QUERY, 'limit': 5})}")
print()
api_input = {"query": QUERY, "limit": 5, "fast": False}
api_output = {
    "results": [{
        "uuid": r["uuid"],
        "media_type": r["media_type"],
        "path": r["path"],
        "date": r.get("date"),
        "width": r.get("width"),
        "height": r.get("height"),
        "duration": r.get("duration"),
        "relevance_score": r.get("relevance_score"),
        "albums": json.loads(r["albums"]) if isinstance(r.get("albums"), str) else r.get("albums", []),
        "description": json.loads(r["description"]) if isinstance(r.get("description"), str) else r.get("description", {}),
    } for r in results],
    "count": len(results),
    "query": QUERY,
}
print("Response JSON:")
print(json.dumps(api_output, indent=2, default=str))
