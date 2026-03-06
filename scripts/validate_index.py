"""Runtime validation: index pipeline round-trip."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
import uuid as uuid_mod
import numpy as np
from PIL import Image

# ── 1. Create test media files ──────────────────────────────────────────────

print("=== Step 1: Create test media files ===")
tmpdir = tempfile.mkdtemp(prefix="validate_index_")

image_specs = [
    ("red_landscape.jpg",    (640, 480), (255, 0, 0)),
    ("green_portrait.jpg",   (480, 640), (0, 255, 0)),
    ("blue_square.jpg",      (512, 512), (0, 0, 255)),
    ("yellow_wide.jpg",      (800, 200), (255, 255, 0)),
    ("purple_tiny.jpg",      (64, 64),   (128, 0, 128)),
]

image_paths = []
for fname, size, color in image_specs:
    path = os.path.join(tmpdir, fname)
    img = Image.new("RGB", size, color=color)
    img.save(path, "JPEG")
    image_paths.append(path)
    print(f"  Created {fname} ({size})")

print(f"  All 5 images saved to {tmpdir}")

# ── 2. Compute CLIP embeddings ──────────────────────────────────────────────

print("\n=== Step 2: Compute CLIP embeddings ===")
from index.clip_embeddings import embed_image, embed_images, embed_text

# Individual embeddings
individual_embeddings = []
for path in image_paths:
    emb = embed_image(path)
    assert emb.shape == (512,), f"Expected shape (512,), got {emb.shape}"
    norm = float(np.linalg.norm(emb))
    assert abs(norm - 1.0) < 1e-4, f"Expected norm ~1.0, got {norm}"
    individual_embeddings.append(emb)
    print(f"  embed_image({os.path.basename(path)}): shape={emb.shape}, norm={norm:.6f}")

# Pairwise cosine similarity - different images should produce different embeddings
print("  Checking pairwise cosine similarities...")
for i in range(len(individual_embeddings)):
    for j in range(i + 1, len(individual_embeddings)):
        cos_sim = float(np.dot(individual_embeddings[i], individual_embeddings[j]))
        assert cos_sim < 0.99, (
            f"Images {i} and {j} too similar: cosine={cos_sim:.4f}"
        )
        # print(f"    cos_sim({i},{j}) = {cos_sim:.4f}")
print("  All pairwise cosine similarities < 0.99")

# Batch embeddings
batch_embeddings = embed_images(image_paths)
assert batch_embeddings.shape == (5, 512), f"Expected (5,512), got {batch_embeddings.shape}"
print(f"  embed_images batch: shape={batch_embeddings.shape}")

# Check batch matches individual
for i in range(5):
    cos_sim = float(np.dot(individual_embeddings[i], batch_embeddings[i]))
    assert cos_sim > 0.99, (
        f"Batch embedding {i} doesn't match individual: cosine={cos_sim:.4f}"
    )
print("  Batch embeddings match individual embeddings (cosine > 0.99)")

# ── 3. Store in database ────────────────────────────────────────────────────

print("\n=== Step 3: Store in database ===")

import config
import index.store as store

# Use temporary DB
tmp_db_path = os.path.join(tmpdir, "test_media.db")
config.DB_PATH = tmp_db_path
store.DB_PATH = tmp_db_path

store.init_db()
print(f"  Database initialized at {tmp_db_path}")

test_uuids = [str(uuid_mod.uuid4()) for _ in range(5)]
test_albums = [["vacation", "summer"], ["work"], ["vacation"], ["nature", "landscapes"], ["misc"]]
test_labels = [["red", "solid"], ["green", "portrait"], ["blue", "square"], ["yellow", "wide"], ["purple", "tiny"]]
test_persons = [["Alice"], ["Bob"], ["Charlie"], [], ["Alice", "Bob"]]
test_descriptions = [
    {"summary": "A solid red image", "subjects": ["red rectangle"], "mood": "bold"},
    {"summary": "A solid green portrait image", "subjects": ["green rectangle"], "mood": "calm"},
    {"summary": "A solid blue square", "subjects": ["blue square"], "mood": "cool"},
    {"summary": "A yellow wide landscape", "subjects": ["yellow strip"], "mood": "cheerful"},
    {"summary": "A tiny purple image", "subjects": ["purple dot"], "mood": "mysterious"},
]
test_quality_scores = [0.9, 0.7, 0.5, 0.8, 0.3]
test_dates = [
    "2024-01-15T10:00:00",
    "2024-02-20T14:30:00",
    "2024-03-10T09:15:00",
    "2024-04-05T16:45:00",
    "2024-05-01T08:00:00",
]

for i in range(5):
    item = {
        "uuid": test_uuids[i],
        "path": image_paths[i],
        "media_type": "photo" if i < 4 else "video",
        "date": test_dates[i],
        "albums": test_albums[i],
        "labels": test_labels[i],
        "persons": test_persons[i],
        "description": test_descriptions[i],
        "embedding": individual_embeddings[i],
        "quality_score": test_quality_scores[i],
    }
    store.upsert_media(item)
print("  Upserted 5 media items")

# Verify count
count = store.count_media()
assert count == 5, f"Expected count 5, got {count}"
print(f"  count_media() = {count}")

# Verify get_indexed_uuids
indexed = store.get_indexed_uuids()
assert indexed == set(test_uuids), f"UUID mismatch: {indexed} vs {set(test_uuids)}"
print(f"  get_indexed_uuids() returned all 5 UUIDs")

# Verify get_media_by_uuids
records = store.get_media_by_uuids(test_uuids)
assert len(records) == 5, f"Expected 5 records, got {len(records)}"
uuid_to_rec = {r["uuid"]: r for r in records}

for i, uid in enumerate(test_uuids):
    rec = uuid_to_rec[uid]
    # JSON fields round-trip
    assert rec["albums"] == test_albums[i], f"Albums mismatch for {i}: {rec['albums']} vs {test_albums[i]}"
    assert rec["labels"] == test_labels[i], f"Labels mismatch for {i}: {rec['labels']} vs {test_labels[i]}"
    assert rec["persons"] == test_persons[i], f"Persons mismatch for {i}: {rec['persons']} vs {test_persons[i]}"
    assert rec["description"] == test_descriptions[i], f"Description mismatch for {i}: {rec['description']} vs {test_descriptions[i]}"
    # Embedding round-trip
    emb = rec["embedding"]
    assert emb is not None, f"Embedding is None for {i}"
    cos_sim = float(np.dot(emb, individual_embeddings[i]))
    assert cos_sim > 0.999, f"Embedding mismatch for {i}: cosine={cos_sim:.6f}"
print("  All fields survived serialization round-trip (including embeddings)")

# ── 4. Search ────────────────────────────────────────────────────────────────

print("\n=== Step 4: Search ===")

# 4a: search_by_text
query_emb = embed_text("red image")
results = store.search_by_text(query_emb, limit=5)
assert len(results) > 0, "search_by_text returned no results"
assert "similarity" in results[0], "Missing 'similarity' key in results"
# Verify sorted by descending similarity
for j in range(len(results) - 1):
    assert results[j]["similarity"] >= results[j + 1]["similarity"], "Results not sorted by similarity"
print(f"  search_by_text('red image'): {len(results)} results, top similarity={results[0]['similarity']:.4f}")

# 4b: search_by_metadata with album filter
results = store.search_by_metadata(albums=["vacation"])
vacation_uuids = {test_uuids[0], test_uuids[2]}  # items 0 and 2 have "vacation"
result_uuids = {r["uuid"] for r in results}
assert result_uuids == vacation_uuids, f"Album filter mismatch: {result_uuids} vs {vacation_uuids}"
print(f"  search_by_metadata(albums=['vacation']): {len(results)} results")

# 4c: search_by_metadata with date_range
results = store.search_by_metadata(date_range=("2024-02-01", "2024-03-31"))
result_uuids = {r["uuid"] for r in results}
expected = {test_uuids[1], test_uuids[2]}  # Feb and Mar items
assert result_uuids == expected, f"Date range filter mismatch: {result_uuids} vs {expected}"
print(f"  search_by_metadata(date_range): {len(results)} results")

# 4d: search_by_metadata with min_quality
results = store.search_by_metadata(min_quality=0.75)
result_uuids = {r["uuid"] for r in results}
expected = {test_uuids[0], test_uuids[3]}  # quality 0.9 and 0.8
assert result_uuids == expected, f"Quality filter mismatch: got {[r.get('quality_score') for r in results]}"
print(f"  search_by_metadata(min_quality=0.75): {len(results)} results")

# 4e: search_by_description
results = store.search_by_description("red")
assert len(results) > 0, "search_by_description('red') returned no results"
# The red image should be in results (description contains "red")
result_uuids = {r["uuid"] for r in results}
assert test_uuids[0] in result_uuids, "Red image not found in description search for 'red'"
assert "relevance_score" in results[0], "Missing 'relevance_score' in description search results"
print(f"  search_by_description('red'): {len(results)} results")

# 4f: hybrid_search
from curate.search import hybrid_search
results = hybrid_search("colorful landscape")
assert isinstance(results, list), f"hybrid_search returned {type(results)}"
if len(results) > 0:
    assert "relevance_score" in results[0], "Missing 'relevance_score' in hybrid_search results"
print(f"  hybrid_search('colorful landscape'): {len(results)} results")

# ── 5. Upsert idempotency ───────────────────────────────────────────────────

print("\n=== Step 5: Upsert idempotency ===")

updated_desc = {"summary": "UPDATED red image", "subjects": ["new subject"], "mood": "different"}
item = {
    "uuid": test_uuids[0],
    "path": image_paths[0],
    "media_type": "photo",
    "date": test_dates[0],
    "albums": test_albums[0],
    "labels": test_labels[0],
    "persons": test_persons[0],
    "description": updated_desc,
    "embedding": individual_embeddings[0],
    "quality_score": test_quality_scores[0],
}
store.upsert_media(item)

count = store.count_media()
assert count == 5, f"Expected count 5 after upsert, got {count}"
print(f"  count after upsert of same UUID: {count}")

rec = store.get_media_by_uuids([test_uuids[0]])[0]
assert rec["description"] == updated_desc, f"Description not updated: {rec['description']}"
print(f"  Description updated correctly: {rec['description']['summary']}")

# ── 6. Keyframe embeddings ──────────────────────────────────────────────────

print("\n=== Step 6: Keyframe embeddings ===")

video_uuid = test_uuids[4]  # the "video" item

# Create 3 fake keyframe embeddings (using slightly modified image embeddings)
kf_embeddings = []
for kf_idx in range(3):
    # Perturb the video's embedding slightly differently for each keyframe
    rng = np.random.RandomState(42 + kf_idx)
    noise = rng.randn(512).astype(np.float32) * 0.1
    kf_emb = individual_embeddings[4] + noise * (kf_idx + 1)
    kf_emb = kf_emb / np.linalg.norm(kf_emb)
    kf_embeddings.append(kf_emb)
    store.upsert_keyframe_embedding(
        media_uuid=video_uuid,
        keyframe_index=kf_idx,
        timestamp=float(kf_idx * 2.0),
        embedding=kf_emb,
    )
    print(f"  Stored keyframe {kf_idx} for video {video_uuid[:8]}...")

# Search keyframes
query_emb = embed_text("purple image")
kf_results = store.search_keyframes_by_text(query_emb, limit=5)
assert len(kf_results) > 0, "search_keyframes_by_text returned no results"
assert kf_results[0]["media_uuid"] == video_uuid, "Best keyframe should belong to our video"
assert "similarity" in kf_results[0], "Missing 'similarity' in keyframe results"
assert "keyframe_index" in kf_results[0], "Missing 'keyframe_index' in keyframe results"
print(f"  search_keyframes_by_text: {len(kf_results)} results, best keyframe_index={kf_results[0]['keyframe_index']}")

# ── 7. Delete ────────────────────────────────────────────────────────────────

print("\n=== Step 7: Delete ===")

# Delete one item
deleted = store.delete_media(test_uuids[0])
assert deleted is True, f"delete_media returned {deleted}, expected True"
count = store.count_media()
assert count == 4, f"Expected count 4 after delete, got {count}"
print(f"  Deleted one item, count = {count}")

# Delete all
num_deleted = store.delete_all_media()
assert num_deleted == 4, f"delete_all_media returned {num_deleted}, expected 4"
count = store.count_media()
assert count == 0, f"Expected count 0 after delete_all, got {count}"
print(f"  Deleted all items, count = {count}")

# ── Cleanup ──────────────────────────────────────────────────────────────────

import shutil
shutil.rmtree(tmpdir, ignore_errors=True)

print("\n" + "=" * 60)
print("ALL RUNTIME VALIDATIONS PASSED")
print("=" * 60)
