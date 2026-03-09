"""Two-stage AI director that builds edit decision lists using Claude.

Stage 1 — Story Architect: designs narrative structure (acts, emotional arc,
    clip assignment) from the enriched clip manifest and creative brief.
Stage 2 — Editor: produces a detailed, beat-aligned EDL that follows the
    story arc and defaults to hard cuts.

Falls back to single-stage behaviour when music_analysis is not provided or
when a stage fails.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict

import anthropic

import config

logger = logging.getLogger(__name__)

# Valid xfade transition names for FFmpeg, plus "cut" (hard cut, no xfade)
VALID_TRANSITIONS = {
    "cut",
    "fade", "fadeblack", "fadewhite", "dissolve",
    "slideleft", "slideright", "slideup", "slidedown",
    "smoothleft", "smoothright", "smoothup", "smoothdown",
    "circlecrop", "circleopen", "circleclose",
    "radial", "rectcrop", "distance", "pixelize",
    "wipeleft", "wiperight", "wipeup", "wipedown",
}


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

STORY_ARCHITECT_PROMPT = """\
You are a master video editor specializing in highlight reels, memory recaps, \
and nostalgic montage videos — the kind shared on social media that make people \
feel something. Think of the best Instagram/TikTok recap edits, travel montages, \
and "year in review" videos you've seen.

Your goal is to create a POLISHED, EMOTIONALLY RESONANT highlight video — not \
a rough assembly of clips. Every creative choice should serve the feeling.

Design Principles:
1. EMOTION FIRST — what should the audience feel? Nostalgia? Joy? Wonder?
2. RHYTHM — cuts should feel musical, even without music. Short-long-short patterns.
3. VISUAL FLOW — shots should flow naturally. Similar compositions connect; \
contrasting compositions create energy.
4. VARIETY — mix close-ups with wide shots, static with motion, people with places.

Structure the video in ACTS:

- **Hook** (5-10%): Open with your BEST shot. The one that makes people stop \
scrolling. A stunning landscape, a joyful moment, a dramatic angle.
- **Build** (30-40%): Tell the story. Mix activities, people, places. \
Moderate pacing — let moments breathe but keep it moving.
- **Peak** (25-30%): The highlight reel within the highlight reel. Best footage, \
fastest pacing, most energy. Group the most exciting/beautiful/emotional moments.
- **Close** (10-15%): Wind down with warmth. A sunset, a group photo, a quiet \
moment. Leave the viewer feeling something.

For shorter videos (<30s), use just Hook → Peak → Close.

Music & Pacing:
- If music is provided, align acts to music sections (verse=build, chorus=peak).
- Without music, aim for a natural rhythm: ~2-4 seconds per clip in build, \
1.5-3 seconds in peak sections.

Clip Selection:
- Study quality_score — reserve Q7+ clips for the hook and peak.
- Group clips by theme/date for coherent sequences (all golf shots together, \
all food shots together, all group photos together).
- Only suggest clips from the manifest — NEVER invent UUIDs.
- Suggest MORE clips than needed per act — the Editor will curate.

Transition Strategy — THIS IS CRITICAL:
- This is a highlight reel, NOT a documentary. Transitions are part of the style.
- CROSSFADE/DISSOLVE should be the DEFAULT between most clips (0.3-0.5s).
- Use FADE TO BLACK only for opening, closing, or major mood shifts between acts.
- Hard cuts ONLY during fast-paced peak sections where rapid cutting adds energy.
- The overall feel should be smooth and flowing, like memories blending together.

Temporal Awareness:
- Use clip "date" fields to understand chronology.
- If the brief references a time period, only include clips from that range.
- Chronological order often works well for memory recaps.

