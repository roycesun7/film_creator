"""Video assembly package.

Provides `get_builder()` which returns the best available build_video function:
- FFmpeg subprocess builder (professional quality) when FFmpeg is installed
- moviepy-based builder as fallback
"""

import logging

logger = logging.getLogger(__name__)


def get_build_video():
    """Return the best available build_video function."""
    try:
        from assemble.ffmpeg_builder import is_available, build_video as ffmpeg_build
        if is_available():
            logger.info("Using FFmpeg subprocess builder for professional output")
            return ffmpeg_build
    except ImportError:
        pass

    logger.info("Using moviepy builder (FFmpeg not available)")
    from assemble.builder import build_video
    return build_video
