import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
PROJECT_ROOT = Path(__file__).parent
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Legacy SQLite path (kept for reference / migration scripts)
DB_PATH = PROJECT_ROOT / "media_index.db"

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://wuevigbacntyssfreggh.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Ind1ZXZpZ2JhY250eXNzZnJlZ2doIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzI4MzUzMzgsImV4cCI6MjA4ODQxMTMzOH0.FSFu0wSXhujodZ9XnHOgcWzt-nif6elrYPd6oX_jZXc")

CLIP_MODEL = "ViT-B-32"
CLIP_PRETRAINED = "openai"
CLIP_EMBEDDING_DIM = 512

# Twelve Labs (preferred embedding engine)
TWELVELABS_API_KEY = os.getenv("TWELVELABS_API_KEY")
TWELVELABS_MODEL = "marengo3.0"  # Embed API v2 (was "Marengo-retrieval-2.7")
TWELVELABS_EMBEDDING_DIM = 512  # Marengo 3.0 produces 512-d vectors (was 1024)
USE_TWELVELABS = bool(TWELVELABS_API_KEY)

# Effective embedding dim depends on which engine is active
EMBEDDING_DIM = TWELVELABS_EMBEDDING_DIM if USE_TWELVELABS else CLIP_EMBEDDING_DIM

# Jamendo (royalty-free music library)
JAMENDO_CLIENT_ID = os.getenv("JAMENDO_CLIENT_ID", "")

VISION_MODEL = "claude-sonnet-4-20250514"
DIRECTOR_MODEL = "claude-sonnet-4-20250514"

MAX_VIDEO_CLIP_DURATION = 8.0
DEFAULT_PHOTO_DURATION = 3.0
DEFAULT_TRANSITION_DURATION = 0.5
DEFAULT_OUTPUT_FPS = 30
DEFAULT_OUTPUT_RESOLUTION = (1920, 1080)