Respond with a single JSON object (no markdown fences):
{
  "title": "string — creative, evocative title",
  "narrative_summary": "string — 2-3 sentence description of the emotional arc",
  "music_mood": "string — specific genre/vibe (e.g. 'upbeat indie pop', 'warm acoustic nostalgia', 'chill lofi vibes')",
  "overall_energy_arc": "string — energy progression",
  "transition_philosophy": "string — transition strategy",
  "acts": [
    {
      "name": "string — act name",
      "description": "string — emotional purpose",
      "mood": "string — emotional quality",
      "energy": "low | medium | high",
      "pacing": "slow | moderate | fast",
      "target_duration": 8.0,
      "music_section": "string — which music section, or 'any'",
      "suggested_clip_uuids": ["uuid1", "uuid2", "uuid3"],
      "transition_in": "fade | fadeblack | dissolve",
      "transition_out": "fade | fadeblack | dissolve"
    }
  ]
}
"""

EDITOR_PROMPT = """\
You are a world-class video editor creating a polished highlight reel / memory \
montage. Execute the story arc designed by the narrative director. Select \
specific clips, set precise timings, and produce an edit decision list (EDL) \
that feels like a professional Instagram/social media recap video.

You have been given:
1. A STORY ARC with acts, mood, pacing, and suggested clips.
2. The full CLIP MANIFEST with detailed metadata for every available clip.
3. Optionally, MUSIC ANALYSIS with beat positions and section timestamps.

Editing Principles:

TRANSITIONS — THE MOST IMPORTANT PART:
- This is a highlight montage, NOT a news broadcast. Smooth transitions are essential.
- DEFAULT transition is "dissolve" (crossfade) with 0.3-0.5s duration. \
Use dissolve/fade for MOST edit points — this creates the smooth, dreamy, \
nostalgic feel that defines great highlight reels.
- Use "fadeblack" for the very FIRST shot (fade in from black) and very LAST shot \
(fade out to black). Also use at major act boundaries for dramatic effect.
- Use "cut" (hard cut) ONLY during high-energy peak sections where rapid cutting \
adds excitement — typically 3-5 fast cuts in a row, then return to dissolves.
- Transition duration: 0.3s for fast-paced sections, 0.5s for slower emotional moments.
- When transition is "cut", set transition_duration to 0.

BEAT ALIGNMENT (when beat grid / cut points are provided):
- Align clip boundaries to the nearest beat where possible.
- On strong beats / downbeats, start new clips.
- Don't force every cut to a beat — some moments need to breathe.
- High-energy sections: cut more frequently (every 1-2 beats).
- Low-energy sections: hold shots longer (2-4 bars).

SHOT SELECTION & ORDERING:
- Follow the story arc's act structure and clip suggestions.
- Visual variety is critical:
  * NEVER place two clips of the same subject or scene back-to-back.
  * Alternate wide/close, static/moving, people/places.
  * Mix photos and videos when both are available.
- For the PEAK act: use highest quality_score clips, most dramatic moments, \
fastest pacing.
- Use each clip only once.

TIMING:
- For videos: set start_time and end_time to capture the BEST 2-4 second segment. \
Study the description to find the highlight moment. Don't use full clips.
- For photos: 2-4 seconds. Shorter in fast sections, longer in slow.
- Vary durations: mix quick cuts (1.5-2.5s) with held moments (3-5s).
- Total duration should approximate the target.

EFFECTS:
- Set ken_burns=true on ALL photos for subtle motion (this is essential — \
static photos feel dead in a montage).
- Set speed to 0.5-0.8 for dramatic slow-motion on the best action moments.
- Default speed is 1.0.

ROLES — use these correctly:
- "opener": ONLY the first 1-2 shots. Best/most striking visual.
- "highlight": emotional core moments — the best footage. Should be ~40-50% of shots.
- "b-roll": atmosphere, scenery, establishing shots. Fills in the story.
- "transition": SHORT (1-2s MAX) visual bridges. A sky shot, a texture, a motion blur. \
NEVER use a full-length clip as a "transition". If a clip is more than 2s, it's b-roll.
- "closer": ONLY the final 1-2 shots. Warm, conclusive.

