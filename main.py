"""Video Composer CLI — index your Apple Photos library and generate videos with AI."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime

from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("video-composer")


def cmd_index(args: argparse.Namespace) -> None:
    """Index media from Apple Photos into the local database."""
    from index.apple_photos import get_media_items
    from index.clip_embeddings import embed_image
    from index.vision_describe import describe_image, describe_images_batch
    from index.store import init_db, upsert_media, upsert_keyframe_embedding, get_indexed_uuids

    init_db()

    date_range = None
    if args.after or args.before:
        start = datetime.fromisoformat(args.after) if args.after else datetime.min
        end = datetime.fromisoformat(args.before) if args.before else datetime.max
        date_range = (start, end)

    tqdm.write(f"[index] Reading Apple Photos library (limit={args.limit}, album={args.album})...")
    items = get_media_items(limit=args.limit, album=args.album, date_range=date_range)
    tqdm.write(f"[index] Found {len(items)} media items")

    if not items:
        tqdm.write("[index] No items found. Check your filters.")
        return

    # Skip already-indexed items unless --force is given
    skipped = 0
    if not args.force:
        existing_uuids = get_indexed_uuids()
        original_count = len(items)
        items = [item for item in items if item.uuid not in existing_uuids]
        skipped = original_count - len(items)
        if skipped > 0:
            tqdm.write(f"[index] Skipped {skipped} already-indexed items (use --force to re-index)")
        if not items:
            tqdm.write("[index] All items already indexed. Nothing to do.")
            return

    for item in tqdm(items, desc="[index] Processing media", unit="item"):
        if item.path is None:
            tqdm.write(f"[index]   Skipping {item.uuid[:8]} — no file path (iCloud-only?)")
            continue

        # Determine which image to embed (photo itself, or first keyframe for video)
        embed_path = item.path if item.media_type == "photo" else (
            item.keyframe_paths[0] if item.keyframe_paths else None
        )

        # CLIP embedding
        embedding = None
        if embed_path:
            try:
                tqdm.write(f"[index]   Computing CLIP embedding for {item.uuid[:8]}...")
                embedding = embed_image(embed_path)
            except Exception as e:
                tqdm.write(f"[index]   CLIP embedding failed: {e}")

        # Claude Vision description (optional, controlled by flag)
        description = {}
        quality_score = None
        if args.describe:
            try:
                tqdm.write(f"[index]   Getting Claude Vision description for {item.uuid[:8]}...")
                description = describe_image(embed_path or item.path)
                quality_score = description.get("quality_score")
            except Exception as e:
                tqdm.write(f"[index]   Vision description failed: {e}")

        # Store in DB
        record = {
            "uuid": item.uuid,
            "path": item.path,
            "media_type": item.media_type,
            "date": item.date.isoformat() if item.date else None,
            "lat": item.location[0] if item.location else None,
            "lon": item.location[1] if item.location else None,
            "albums": item.albums,
            "labels": item.labels,
            "persons": item.persons,
            "width": item.width,
            "height": item.height,
            "duration": item.duration,
            "description": description,
            "embedding": embedding,
            "quality_score": quality_score,
        }
        upsert_media(record)

        # Embed ALL keyframes for videos (enables temporal search)
        if item.media_type == "video" and item.keyframe_paths:
            tqdm.write(f"[index]   Embedding {len(item.keyframe_paths)} keyframes...")
            from index.clip_embeddings import embed_images
            keyframe_embs = embed_images(item.keyframe_paths)
            for ki, (kpath, kemb) in enumerate(zip(item.keyframe_paths, keyframe_embs)):
                timestamp = ki * 2.0  # KEYFRAME_INTERVAL_SEC
                upsert_keyframe_embedding(item.uuid, ki, timestamp, kemb)

    tqdm.write(f"\n[index] Indexing complete. {len(items)} items processed.")


def cmd_search(args: argparse.Namespace) -> None:
    """Search the indexed media library."""
    from index.store import init_db

    init_db()

    print(f'[search] Searching for: "{args.query}"')

    if args.fast:
        from index.store import search_by_description
        print("[search] Using fast text search (no CLIP model)")
        results = search_by_description(query=args.query, limit=args.limit)
    else:
        from curate.search import hybrid_search
        results = hybrid_search(
            query=args.query,
            albums=args.albums.split(",") if args.albums else None,
            persons=args.persons.split(",") if args.persons else None,
            min_quality=args.min_quality,
            limit=args.limit,
        )

    if not results:
        print("[search] No results found.")
        return

    print(f"[search] Found {len(results)} results:\n")
    for i, r in enumerate(results):
        desc = r.get("description", {})
        summary = desc.get("summary", "") if isinstance(desc, dict) else ""
        print(f"  {i + 1}. [{r['media_type']}] {r['uuid'][:12]}... "
              f"score={r.get('relevance_score', 0):.4f}")
        if summary:
            print(f"     {summary}")
        print(f"     date={r.get('date', '?')}  quality={r.get('quality_score', '?')}")
        print()


def cmd_generate(args: argparse.Namespace) -> None:
    """Generate a video from a creative prompt."""
    from index.store import init_db
    from curate.search import hybrid_search
    from curate.director import create_edit_decision_list
    from assemble.builder import build_video

    try:
        init_db()

        # Step 1: Search for relevant clips
        print(f'[generate] Searching for clips matching: "{args.prompt}"')
        candidates = hybrid_search(
            query=args.prompt,
            albums=args.albums.split(",") if args.albums else None,
            persons=args.persons.split(",") if args.persons else None,
            min_quality=args.min_quality,
            limit=args.num_candidates,
        )

        if not candidates:
            print("[generate] No matching media found. Index some media first with: python main.py index")
            return

        print(f"[generate] Found {len(candidates)} candidate clips")

        # Step 2: AI Director creates an edit decision list
        print(f"[generate] Asking AI director to plan the video...")
        edl = create_edit_decision_list(
            candidates=candidates,
            prompt=args.prompt,
            target_duration=args.duration,
        )

        print(f'[generate] EDL created: "{edl.title}"')
        print(f"[generate]   Shots: {len(edl.shots)}")
        print(f"[generate]   Duration: {edl.estimated_duration:.1f}s")
        print(f"[generate]   Music mood: {edl.music_mood}")
        print(f"[generate]   Summary: {edl.narrative_summary}")

        # --dry-run: show the EDL without rendering
        if args.dry_run:
            print("\n[generate] Dry run — skipping render. EDL shots:")
            for i, shot in enumerate(edl.shots, 1):
                dur = shot.end_time - shot.start_time
                print(f"  {i}. [{shot.role}] {shot.media_type} {dur:.1f}s — {shot.reason}")
            return

        # Step 3: Assemble the video
        print(f"\n[generate] Assembling video with theme '{args.theme}'...")
        output = build_video(
            edl=edl,
            theme_name=args.theme,
            music_path=args.music,
            output_path=args.output,
        )

        print(f"\n[generate] Video saved to: {output}")

    except KeyboardInterrupt:
        print("\n[generate] Interrupted by user.")
        sys.exit(1)
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc, exc_info=True)
        print(f"\n[generate] ERROR: {exc}")
        sys.exit(1)


def cmd_preview(args: argparse.Namespace) -> None:
    """Preview a video plan without rendering — shows the EDL for review."""
    from index.store import init_db
    from curate.search import hybrid_search
    from curate.director import create_edit_decision_list

    init_db()

    # Step 1: Search for relevant clips
    print(f'[preview] Searching for clips matching: "{args.prompt}"')
    candidates = hybrid_search(
        query=args.prompt,
        albums=args.albums.split(",") if args.albums else None,
        persons=args.persons.split(",") if args.persons else None,
        min_quality=args.min_quality,
        limit=args.num_candidates,
    )

    if not candidates:
        print("[preview] No matching media found. Index some media first with: python main.py index")
        return

    print(f"[preview] Found {len(candidates)} candidate clips")

    # Step 2: AI Director creates an edit decision list
    print(f"[preview] Asking AI director to plan the video...")
    edl = create_edit_decision_list(
        candidates=candidates,
        prompt=args.prompt,
        target_duration=args.duration,
    )

    # Display the EDL for review
    print()
    print("=" * 70)
    print(f"  VIDEO PREVIEW — \"{edl.title}\"")
    print("=" * 70)
    print()
    print(f"  Narrative:  {edl.narrative_summary}")
    print(f"  Music mood: {edl.music_mood}")
    print(f"  Est. duration: {edl.estimated_duration:.1f}s")
    print(f"  Total shots: {len(edl.shots)}")
    print()
    print("-" * 70)
    print(f"  {'#':<4} {'Role':<12} {'Type':<7} {'Duration':>8}  Description")
    print("-" * 70)

    for i, shot in enumerate(edl.shots, 1):
        dur = shot.end_time - shot.start_time
        reason = shot.reason[:50] + "..." if len(shot.reason) > 50 else shot.reason
        print(f"  {i:<4} {shot.role:<12} {shot.media_type:<7} {dur:>7.1f}s  {reason}")

    print("-" * 70)
    print()
    print("  To render this video, run:")
    prompt_escaped = args.prompt.replace('"', '\\"')
    print(f'    python main.py generate "{prompt_escaped}"')
    print()


def cmd_stats(args: argparse.Namespace) -> None:
    """Show stats about the indexed library."""
    from index.store import init_db, get_all_embeddings, _get_client

    init_db()
    client = _get_client()

    resp = client.table("media").select("*").execute()
    rows = resp.data or []

    total = len(rows)
    photos = sum(1 for r in rows if r.get("media_type") == "photo")
    videos = sum(1 for r in rows if r.get("media_type") == "video")
    with_desc = sum(1 for r in rows if r.get("description") and r["description"] != {})

    uuids, _ = get_all_embeddings()
    with_emb = len(uuids)

    print(f"[stats] Indexed media: {total}")
    print(f"[stats]   Photos: {photos}")
    print(f"[stats]   Videos: {videos}")
    print(f"[stats]   With embeddings: {with_emb}")
    print(f"[stats]   With AI descriptions: {with_desc}")

    if total == 0:
        return

    dates = [r["date"] for r in rows if r.get("date")]
    if dates:
        earliest = min(dates)[:10]
        latest = max(dates)[:10]
        print(f"[stats]   Date range: {earliest} to {latest}")

    album_counts: dict[str, int] = {}
    for row in rows:
        for album in (row.get("albums") or []):
            album_counts[album] = album_counts.get(album, 0) + 1
    if album_counts:
        top_albums = sorted(album_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        print("[stats]   Top albums:")
        for name, count in top_albums:
            print(f"[stats]     {name}: {count}")

    person_counts: dict[str, int] = {}
    for row in rows:
        for person in (row.get("persons") or []):
            person_counts[person] = person_counts.get(person, 0) + 1
    if person_counts:
        top_persons = sorted(person_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        print("[stats]   Top persons:")
        for name, count in top_persons:
            print(f"[stats]     {name}: {count}")

    quality_scores = [r["quality_score"] for r in rows if r.get("quality_score") is not None]
    if quality_scores:
        avg_quality = sum(quality_scores) / len(quality_scores)
        print(f"[stats]   Average quality score: {avg_quality:.1f}")


def cmd_list(args: argparse.Namespace) -> None:
    """List indexed media in a formatted table."""
    from index.store import init_db, list_media

    init_db()

    items = list_media(limit=args.limit, offset=0, sort_by=args.sort)

    if not items:
        print("[list] No indexed media found.")
        return

    # Print table header
    print()
    print(f"  {'UUID':<14} {'Type':<7} {'Date':<12} {'Albums':<20} {'Quality':>7}  Description")
    print("  " + "-" * 90)

    for item in items:
        uuid_short = item["uuid"][:12]
        media_type = item.get("media_type", "?")
        date_str = item.get("date", "")[:10] if item.get("date") else "—"
        albums = ", ".join(item.get("albums", [])) if item.get("albums") else "—"
        if len(albums) > 18:
            albums = albums[:17] + "…"
        quality = item.get("quality_score")
        quality_str = f"{quality:.0f}" if quality is not None else "—"
        desc = item.get("description", {})
        summary = ""
        if isinstance(desc, dict):
            summary = desc.get("summary", "")
        if len(summary) > 60:
            summary = summary[:57] + "..."

        print(f"  {uuid_short:<14} {media_type:<7} {date_str:<12} {albums:<20} {quality_str:>7}  {summary}")

    print()
    print(f"  Showing {len(items)} item(s) (sorted by {args.sort})")
    print()


def cmd_delete(args: argparse.Namespace) -> None:
    """Delete media from the indexed library."""
    from index.store import (
        init_db, delete_media, delete_all_media, count_media,
        search_by_metadata, get_media_by_uuids, _get_client,
    )

    init_db()

    if args.all:
        total = count_media()
        if total == 0:
            print("[delete] No media to delete.")
            return
        print(f"[delete] This will delete ALL {total} indexed media items.")
        if not args.yes:
            print("[delete] Use --yes to confirm, or run interactively:")
            try:
                answer = input("[delete] Are you sure? [y/N] ")
                if answer.strip().lower() not in ("y", "yes"):
                    print("[delete] Aborted.")
                    return
            except (EOFError, KeyboardInterrupt):
                print("\n[delete] Aborted.")
                return
        deleted = delete_all_media()
        print(f"[delete] Deleted {deleted} item(s).")
        return

    if args.album:
        # Find all items in the given album
        items = search_by_metadata(albums=[args.album])
        if not items:
            print(f'[delete] No items found in album "{args.album}".')
            return
        print(f'[delete] Found {len(items)} item(s) in album "{args.album}":')
        for item in items[:10]:
            print(f"  - {item['uuid'][:12]}... [{item.get('media_type', '?')}]")
        if len(items) > 10:
            print(f"  ... and {len(items) - 10} more")
        if not args.yes:
            print("[delete] Use --yes to confirm, or run interactively:")
            try:
                answer = input("[delete] Delete these items? [y/N] ")
                if answer.strip().lower() not in ("y", "yes"):
                    print("[delete] Aborted.")
                    return
            except (EOFError, KeyboardInterrupt):
                print("\n[delete] Aborted.")
                return
        deleted_count = 0
        for item in items:
            if delete_media(item["uuid"]):
                deleted_count += 1
        print(f"[delete] Deleted {deleted_count} item(s).")
        return

    if args.uuid:
        # Try exact match first, then partial match
        uuid_arg = args.uuid
        matches = get_media_by_uuids([uuid_arg])
        if not matches:
            # Try partial match via Supabase ilike
            client = _get_client()
            if len(uuid_arg) >= 8:
                resp = client.table("media").select("uuid").ilike("uuid", f"{uuid_arg}%").execute()
                matching_uuids = [row["uuid"] for row in resp.data]
            else:
                matching_uuids = []

            if len(matching_uuids) == 0:
                print(f'[delete] No media found matching UUID "{uuid_arg}".')
                return
            elif len(matching_uuids) > 1:
                print(f'[delete] Multiple matches for "{uuid_arg}":')
                for uid in matching_uuids[:10]:
                    print(f"  - {uid}")
                print("[delete] Please provide a more specific UUID.")
                return
            else:
                uuid_arg = matching_uuids[0]
                matches = get_media_by_uuids([uuid_arg])

        item = matches[0]
        desc = item.get("description", {})
        summary = desc.get("summary", "") if isinstance(desc, dict) else ""
        print(f"[delete] Will delete: {item['uuid'][:12]}... [{item.get('media_type', '?')}]")
        if summary:
            print(f"  {summary}")

        if delete_media(item["uuid"]):
            print("[delete] Deleted 1 item.")
        else:
            print("[delete] Failed to delete item.")
        return

    print("[delete] Specify a UUID, --all, or --album. See --help.")


def cmd_reindex(args: argparse.Namespace) -> None:
    """Re-compute CLIP embeddings (and optionally descriptions) for all indexed items."""
    from index.clip_embeddings import embed_image
    from index.store import init_db, list_media, upsert_media, count_media

    init_db()

    total = count_media()
    if total == 0:
        print("[reindex] No indexed media found.")
        return

    print(f"[reindex] Re-indexing {total} item(s)...")
    if args.describe:
        print("[reindex] Will also re-run Claude Vision descriptions (--describe)")

    # Fetch all items in batches
    batch_size = 100
    processed = 0
    skipped = 0

    all_items = []
    for offset in range(0, total, batch_size):
        batch = list_media(limit=batch_size, offset=offset, sort_by="recent")
        all_items.extend(batch)

    for item in tqdm(all_items, desc="[reindex] Processing", unit="item"):
        path = item.get("path")
        if not path or not os.path.exists(path):
            tqdm.write(f"[reindex]   Skipping {item['uuid'][:8]} -- no valid path")
            skipped += 1
            continue

        embed_path = path

        # Re-compute CLIP embedding
        try:
            embedding = embed_image(embed_path)
            item["embedding"] = embedding
        except Exception as e:
            tqdm.write(f"[reindex]   CLIP failed for {item['uuid'][:8]}: {e}")
            skipped += 1
            continue

        # Optionally re-run description
        if args.describe:
            try:
                from index.vision_describe import describe_image
                description = describe_image(embed_path)
                item["description"] = description
                item["quality_score"] = description.get("quality_score")
            except Exception as e:
                tqdm.write(f"[reindex]   Vision failed for {item['uuid'][:8]}: {e}")

        upsert_media(item)
        processed += 1

    print(f"\n[reindex] Done. Processed: {processed}, Skipped: {skipped}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="video-composer",
        description="AI-powered video composer from your Apple Photos library",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- index ---
    idx = subparsers.add_parser("index", help="Index media from Apple Photos")
    idx.add_argument("--limit", type=int, default=None, help="Max items to index")
    idx.add_argument("--album", type=str, default=None, help="Filter to album name")
    idx.add_argument("--after", type=str, default=None, help="Start date (ISO format)")
    idx.add_argument("--before", type=str, default=None, help="End date (ISO format)")
    idx.add_argument("--describe", action="store_true",
                     help="Use Claude Vision to describe each item (costs API credits)")
    idx.add_argument("--force", action="store_true",
                     help="Re-index items even if already in the database")

    # --- search ---
    srch = subparsers.add_parser("search", help="Search indexed media")
    srch.add_argument("query", type=str, help="Natural language search query")
    srch.add_argument("--albums", type=str, default=None, help="Comma-separated album filter")
    srch.add_argument("--persons", type=str, default=None, help="Comma-separated person filter")
    srch.add_argument("--min-quality", type=float, default=None, dest="min_quality")
    srch.add_argument("--limit", type=int, default=20)
    srch.add_argument("--fast", action="store_true",
                      help="Fast text-only search over descriptions (no CLIP model needed)")

    # --- delete ---
    dlt = subparsers.add_parser("delete", help="Delete media from the index")
    dlt.add_argument("uuid", type=str, nargs="?", default=None,
                     help="UUID (or partial UUID, 8+ chars) of item to delete")
    dlt.add_argument("--all", action="store_true",
                     help="Delete all indexed media")
    dlt.add_argument("--album", type=str, default=None,
                     help="Delete all items from a specific album")
    dlt.add_argument("--yes", action="store_true",
                     help="Skip confirmation prompt for destructive operations")

    # --- reindex ---
    reidx = subparsers.add_parser("reindex", help="Re-compute CLIP embeddings for all items")
    reidx.add_argument("--describe", action="store_true",
                       help="Also re-run Claude Vision descriptions")

    # --- generate ---
    gen = subparsers.add_parser("generate", help="Generate a video from a creative prompt")
    gen.add_argument("prompt", type=str, help="Creative brief (e.g., 'summer vacation highlights')")
    gen.add_argument("--duration", type=float, default=60.0, help="Target duration in seconds")
    gen.add_argument("--theme", type=str, default="minimal",
                     choices=["minimal", "warm_nostalgic", "bold_modern"])
    gen.add_argument("--music", type=str, default=None, help="Path to background music file")
    gen.add_argument("--output", type=str, default=None, help="Output file path")
    gen.add_argument("--albums", type=str, default=None, help="Comma-separated album filter")
    gen.add_argument("--persons", type=str, default=None, help="Comma-separated person filter")
    gen.add_argument("--min-quality", type=float, default=None, dest="min_quality")
    gen.add_argument("--num-candidates", type=int, default=30, dest="num_candidates",
                     help="Number of candidate clips to consider")
    gen.add_argument("--dry-run", action="store_true", dest="dry_run",
                     help="Show the EDL without rendering the video")

    # --- preview ---
    prev = subparsers.add_parser("preview", help="Preview a video plan without rendering")
    prev.add_argument("prompt", type=str, help="Creative brief (e.g., 'summer vacation highlights')")
    prev.add_argument("--duration", type=float, default=60.0, help="Target duration in seconds")
    prev.add_argument("--albums", type=str, default=None, help="Comma-separated album filter")
    prev.add_argument("--persons", type=str, default=None, help="Comma-separated person filter")
    prev.add_argument("--min-quality", type=float, default=None, dest="min_quality")
    prev.add_argument("--num-candidates", type=int, default=30, dest="num_candidates",
                     help="Number of candidate clips to consider")

    # --- list ---
    lst = subparsers.add_parser("list", help="List indexed media in a table")
    lst.add_argument("--limit", type=int, default=20, help="Number of items to show (default: 20)")
    lst.add_argument("--sort", type=str, default="date", choices=["date", "quality", "recent"],
                     help="Sort order (default: date)")

    # --- stats ---
    subparsers.add_parser("stats", help="Show library stats")

    args = parser.parse_args()

    commands = {
        "index": cmd_index,
        "search": cmd_search,
        "delete": cmd_delete,
        "reindex": cmd_reindex,
        "generate": cmd_generate,
        "preview": cmd_preview,
        "stats": cmd_stats,
        "list": cmd_list,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
