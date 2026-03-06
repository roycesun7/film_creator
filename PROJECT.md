# Video Composer

AI-powered video editing tool with a web UI. Upload photos and videos, search them semantically using Twelve Labs Marengo multimodal embeddings, and generate polished videos from natural language prompts with an AI director.

## Vision

Build an incredibly smooth video editing experience where you can upload clips, search them semantically, and have AI generate videos from your library. Inspired by [Eden.so](https://eden.so/) and [Cardboard](https://www.usecardboard.com/), but differentiated by being **library-first** — starting from your organized media collection rather than a blank timeline.

## Architecture

```
┌─────────────────────────────────────────────┐
│          React + Vite Frontend              │
│  Dashboard | Library | Search | Studio      │
│  Tailwind CSS, React Router, TanStack Query │
└─────────────────────┬───────────────────────┘
                      │ REST API (proxy :5173→:8000)
┌─────────────────────▼───────────────────────┐
│          FastAPI Backend (api.py)            │
│  File upload, thumbnail gen, job tracking   │
│  Wraps index/, curate/, assemble/ layers    │
└─────────────────────┬───────────────────────┘
                      │
┌─────────────────────▼───────────────────────┐
│              INDEXING LAYER                  │
│  Upload → Twelve Labs Marengo (1024-d)      │
│         + Claude Vision descriptions (opt)  │
│         + CLIP ViT-B-32 fallback (512-d)    │
│         → SQLite + vector index             │
└─────────────────────┬───────────────────────┘
                      │
┌─────────────────────▼───────────────────────┐
│            CURATION LAYER                   │
│  Hybrid search (embeddings + metadata + RRF)│
│  + Temporal segment search for videos       │
│  + Claude "Director" → Edit Decision List   │
└─────────────────────┬───────────────────────┘
                      │
┌─────────────────────▼───────────────────────┐
│            ASSEMBLY LAYER                   │
│  moviepy: Ken Burns, transitions, titles,   │
│  closing card, music, color themes → MP4    │
└─────────────────────────────────────────────┘
```

## Tech Stack

- **Python 3.11** with venv at `.venv/`
- **FastAPI + uvicorn** — REST API backend
- **React + Vite + TypeScript + Tailwind CSS** — web frontend
- **Twelve Labs Marengo** — multimodal video-native embeddings (1024-d, visual + audio + temporal)
- **open-clip-torch** (ViT-B-32) — local CLIP fallback embeddings (512-d)
- **anthropic SDK** — Claude Vision for descriptions, Claude as video director
- **moviepy 2.x** — video assembly, Ken Burns, transitions, export
- **SQLite** — media index + segment embeddings (at `media_index.db`)
- **osxphotos** — optional Apple Photos library import

## Project Structure

```
video-composer/
├── config.py                     # Settings, env loading, model config
├── api.py                        # FastAPI backend (REST API, upload, jobs)
├── main.py                       # CLI entry point (index, search, generate)
├── index/
│   ├── twelvelabs_embed.py       # Twelve Labs Marengo embeddings (primary)
│   ├── clip_embeddings.py        # CLIP embed_image/embed_text (fallback)
│   ├── apple_photos.py           # osxphotos integration (optional)
│   ├── vision_describe.py        # Claude Vision structured descriptions
│   └── store.py                  # SQLite DB, vector search, segment embeddings
├── curate/
│   ├── search.py                 # Hybrid search (Twelve Labs/CLIP + metadata + RRF)
│   └── director.py               # Claude AI director → EditDecisionList
├── assemble/
│   ├── themes.py                 # 3 themes, Ken Burns, fit_to_resolution, color filters
│   └── builder.py                # moviepy pipeline: clips → transitions → music → MP4
├── frontend/                     # React + Vite + Tailwind web UI
│   ├── src/
│   │   ├── App.tsx               # Router + sidebar navigation
│   │   ├── api.ts                # API client + TypeScript types
│   │   └── pages/
│   │       ├── Dashboard.tsx     # Stats overview (auto-refreshes every 5s)
│   │       ├── Library.tsx       # Media grid, upload, drag & drop, video preview
│   │       ├── SearchPage.tsx    # Semantic search
│   │       ├── Studio.tsx        # Prompt → preview EDL → render video
│   │       └── Videos.tsx        # Browse and play generated videos
│   ├── package.json
│   └── vite.config.ts            # Proxy /api → FastAPI
├── scripts/
│   └── demo_search.py            # Shows full search pipeline input/output
├── uploads/                      # Uploaded media files (gitignored)
├── output/                       # Generated videos (gitignored)
├── .thumbnails/                  # Cached thumbnails (gitignored)
├── tests/                        # 162 pytest tests
├── .env                          # API keys (gitignored)
├── requirements.txt
├── pytest.ini
└── Makefile
```

## Running the App

```bash
cd video-composer
source .venv/bin/activate

# Terminal 1 — API server
make api           # starts FastAPI on :8000

# Terminal 2 — Frontend dev server
make frontend      # starts Vite on :5173
```

Open **http://localhost:5173** in your browser.

## Web UI Pages

| Page | What it does |
|---|---|
| **Dashboard** | Stats overview — total indexed, photos, videos, embedding count, recent jobs. Auto-refreshes every 5s. |
| **Library** | Thumbnail grid of all indexed media. Click "Add Media" or drag & drop files to upload. Videos show duration badge and inline playback in detail modal. Library updates instantly after upload. |
| **Search** | Natural language search using Twelve Labs multimodal embeddings (or fast text search mode) |
| **Studio** | Enter a creative brief → AI director plans an EDL → preview shot list → render video → watch inline |
| **Videos** | Browse and play all generated videos |

## Embedding Pipeline

The system uses **Twelve Labs Marengo** as the primary embedding engine with **CLIP as fallback**.

| | Twelve Labs Marengo (primary) | CLIP ViT-B-32 (fallback) |
|---|---|---|
| **Dimensions** | 1024 | 512 |
| **Video handling** | Full multimodal — visual, audio, temporal dynamics fused per segment | Single frame extracted every 2s, no audio |
| **Audio** | First-class — speech, music, ambient sounds | None |
| **Search** | Any-to-any: text→video, text→image in unified latent space | Image-text only, no audio understanding |
| **Activation** | Set `TWELVELABS_API_KEY` in `.env` | Automatic when Twelve Labs key is absent |

### Upload Flow

1. File saved to `uploads/`, media record inserted into SQLite **immediately** (with metadata, no embedding yet)
2. Library grid updates instantly — no page reload needed
3. Background thread starts embedding computation:
   - Twelve Labs Marengo API call (~3-5s for images, ~10-30s for videos depending on length)
   - Falls back to local CLIP if Twelve Labs fails
4. Embedding (1024 floats × 4 bytes = 4KB BLOB) written to the media record in SQLite
5. Dashboard "With Embeddings" counter updates automatically via 5s polling

### Search Flow

1. **Query embedding**: text query → Twelve Labs `embed_text()` → 1024-d vector (~200ms)
2. **Vector search**: load all stored embeddings from SQLite, compute cosine similarity (dot product of normalized vectors), rank by score
3. **Metadata search**: text-match against descriptions, labels, albums
4. **RRF merge**: Reciprocal Rank Fusion combines both ranked lists — items in both get boosted
5. **Response**: ranked results with `relevance_score`, media metadata, no raw embeddings

### Example Search Pipeline

```
Input:  POST /api/search  {"query": "outdoor scenery", "limit": 5}

Step 1 — Embed query:
  "outdoor scenery" → Marengo → [-0.00021, -0.03174, -0.00311, ...] (1024 floats)

Step 2 — Load stored embeddings:
  SELECT uuid, embedding FROM media WHERE embedding IS NOT NULL
  → deserialize BLOBs → matrix shape (N, 1024)

Step 3 — Cosine similarity:
  score = query_vec · stored_vec  (dot product, range -1.0 to 1.0)
  aee1cf7c...  cosine_similarity = 0.2996

Step 4 — Hybrid merge (RRF):
  Vector rank + metadata rank → fused score

Output:
{
  "results": [{
    "uuid": "aee1cf7c-...",
    "media_type": "video",
    "width": 720, "height": 1280,
    "duration": 7.58,
    "relevance_score": 0.033
  }],
  "count": 1,
  "query": "outdoor scenery"
}
```

### Storage Schema (SQLite)

```sql
-- Main media table
media (
  uuid TEXT PRIMARY KEY,
  path TEXT,                    -- local file path in uploads/
  media_type TEXT,              -- "photo" or "video"
  date TEXT,                    -- ISO 8601
  width INTEGER, height INTEGER,
  duration REAL,                -- seconds (videos only)
  embedding BLOB,               -- 1024 × float32 = 4096 bytes (or 512 × float32 for CLIP)
  description TEXT,             -- JSON from Claude Vision
  quality_score REAL,
  albums TEXT, labels TEXT, persons TEXT,  -- JSON arrays
  indexed_at TEXT
)

-- Per-segment embeddings for temporal video search
keyframe_embeddings (
  media_uuid TEXT,
  keyframe_index INTEGER,
  timestamp_sec REAL,           -- segment start time
  embedding BLOB                -- 1024 × float32
)
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/stats` | Library overview stats (total, photos, videos, with_embeddings) |
| `GET` | `/api/media` | Paginated media list (sort: date, quality, recent) |
| `GET` | `/api/media/{uuid}` | Single media detail |
| `GET` | `/api/media/{uuid}/thumbnail` | Serve photo/video thumbnail (JPEG) |
| `GET` | `/api/media/{uuid}/video` | Serve original video file for playback |
| `DELETE` | `/api/media/{uuid}` | Delete a media item |
| `POST` | `/api/upload` | Upload photos/videos (multipart). Inserts record immediately, embeds in background. |
| `POST` | `/api/search` | Semantic or text search. Returns ranked results without raw embeddings. |
| `POST` | `/api/index` | Import from Apple Photos (background job) |
| `POST` | `/api/preview` | AI director → EDL preview |
| `POST` | `/api/generate` | Render video (background job) |
| `GET` | `/api/jobs/{id}` | Poll job status |
| `GET` | `/api/jobs` | List all jobs |
| `GET` | `/api/videos` | List generated MP4s |

## CLI Commands

```bash
source .venv/bin/activate

# Indexing (Apple Photos — requires Full Disk Access)
python main.py index --limit 50
python main.py index --album "Vacation" --describe

# Browsing
python main.py stats
python main.py list --limit 30 --sort quality

# Searching
python main.py search "beach sunset"
python main.py search "beach sunset" --fast

# Video generation
python main.py preview "summer highlights"
python main.py generate "summer highlights"
python main.py generate "family trip" --duration 30 --theme warm_nostalgic --music ~/song.mp3

# Management
python main.py reindex
python main.py delete --all --yes
```

## Themes

| Name | Style |
|---|---|
| `minimal` | White text, crossfade transitions, Ken Burns on photos |
| `warm_nostalgic` | Warm color toning, fade-through-black transitions |
| `bold_modern` | Large bold text, high contrast, no Ken Burns |

## Setup Requirements

1. **macOS** (for Apple Photos integration; file upload works anywhere)
2. **FFmpeg** — `brew install ffmpeg`
3. **API keys** in `.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   TWELVELABS_API_KEY=tlk_...
   ```
4. **Python deps**: `pip install -r requirements.txt`
5. **Frontend deps**: `cd frontend && npm install`

## Testing

```bash
make test              # 162 tests, all passing
make test-fast         # skip slow embedding tests
make test-integration  # end-to-end pipeline tests
make lint              # compile-check all source files
```

## Key Design Decisions

- **Twelve Labs Marengo over CLIP**: CLIP (2021) is image-only, 512-d, no audio, no temporal understanding. Marengo produces 1024-d multimodal embeddings that jointly capture visual, audio, and temporal information. ~15% better video retrieval accuracy on benchmarks.
- **Graceful fallback**: If `TWELVELABS_API_KEY` is not set, the system automatically uses local CLIP. No code changes needed. If Twelve Labs fails mid-upload, that file falls back to CLIP silently.
- **Immediate insert, background embed**: Upload endpoint inserts the media record into SQLite immediately (so the UI updates instantly), then computes embeddings in a background thread. This avoids the UI feeling stuck while waiting for API calls.
- **Dimension-aware search**: `get_all_embeddings()` filters by `EMBEDDING_DIM` — only embeddings matching the active engine's dimension (1024 for Twelve Labs, 512 for CLIP) are used in search. Mixed-dimension embeddings from engine switches are silently excluded.
- **File upload over Apple Photos**: The web UI uses direct file upload (drag & drop) instead of Apple Photos integration, avoiding the Full Disk Access permission requirement.
- **EDL-based pipeline**: The AI director outputs a structured Edit Decision List. The assembly layer executes it. You can preview and tweak the plan before committing to a render.
- **Background job architecture**: Indexing and video generation run in background threads with progress polling via `/api/jobs/{id}`.
- **Hybrid search with RRF**: Embedding similarity + metadata filters merged via Reciprocal Rank Fusion. Items appearing in both result sets get boosted scores.

## Known Limitations

- **Embedding dimension mismatch**: If you switch between Twelve Labs and CLIP (by adding/removing the API key), previously stored embeddings with the old dimension won't appear in search results. Re-upload or re-embed affected files.
- **In-memory job tracking**: Background jobs are stored in a Python dict — they're lost on server restart. No persistent job history.
- **Brute-force vector search**: All embeddings loaded into memory for cosine similarity. Works fine for thousands of items but won't scale to millions without a proper vector index (pgvector, FAISS, etc).
- **No auth**: Single-user local tool. No authentication or multi-tenancy.

## Next Steps

- **Supabase migration** — replace SQLite with Supabase (Postgres + pgvector) for persistent storage, vector search at scale, and file storage via Supabase Storage
- **Beat-synced editing** — music is overlaid but cuts aren't synced to beats (needs librosa)
- **More themes** — user-defined or AI-suggested themes
- **Subtitle/caption support** — text overlays on individual clips
- **Smart suggestions** — "based on your library, here are 5 videos you could make"
- **Twelve Labs Pegasus** — rich AI-generated video descriptions (currently using Claude Vision)