Respond with a single JSON object (no markdown fences):
{
  "title": "string — from the story arc",
  "narrative_summary": "string — from the story arc",
  "music_mood": "string — from the story arc",
  "shots": [
    {
      "uuid": "string",
      "path": "string",
      "media_type": "photo | video",
      "start_time": 0.0,
      "end_time": 3.0,
      "role": "opener | highlight | b-roll | transition | closer",
      "reason": "string — why this shot here serves the story",
      "transition": "dissolve",
      "transition_duration": 0.4,
      "ken_burns": false,
      "speed": 1.0
    }
  ]
}
"""

# Legacy single-stage prompt (fallback)
SINGLE_STAGE_PROMPT = """\
You are a world-class video editor creating a polished highlight reel / memory \
montage video. Given available footage and a creative brief, produce an edit \
decision list (EDL) that feels like a professional social media recap — smooth, \
emotional, and visually polished.

Adapt your style to the brief:
- Highlight reel: smooth crossfades, nostalgic feel, best moments curated.
- Travel/vacation: chronological flow, mix wide & close-up, warm dissolves.
- Family/personal: emotional arc, linger on faces, gentle transitions.
- Action/sports: mix fast cuts in peaks with smooth dissolves in between.

Temporal Awareness:
- Use clip "date" fields to understand chronology.
- If the brief references a time period (e.g. "summer 2024"), only include \
clips from that range.
- Chronological order often works well for memory recaps.

Pacing:
- Mix shorter cuts (1.5-3s) with held moments (3-5s).
- Photos: 2-4 seconds. Videos: trim to the strongest 2-4 second segment.
- Build to a peak then wind down — don't keep constant pacing.

Visual Flow:
- NEVER place visually similar shots back-to-back.
- Alternate wide/close, static/moving, people/places.
- Use higher quality_score clips for the opening and peak sections.

Transitions — CRITICAL for highlight reels:
- DEFAULT transition is "dissolve" (crossfade, 0.3-0.5s). Use it for MOST cuts.
- "fadeblack" for the very first shot (fade in) and very last shot (fade out).
- "cut" (hard cut) ONLY during fast-paced peak sections for energy.
- When transition is "cut", set transition_duration to 0.

Effects:
- Set ken_burns=true on ALL photos (static photos feel dead in montages).
- Set speed to 0.5-0.8 for dramatic slow-motion on key action moments.
- Default speed is 1.0.

Roles:
- "opener": first 1-2 shots only. Most visually striking.
- "highlight": emotional core. ~40-50% of all shots.
- "b-roll": atmosphere, scenery. Fills in the story.
- "transition": SHORT visual bridges (1-2s MAX). Never a full-length clip.
- "closer": final 1-2 shots only. Warm, conclusive.

Respond with a single JSON object (no markdown fences):
{
  "title": "string — creative, evocative title",
  "narrative_summary": "string — 1-2 sentence summary of the video's arc",
  "music_mood": "string — specific genre/vibe for soundtrack",
  "shots": [
    {
      "uuid": "string",
      "path": "string",
      "media_type": "photo | video",
      "start_time": 0.0,
      "end_time": 3.0,
      "role": "opener | highlight | b-roll | transition | closer",
      "reason": "string",
      "transition": "dissolve",
      "transition_duration": 0.4,
      "ken_burns": false,
      "speed": 1.0
    }
  ]
}
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Shot:
    uuid: str
    path: str
    media_type: str
    start_time: float
    end_time: float
    role: str
    reason: str
    transition: str = "cut"
    transition_duration: float = 0.0
    ken_burns: bool = False
    speed: float = 1.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)


