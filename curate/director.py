"""AI director that builds edit decision lists using Claude."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict

import anthropic

import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a world-class video editor and storyteller. Given the available footage, \
create a cinematic edit decision list (EDL) for a video.

Story & Structure:
- Open with an establishing shot that sets the scene and mood.
- Build a clear narrative arc: setup → rising action → climax → resolution.
- End with a memorable closing shot that provides emotional closure.
- Consider chronological order for same-event clips, but feel free to \
break chronology when it serves the story.

Pacing & Rhythm:
- Vary shot durations for rhythm: mix quick cuts (1.5-2.5s) with lingering \
moments (4-6s) to create a visual pulse.
- Use shorter durations for b-roll and transitions, longer for emotional highlights.
- For photos, use 2-5 seconds. For video clips, trim to the single most \
compelling segment rather than using the full clip.
- Build energy through the middle, then slow down toward the close.

Visual Flow:
- Never place visually similar shots back-to-back.
- Alternate between wide/establishing shots and close-up/detail shots.
- Mix photos and videos when both are available for textural variety.
- Use b-roll shots to bridge between key moments.

Technical Requirements:
- Every shot MUST reference a uuid from the provided manifest — do not invent uuids.
- The total duration of all shots should approximate the requested target duration.
- Assign each shot a role: "opener", "highlight", "b-roll", "transition", or "closer".
- A video should have exactly 1 opener and 1 closer. Use highlights for key \
moments, b-roll for atmosphere, and transitions for visual bridges.
- Provide a brief reason for each shot choice explaining how it serves the story.

Respond with a single JSON object matching this schema (no markdown fences):
{
  "title": "string — creative, evocative title (not just descriptive)",
  "narrative_summary": "string — 1-2 sentence summary of the video's emotional arc",
  "music_mood": "string — e.g. upbeat, calm, nostalgic, dramatic, playful, bittersweet",
  "shots": [
    {
      "uuid": "string",
      "path": "string",
      "media_type": "photo | video",
      "start_time": 0.0,
      "end_time": 3.0,
      "role": "opener | highlight | b-roll | transition | closer",
      "reason": "string"
    }
  ]
}
"""


@dataclass
class Shot:
    uuid: str
    path: str
    media_type: str
    start_time: float
    end_time: float
    role: str
    reason: str


@dataclass
class EditDecisionList:
    shots: list[Shot] = field(default_factory=list)
    title: str = ""
    narrative_summary: str = ""
    estimated_duration: float = 0.0
    music_mood: str = ""


def create_edit_decision_list(
    candidates: list[dict],
    prompt: str,
    target_duration: float = 60.0,
) -> EditDecisionList:
    """Ask Claude to produce an EDL from *candidates* guided by *prompt*.

    Parameters
    ----------
    candidates:
        Media items (dicts from the search layer) available for inclusion.
    prompt:
        Creative brief from the user describing the desired video.
    target_duration:
        Desired total video length in seconds.

    Returns
    -------
    EditDecisionList
        Validated edit decision list ready for the assembly layer.
    """
    manifest = _build_manifest(candidates)
    user_message = (
        f"Available footage:\n{json.dumps(manifest, indent=2)}\n\n"
        f"Creative brief: {prompt}\n\n"
        f"Target duration: {target_duration} seconds."
    )

    max_attempts = 2
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=config.DIRECTOR_MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
        except anthropic.APIError as exc:
            logger.error(
                "Anthropic API error on attempt %d/%d: %s", attempt, max_attempts, exc
            )
            last_error = exc
            if attempt < max_attempts:
                continue
            raise RuntimeError(
                f"Failed to get response from Claude API after {max_attempts} attempts: {exc}"
            ) from exc

        raw_text = response.content[0].text

        try:
            edl = _parse_response(raw_text, candidates)
        except json.JSONDecodeError as exc:
            logger.warning(
                "JSON parse error on attempt %d/%d: %s\nRaw text: %s",
                attempt, max_attempts, exc, raw_text[:500],
            )
            last_error = exc
            if attempt < max_attempts:
                continue
            # Return an empty EDL rather than crashing
            logger.error(
                "Failed to parse Claude response as JSON after %d attempts. "
                "Returning empty EDL.", max_attempts,
            )
            return EditDecisionList(
                shots=[],
                title="Untitled",
                narrative_summary="",
                estimated_duration=0.0,
                music_mood="",
            )

        edl = _validate(edl, candidates, target_duration)
        return edl

    # Should not be reached, but just in case
    return EditDecisionList()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_manifest(candidates: list[dict]) -> list[dict]:
    """Distil candidate media into the compact manifest sent to Claude."""
    manifest = []
    for c in candidates:
        desc = c.get("description", "")
        # Extract just the summary from description dicts to keep manifest compact
        if isinstance(desc, dict):
            desc = desc.get("summary", "")

        entry: dict = {
            "uuid": c["uuid"],
            "media_type": c.get("media_type", "photo"),
            "description": desc,
            "date": c.get("date", ""),
            "persons": c.get("persons", []),
            "labels": c.get("labels", []),
            "quality_score": c.get("quality_score"),
            "path": c.get("path", ""),
        }
        # Include duration and dimensions for video clips to help with trimming
        if c.get("media_type") == "video":
            entry["duration"] = c.get("duration")
        if c.get("width") and c.get("height"):
            entry["aspect"] = f"{c['width']}x{c['height']}"

        manifest.append(entry)
    return manifest


