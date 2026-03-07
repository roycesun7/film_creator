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
│         → Supabase (Postgres + pgvector)     │
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
- **Supabase (Postgres + pgvector)** — managed database for media index, embeddings, and vector search
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
│   └── store.py                  # Supabase client, pgvector search, segment embeddings
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
│   ├── demo_search.py            # Shows full search pipeline input/output
│   ├── validate_index.py         # Runtime validation of index pipeline
│   ├── validate_curation.py      # Runtime validation of curation layer (real CLIP + Supabase)
│   └── validate_assembly.py      # Runtime validation of assembly pipeline (real renders)
├── uploads/                      # Uploaded media files (gitignored)
├── output/                       # Generated videos (gitignored)
├── .thumbnails/                  # Cached thumbnails (gitignored)
├── tests/                        # 163 pytest tests (8 test files)
│   ├── conftest.py               # Shared fixtures (temp DB, media items)
│   ├── test_index.py             # Indexing pipeline tests (33 tests)
│   ├── test_assemble.py          # Assembly/render tests (40 tests)
│   ├── test_curate.py            # Search & director tests (25 tests)
│   ├── test_edge_cases.py        # Edge case coverage (30 tests)
│   ├── test_management.py        # Media management tests (16 tests)
│   ├── test_keyframes.py         # Keyframe embedding tests (7 tests)
│   ├── test_integration.py       # End-to-end pipeline tests (5 tests)
│   └── test_cli.py               # CLI command tests (6 tests)
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

1. File saved to `uploads/`, media record upserted into Supabase **immediately** (with metadata, no embedding yet)
2. Library grid updates instantly — no page reload needed
3. Background thread starts embedding computation:
   - Twelve Labs Marengo API call (~3-5s for images, ~10-30s for videos depending on length)
   - Falls back to local CLIP if Twelve Labs fails
4. Embedding written to the appropriate pgvector column (`embedding` for 1024-d Twelve Labs, `clip_embedding` for 512-d CLIP)
5. Dashboard "With Embeddings" counter updates automatically via 5s polling

### Search Flow

1. **Query embedding**: text query → Twelve Labs `embed_text()` → 1024-d vector (~200ms)
2. **Vector search**: pgvector RPC (`match_media` or `match_media_clip`) computes cosine distance server-side; falls back to in-memory similarity if RPC fails
3. **Metadata search**: text-match against descriptions, labels, persons via Postgres ilike
4. **RRF merge**: Reciprocal Rank Fusion combines both ranked lists — items in both get boosted
5. **Response**: ranked results with `relevance_score`, media metadata, no raw embeddings

### Example Search Pipeline

```
Input:  POST /api/search  {"query": "outdoor scenery", "limit": 5}

Step 1 — Embed query:
  "outdoor scenery" → Marengo → [-0.00021, -0.03174, -0.00311, ...] (1024 floats)

Step 2 — pgvector cosine search (server-side via RPC):
  SELECT * FROM match_media(query_embedding, match_limit)
  → pgvector <=> operator computes cosine distance

Step 3 — Results ranked by similarity:
  aee1cf7c...  similarity = 0.2996

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

### Storage Schema (Supabase / Postgres + pgvector)

```sql
-- Main media table
media (
  uuid TEXT PRIMARY KEY,
  path TEXT,                    -- local file path in uploads/
  media_type TEXT,              -- "photo" or "video"
  date TEXT,                    -- ISO 8601
  lat REAL, lon REAL,           -- GPS coordinates (optional)
  width INTEGER, height INTEGER,
  duration REAL,                -- seconds (videos only)
  embedding vector(1024),       -- Twelve Labs Marengo (pgvector)
  clip_embedding vector(512),   -- CLIP ViT-B-32 fallback (pgvector)
  description JSONB,            -- structured data from Claude Vision
  quality_score REAL,
  albums JSONB, labels JSONB, persons JSONB,  -- JSON arrays
  indexed_at TEXT
)

-- Per-segment embeddings for temporal video search
keyframe_embeddings (
  media_uuid TEXT,
  keyframe_index INTEGER,
  timestamp_sec REAL,           -- segment start time
  embedding vector(1024)        -- Twelve Labs Marengo (pgvector)
)

-- pgvector RPC functions for cosine similarity search
-- match_media(query_embedding, match_limit)       → search 1024-d embeddings
-- match_media_clip(query_embedding, match_limit)   → search 512-d embeddings
-- match_keyframes(query_embedding, match_limit)    → search keyframe embeddings
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
   SUPABASE_URL=https://xxx.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=eyJ...
   ```
4. **Python deps**: `pip install -r requirements.txt`
5. **Frontend deps**: `cd frontend && npm install`

## Testing

```bash
make test              # 163 tests, all passing
make test-fast         # skip slow embedding tests
make test-integration  # end-to-end pipeline tests
make lint              # compile-check all source files

# Runtime validation scripts (use real embeddings + Supabase, no mocks)
python scripts/validate_index.py      # index pipeline round-trip
python scripts/validate_curation.py   # search + CLI with real CLIP embeddings
python scripts/validate_assembly.py   # render real videos, verify outputs
```

## Key Design Decisions

- **Twelve Labs Marengo over CLIP**: CLIP (2021) is image-only, 512-d, no audio, no temporal understanding. Marengo produces 1024-d multimodal embeddings that jointly capture visual, audio, and temporal information. ~15% better video retrieval accuracy on benchmarks.
- **Graceful fallback**: If `TWELVELABS_API_KEY` is not set, the system automatically uses local CLIP. No code changes needed. If Twelve Labs fails mid-upload, that file falls back to CLIP silently.
- **Immediate insert, background embed**: Upload endpoint upserts the media record into Supabase immediately (so the UI updates instantly), then computes embeddings in a background thread. This avoids the UI feeling stuck while waiting for API calls.
- **Separate embedding columns**: Twelve Labs (1024-d) and CLIP (512-d) embeddings are stored in distinct pgvector columns (`embedding` and `clip_embedding`), avoiding dimension conflicts when switching engines. `get_all_embeddings()` reads the column matching the active engine.
- **File upload over Apple Photos**: The web UI uses direct file upload (drag & drop) instead of Apple Photos integration, avoiding the Full Disk Access permission requirement.
- **EDL-based pipeline**: The AI director outputs a structured Edit Decision List. The assembly layer executes it. You can preview and tweak the plan before committing to a render.
- **Background job architecture**: Indexing and video generation run in background threads with progress polling via `/api/jobs/{id}`.
- **Hybrid search with RRF**: Embedding similarity + metadata filters merged via Reciprocal Rank Fusion. Items appearing in both result sets get boosted scores.

## Known Limitations

- **In-memory job tracking**: Background jobs are stored in a Python dict — they're lost on server restart. No persistent job history.
- **No auth**: Single-user local tool. No authentication or multi-tenancy.
- **pgvector RPC fallback**: If the Supabase RPC functions (`match_media`, etc.) fail, search falls back to loading all embeddings into Python and computing cosine similarity in-memory.

## Next Steps

- **Mobile testing** — no automated mobile/responsive tests yet; responsive design is CSS-only via Tailwind breakpoints
- **Frontend unit tests** — no React component tests (no Jest/Vitest/Playwright); only backend pytest coverage
- **Beat-synced editing** — music is overlaid but cuts aren't synced to beats (needs librosa)
- **More themes** — user-defined or AI-suggested themes
- **Subtitle/caption support** — text overlays on individual clips
- **Smart suggestions** — "based on your library, here are 5 videos you could make"
- **Twelve Labs Pegasus** — rich AI-generated video descriptions (currently using Claude Vision)