@dataclass
class EditDecisionList:
    shots: list[Shot] = field(default_factory=list)
    title: str = ""
    narrative_summary: str = ""
    estimated_duration: float = 0.0
    music_mood: str = ""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def create_edit_decision_list(
    candidates: list[dict],
    prompt: str,
    target_duration: float = 60.0,
    music_analysis: dict | None = None,
) -> EditDecisionList:
    """Ask Claude to produce an EDL from *candidates* guided by *prompt*.

    Uses a two-stage pipeline (Story Architect then Editor) when
    *music_analysis* is provided, falling back to a single-stage call
    otherwise or on failure.

    Parameters
    ----------
    candidates:
        Media items (dicts from the search layer) available for inclusion.
    prompt:
        Creative brief from the user describing the desired video.
    target_duration:
        Desired total video length in seconds.
    music_analysis:
        Optional dict from curate.music_analysis with keys: bpm, sections,
        strong_beats, cut_points, buildups, drops.  When provided, enables
        beat-aligned editing via the two-stage pipeline.

    Returns
    -------
    EditDecisionList
        Validated edit decision list ready for the assembly layer.
    """
    manifest = _build_manifest(candidates)

    # --- Two-stage pipeline ---------------------------------------------------
    # Attempt two-stage when we have enough data to justify it.
    # Falls back to single-stage on any failure.
    try:
        story_arc = _run_story_architect(manifest, prompt, target_duration, music_analysis)
    except Exception as exc:
        logger.warning(
            "Stage 1 (Story Architect) failed, falling back to single-stage: %s", exc,
        )
        story_arc = None

    if story_arc is not None:
        try:
            edl = _run_editor(
                story_arc, manifest, candidates, target_duration, music_analysis,
            )
            edl = _validate(edl, candidates, target_duration)
            return edl
        except Exception as exc:
            logger.warning(
                "Stage 2 (Editor) failed on first attempt: %s. Retrying...", exc,
            )
            # Retry once
            try:
                edl = _run_editor(
                    story_arc, manifest, candidates, target_duration, music_analysis,
                )
                edl = _validate(edl, candidates, target_duration)
                return edl
            except Exception as exc2:
                logger.warning(
                    "Stage 2 (Editor) failed on retry: %s. "
                    "Falling back to story arc clip suggestions.", exc2,
                )
                # Attempt to build an EDL from the story arc's clip suggestions
                edl = _story_arc_fallback(story_arc, candidates, target_duration)
                if edl.shots:
                    edl = _validate(edl, candidates, target_duration)
                    return edl
                logger.warning(
                    "Story arc fallback produced no shots. "
                    "Falling back to single-stage pipeline."
                )

    # --- Single-stage fallback ------------------------------------------------
    return _run_single_stage(manifest, candidates, prompt, target_duration)


# ---------------------------------------------------------------------------
# Stage 1: Story Architect
# ---------------------------------------------------------------------------

def _run_story_architect(
    manifest: list[dict],
    prompt: str,
    target_duration: float,
    music_analysis: dict | None,
) -> dict:
    """Run the Story Architect stage and return a story arc dict.

    Raises on API errors or JSON parse failures.
    """
    music_section = ""
    if music_analysis:
        music_section = _format_music_summary(music_analysis)

    user_parts = [
        f"Available footage ({len(manifest)} clips):\n{json.dumps(manifest, indent=2)}",
        f"\nCreative brief: {prompt}",
        f"\nTarget duration: {target_duration} seconds.",
    ]
    if music_section:
        user_parts.append(f"\nMusic analysis:\n{music_section}")

    user_message = "\n".join(user_parts)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.DIRECTOR_MODEL,
        max_tokens=4096,
        system=STORY_ARCHITECT_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = response.content[0].text
    logger.debug("Story Architect raw response:\n%s", raw_text[:2000])

    story_arc = _parse_json(raw_text)
    logger.info(
        "Story Architect produced %d acts: %s",
        len(story_arc.get("acts", [])),
        ", ".join(a.get("name", "?") for a in story_arc.get("acts", [])),
    )
    return story_arc


# ---------------------------------------------------------------------------
# Stage 2: Editor
# ---------------------------------------------------------------------------