def _parse_response(raw_text: str, candidates: list[dict]) -> EditDecisionList:
    """Parse Claude's JSON response into an EditDecisionList."""
    # Strip markdown fences if present despite instructions.
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[: text.rfind("```")]
    text = text.strip()

    data = json.loads(text)

    path_lookup = {c["uuid"]: c.get("path", "") for c in candidates}

    shots: list[Shot] = []
    for s in data.get("shots", []):
        shot = Shot(
            uuid=s["uuid"],
            path=s.get("path") or path_lookup.get(s["uuid"], ""),
            media_type=s.get("media_type", "photo"),
            start_time=float(s.get("start_time", 0.0)),
            end_time=float(s.get("end_time", 0.0)),
            role=s.get("role", "b-roll"),
            reason=s.get("reason", ""),
        )
        shots.append(shot)

    estimated = sum(sh.end_time - sh.start_time for sh in shots)

    return EditDecisionList(
        shots=shots,
        title=data.get("title", "Untitled"),
        narrative_summary=data.get("narrative_summary", ""),
        estimated_duration=estimated,
        music_mood=data.get("music_mood", ""),
    )


def _validate(
    edl: EditDecisionList,
    candidates: list[dict],
    target_duration: float,
) -> EditDecisionList:
    """Validate and clean up the EDL.

    - Remove shots whose uuid is not in the candidate set.
    - Remove duplicate UUIDs (keep first occurrence).
    - Warn if estimated duration diverges significantly from target.
    """
    valid_uuids = {c["uuid"] for c in candidates}

    seen: set[str] = set()
    clean_shots: list[Shot] = []
    for shot in edl.shots:
        if shot.uuid not in valid_uuids:
            logger.warning("Dropping shot with unknown UUID %s", shot.uuid)
            continue
        if shot.uuid in seen:
            logger.warning("Dropping duplicate shot UUID %s", shot.uuid)
            continue
        # Ensure non-negative, ordered times.
        shot.start_time = max(0.0, shot.start_time)
        shot.end_time = max(shot.start_time + 0.1, shot.end_time)
        seen.add(shot.uuid)
        clean_shots.append(shot)

    edl.shots = clean_shots
    edl.estimated_duration = sum(s.end_time - s.start_time for s in clean_shots)

    ratio = edl.estimated_duration / target_duration if target_duration > 0 else 1.0
    if ratio < 0.5 or ratio > 1.5:
        logger.warning(
            "EDL duration (%.1fs) diverges from target (%.1fs) by %.0f%%",
            edl.estimated_duration,
            target_duration,
            abs(ratio - 1.0) * 100,
        )

    return edl