def _run_editor(
    story_arc: dict,
    manifest: list[dict],
    candidates: list[dict],
    target_duration: float,
    music_analysis: dict | None,
) -> EditDecisionList:
    """Run the Editor stage and return a parsed EditDecisionList.

    Raises on API errors or JSON parse failures.
    """
    # Build the user message with all context
    user_parts = [
        "STORY ARC:\n" + json.dumps(story_arc, indent=2),
        f"\nCLIP MANIFEST ({len(manifest)} clips):\n{json.dumps(manifest, indent=2)}",
        f"\nTarget duration: {target_duration} seconds.",
    ]

    if music_analysis:
        # Provide beat grid as compact cut points
        cut_points = music_analysis.get("cut_points", [])
        if cut_points:
            user_parts.append(
                f"\nBEAT-ALIGNED CUT POINTS (recommended times for cuts, "
                f"{len(cut_points)} positions):\n{json.dumps(cut_points)}"
            )

        strong_beats = music_analysis.get("strong_beats", [])
        if strong_beats:
            user_parts.append(
                f"\nSTRONG BEATS ({len(strong_beats)} positions):\n"
                f"{json.dumps(strong_beats[:200])}"  # cap to avoid token overflow
            )

        sections = music_analysis.get("sections", [])
        if sections:
            user_parts.append(
                f"\nMUSIC SECTIONS:\n{json.dumps(sections, indent=2)}"
            )

        bpm = music_analysis.get("bpm")
        if bpm:
            user_parts.append(f"\nBPM: {bpm}")

        buildups = music_analysis.get("buildups", [])
        drops = music_analysis.get("drops", [])
        if buildups:
            user_parts.append(f"\nBUILDUPS (rising energy): {json.dumps(buildups)}")
        if drops:
            user_parts.append(f"\nDROPS (energy release): {json.dumps(drops)}")

    user_message = "\n".join(user_parts)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.DIRECTOR_MODEL,
        max_tokens=8192,
        system=EDITOR_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = response.content[0].text
    logger.debug("Editor raw response:\n%s", raw_text[:2000])

    edl = _parse_response(raw_text, candidates)
    logger.info(
        "Editor produced %d shots, estimated %.1fs",
        len(edl.shots), edl.estimated_duration,
    )
    return edl


# ---------------------------------------------------------------------------
# Single-stage fallback (legacy behaviour)
# ---------------------------------------------------------------------------

def _run_single_stage(
    manifest: list[dict],
    candidates: list[dict],
    prompt: str,
    target_duration: float,
) -> EditDecisionList:
    """Legacy single-stage director call."""
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
                system=SINGLE_STAGE_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
        except anthropic.APIError as exc:
            logger.error(
                "Anthropic API error on attempt %d/%d: %s", attempt, max_attempts, exc,
            )
            last_error = exc
            if attempt < max_attempts:
                continue
            raise RuntimeError(
                f"Failed to get response from Claude API after {max_attempts} attempts: {exc}"
            ) from exc

        raw_text = response.content[0].text
        logger.debug("Single-stage raw response:\n%s", raw_text[:2000])

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

    # Should not be reached
    return EditDecisionList()


# ---------------------------------------------------------------------------
# Story arc fallback — build EDL from Stage 1 clip suggestions
# ---------------------------------------------------------------------------

def _story_arc_fallback(
    story_arc: dict,
    candidates: list[dict],
    target_duration: float,
) -> EditDecisionList:
    """Build a basic EDL from the story arc's suggested clips when Stage 2 fails.

    Uses the act structure and suggested_clip_uuids to create a reasonable
    sequence with default timing.
    """
    candidate_lookup = {c["uuid"]: c for c in candidates}
    valid_uuids = set(candidate_lookup.keys())
    shots: list[Shot] = []
    seen: set[str] = set()

    acts = story_arc.get("acts", [])
    if not acts:
        return EditDecisionList()

    # Distribute target_duration across acts by their target_duration weights
    total_act_dur = sum(a.get("target_duration", 5.0) for a in acts)
    scale = target_duration / total_act_dur if total_act_dur > 0 else 1.0

    for act_idx, act in enumerate(acts):
        act_dur = act.get("target_duration", 5.0) * scale
        suggested = act.get("suggested_clip_uuids", [])
        # Filter to valid, unseen clips
        clip_uuids = [u for u in suggested if u in valid_uuids and u not in seen]
        if not clip_uuids:
            continue

        per_clip_dur = max(1.5, act_dur / len(clip_uuids))

        for clip_idx, uuid in enumerate(clip_uuids):
            cand = candidate_lookup[uuid]
            is_video = cand.get("media_type") == "video"
            src_dur = cand.get("duration", per_clip_dur)
            clip_dur = min(per_clip_dur, src_dur) if is_video else per_clip_dur

            # Determine transition
            if act_idx == 0 and clip_idx == 0:
                trans = "fadeblack"
                trans_dur = 0.5
                role = "opener"
            elif act_idx == len(acts) - 1 and clip_idx == len(clip_uuids) - 1:
                trans = "fadeblack"
                trans_dur = 0.5
                role = "closer"
            elif clip_idx == 0 and act_idx > 0:
                # Act boundary
                trans_in = act.get("transition_in", "dissolve")
                trans = trans_in if trans_in in VALID_TRANSITIONS else "dissolve"
                trans_dur = 0.4
                role = "highlight"
            else:
                trans = "dissolve"
                trans_dur = 0.4
                role = "b-roll"

            shot = Shot(
                uuid=uuid,
                path=cand.get("path", ""),
                media_type=cand.get("media_type", "photo"),
                start_time=0.0,
                end_time=clip_dur,
                role=role,
                reason=f"Auto-assigned from story arc act '{act.get('name', '?')}'",
                transition=trans,
                transition_duration=trans_dur,
                ken_burns=not is_video,
                speed=1.0,
            )
            shots.append(shot)
            seen.add(uuid)

    estimated = sum(s.end_time - s.start_time for s in shots)

    return EditDecisionList(
        shots=shots,
        title=story_arc.get("title", "Untitled"),
        narrative_summary=story_arc.get("narrative_summary", ""),
        estimated_duration=estimated,
        music_mood=story_arc.get("music_mood", ""),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_manifest(candidates: list[dict]) -> list[dict]:
    """Distil candidate media into the enriched manifest sent to Claude.

    Includes Twelve Labs video analysis fields when available for richer
    creative decisions.
    """
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

        # Include duration and dimensions for video clips
        if c.get("media_type") == "video":
            entry["duration"] = c.get("duration")
        if c.get("width") and c.get("height"):
            entry["aspect"] = f"{c['width']}x{c['height']}"

        # Enriched fields from Twelve Labs video analysis
        if c.get("energy_score") is not None:
            entry["energy_score"] = c["energy_score"]
        if c.get("energy_level"):
            entry["energy_level"] = c["energy_level"]
        if c.get("emotional_tone"):
            entry["emotional_tone"] = c["emotional_tone"]
        if c.get("shot_type"):
            entry["shot_type"] = c["shot_type"]
        if c.get("camera_movement"):
            entry["camera_movement"] = c["camera_movement"]
        if c.get("key_actions"):
            entry["key_actions"] = c["key_actions"]
        if c.get("mood"):
            entry["mood"] = c["mood"]
        if c.get("pacing"):
            entry["pacing"] = c["pacing"]
        if c.get("audio_description"):
            entry["audio_description"] = c["audio_description"]
        if c.get("highlight_moments"):
            entry["highlight_moments"] = c["highlight_moments"]

        manifest.append(entry)
    return manifest


def _format_music_summary(music_analysis: dict) -> str:
    """Format music analysis into a compact text summary for Stage 1."""
    parts = []

    bpm = music_analysis.get("bpm")
    if bpm:
        parts.append(f"BPM: {bpm}")

    sections = music_analysis.get("sections", [])
    if sections:
        section_lines = []
        for s in sections:
            label = s.get("label", "unknown")
            start = s.get("start", 0)
            end = s.get("end", 0)
            energy = s.get("avg_energy", 0.5)
            section_lines.append(
                f"  {label}: {start:.1f}s-{end:.1f}s (energy: {energy:.2f})"
            )
        parts.append("Sections:\n" + "\n".join(section_lines))

    buildups = music_analysis.get("buildups", [])
    if buildups:
        buildup_strs = [f"{s:.1f}s-{e:.1f}s" for s, e in buildups]
        parts.append(f"Buildups (rising energy): {', '.join(buildup_strs)}")

    drops = music_analysis.get("drops", [])
    if drops:
        drop_strs = [f"{s:.1f}s-{e:.1f}s" for s, e in drops]
        parts.append(f"Drops (energy release): {', '.join(drop_strs)}")

    # Summarise energy curve if available
    energy_curve = music_analysis.get("energy_curve", [])
    if energy_curve and len(energy_curve) > 10:
        # Sample a few points to describe the arc
        n = len(energy_curve)
        samples = [energy_curve[i] for i in range(0, n, max(1, n // 8))]
        curve_str = ", ".join(f"{t:.1f}s={e:.2f}" for t, e in samples)
        parts.append(f"Energy curve (sampled): {curve_str}")

    return "\n".join(parts) if parts else ""


def _parse_json(raw_text: str) -> dict:
    """Parse a JSON response from Claude, stripping markdown fences if present."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[: text.rfind("```")]
    text = text.strip()
    return json.loads(text)


def _parse_response(raw_text: str, candidates: list[dict]) -> EditDecisionList:
    """Parse Claude's JSON response into an EditDecisionList."""
    data = _parse_json(raw_text)

    path_lookup = {c["uuid"]: c.get("path", "") for c in candidates}

    shots: list[Shot] = []
    for s in data.get("shots", []):
        # Validate transition name
        trans = s.get("transition", "cut")
        if trans not in VALID_TRANSITIONS:
            trans = "cut"

        # Transition duration: 0 for cuts, clamped for others
        if trans == "cut":
            trans_dur = 0.0
        else:
            trans_dur = max(0.2, min(1.5, float(s.get("transition_duration", 0.4))))

        uuid = s.get("uuid")
        if not uuid:
            logger.warning("Shot missing uuid, skipping: %s", s)
            continue
        shot = Shot(
            uuid=uuid,
            path=s.get("path") or path_lookup.get(uuid, ""),
            media_type=s.get("media_type", "photo"),
            start_time=float(s.get("start_time", 0.0)),
            end_time=float(s.get("end_time", 0.0)),
            role=s.get("role", "b-roll"),
            reason=s.get("reason", ""),
            transition=trans,
            transition_duration=trans_dur,
            ken_burns=bool(s.get("ken_burns", s.get("media_type") == "photo")),
            speed=max(0.5, min(2.0, float(s.get("speed", 1.0)))),
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
    - Clamp video timings to source duration.
    - Enforce transition_duration = 0 for "cut" transitions.
    - Warn if estimated duration diverges significantly from target.
    """
    valid_uuids = {c["uuid"] for c in candidates}
    candidate_lookup = {c["uuid"]: c for c in candidates}

    seen: set[str] = set()
    clean_shots: list[Shot] = []
    for shot in edl.shots:
        if shot.uuid not in valid_uuids:
            logger.warning("Dropping shot with unknown UUID %s", shot.uuid)
            continue
        if shot.uuid in seen:
            logger.warning("Dropping duplicate shot UUID %s", shot.uuid)
            continue

        # Enforce cut transition has zero duration
        if shot.transition == "cut":
            shot.transition_duration = 0.0

        # Ensure non-negative, ordered times.
        shot.start_time = max(0.0, shot.start_time)
        shot.end_time = max(shot.start_time + 0.1, shot.end_time)

        # Cap video end_time to actual source duration
        cand = candidate_lookup.get(shot.uuid, {})
        src_duration = cand.get("duration")
        if shot.media_type == "video" and src_duration and src_duration > 0:
            intended_dur = shot.end_time - shot.start_time
            shot.end_time = min(shot.end_time, src_duration)
            shot.start_time = min(shot.start_time, shot.end_time - 0.1)
            # If clamping shrunk the clip too much, try to preserve intended
            # duration by shifting start_time backward
            actual_dur = shot.end_time - shot.start_time
            min_dur = min(1.5, src_duration)  # at least 1.5s or full clip
            desired_dur = max(min(intended_dur, src_duration), min_dur)
            if actual_dur < desired_dur:
                shot.start_time = max(0.0, shot.end_time - desired_dur)
                # If still too short (clip near start), extend end_time
                if shot.end_time - shot.start_time < min_dur:
                    shot.end_time = min(shot.start_time + min_dur, src_duration)

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
