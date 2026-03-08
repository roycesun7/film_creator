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
You are a master film storyteller and narrative designer. Your role is to \
design the high-level story structure for a highlight video, given available \
footage and a creative brief.

Think like Walter Murch — prioritise in this order:
1. EMOTION — what should the audience feel at each moment?
2. STORY — what journey are we taking them on?
3. RHYTHM — how does pacing serve the emotion and story?
4. EYE TRACE — where does the viewer's attention flow between shots?
5. 2D PLANE — how do compositions relate across cuts?
6. 3D SPACE — spatial continuity and geography.

Design the video in ACTS (sections), not individual shots. Each act has \
a purpose in the emotional arc:

- **Hook**: Open with the most visually striking or emotionally compelling \
moment. Drop the viewer into the story. 5-10% of total duration.
- **Context / Setup**: Establish the world, the people, the setting. \
Slower pacing, wider shots. 15-25% of total duration.
- **Rising Action / Build**: Energy increases, shot pace quickens, \
variety of content, intercut between themes. 30-40% of total duration.
- **Climax / Peak**: The best footage, highest energy, fastest cuts, \
most spectacular moments. 15-25% of total duration.
- **Resolution / Denouement**: Wind down gently. Return to calm. \
Reflective, emotional moments. 10-15% of total duration.

You may use fewer acts for short videos (<30s) or more for long ones (>90s). \
Adapt the structure to the content — not every video needs all five stages.

Music Awareness:
- If music analysis is provided, align your acts to the music sections.
- Map intro to hook, verse to context/build, chorus to climax, outro to resolution.
- Consider the energy curve: place high-energy footage where the music peaks.
- Note buildups (use them for rising action) and drops (use them for dramatic reveals).

Clip Selection:
- Study each clip's energy_score, emotional_tone, shot_type, and camera_movement.
- Reserve the BEST clips (highest quality_score, most visually compelling) for the climax.
- Suggest MORE clips than needed per act — the Editor will make final selections.
- Only suggest clips that actually exist in the manifest — NEVER invent UUIDs.
- Consider temporal coherence: clips from the same time period group naturally.

Transition Philosophy:
- Think about transitions at the ACT level, not per-shot.
- Acts should transition between each other with purpose (dissolve, fade to black).
- Within an act, cuts should be HARD CUTS by default.
- Specify the philosophy — the Editor will implement it.

Temporal Awareness:
- Each clip has a "date" field. Use it to understand when footage was captured.
- If the brief references a time period (e.g. "summer 2024", "last Christmas"), \
only include clips whose dates fall within that range.
- When chronological order suits the narrative, arrange clips by date.

Respond with a single JSON object (no markdown fences):
{
  "title": "string — creative, evocative title for the video",
  "narrative_summary": "string — 2-3 sentence description of the video's emotional arc",
  "music_mood": "string — specific genre/vibe for soundtrack (e.g. 'upbeat indie pop with driving rhythm')",
  "overall_energy_arc": "string — describe the energy progression (e.g. 'Hook high, dip for context, steady build to climax, gentle resolution')",
  "transition_philosophy": "string — describe the transition strategy (e.g. 'Hard cuts throughout. Dissolve only between acts. Fade-to-black for open/close.')",
  "acts": [
    {
      "name": "string — act name (e.g. 'The Hook', 'Golden Hour')",
      "description": "string — what this act accomplishes emotionally",
      "mood": "string — emotional quality (e.g. 'exciting', 'nostalgic', 'triumphant')",
      "energy": "low | medium | high",
      "pacing": "slow | moderate | fast",
      "target_duration": 8.0,
      "music_section": "string — which music section this aligns with, or 'any'",
      "suggested_clip_uuids": ["uuid1", "uuid2", "uuid3"],
      "transition_in": "cut | fade | fadeblack | dissolve",
      "transition_out": "cut | fade | fadeblack | dissolve"
    }
  ]
}
"""

EDITOR_PROMPT = """\
You are a world-class video editor executing a story arc designed by a \
narrative director. Your job is to select specific clips, set precise \
timings, and produce a frame-accurate edit decision list (EDL).

You have been given:
1. A STORY ARC with acts, mood, pacing, and suggested clips.
2. The full CLIP MANIFEST with detailed metadata for every available clip.
3. Optionally, MUSIC ANALYSIS with beat positions and section timestamps.

Editing Principles:

CUTS & TRANSITIONS:
- DEFAULT transition is "cut" (hard cut, zero transition duration). \
Use "cut" for the vast majority of edit points.
- Use "dissolve" or "fade" ONLY at act boundaries where the mood shifts.
- Use "fadeblack" ONLY for the very first shot (opening) and very last shot (closing), \
or for a major dramatic pause.
- LIMIT yourself to at most 2-3 different transition types in the entire video.
- When transition is "cut", set transition_duration to 0.
- When transition is not "cut", use transition_duration between 0.3 and 0.5 seconds.

BEAT ALIGNMENT (when beat grid / cut points are provided):
- Align clip boundaries to the nearest beat position where possible.
- On downbeats / strong beats, prefer to start a new clip.
- Don't force every cut to a beat — some moments need to breathe.
- During high-energy sections, cut on every other beat or every beat.
- During low-energy sections, hold shots longer (every 2-4 bars).

SHOT SELECTION & ORDERING:
- Follow the story arc's act structure and clip suggestions.
- Within each act, arrange shots for maximum visual variety:
  * NEVER place two clips with the same shot_type back-to-back (e.g. no two wide shots in a row).
  * NEVER place two clips with the same camera_movement back-to-back.
  * Alternate between static and moving shots for rhythm.
  * Mix photos and videos when both are available.
- For the CLIMAX act: use the highest quality_score clips, the most dramatic moments, \
and the fastest pacing.
- Prefer to use each clip only once — no duplicates.

TIMING:
- For videos: set start_time and end_time to capture the MOST INTERESTING segment. \
Study the description, key_actions, and highlight_moments to find the best part.
- For photos: typical duration is 2-4 seconds. Shorter in fast sections, longer in slow ones.
- Vary shot durations for rhythm: mix quick cuts (1.5-2.5s) with held moments (3-6s).
- Match pacing to the act's energy: fast pacing = shorter shots, slow = longer.
- The total duration of all shots should approximate the target duration.

EFFECTS:
- Set ken_burns=true on ALL photos for subtle motion (pan/zoom).
- Set speed to 0.5-0.8 for dramatic slow-motion on climax/reveal moments.
- Set speed to 1.2-1.5 for time-lapse or passing-of-time sequences.
- Default speed is 1.0 for normal playback.

ROLES:
- "opener": the first 1-2 shots, establishes the video.
- "highlight": key moments that are the emotional core.
- "b-roll": atmosphere, establishing, connecting shots.
- "transition": visual bridges between acts or themes.
- "closer": the final 1-2 shots, resolves the video.

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
      "reason": "string — why this shot at this position serves the story",
      "transition": "cut",
      "transition_duration": 0,
      "ken_burns": false,
      "speed": 1.0
    }
  ]
}
"""

# Legacy single-stage prompt (fallback)
SINGLE_STAGE_PROMPT = """\
You are a world-class video editor and storyteller. Given available footage and \
a creative brief, produce an edit decision list (EDL) that best serves the brief.

Adapt your editing style to the content and brief:
- Action/sports: fast cuts, energetic transitions, build to a climax.
- Travel/vacation: chronological flow, mix wide & close-up, warm pacing.
- Family/personal: emotional arc, linger on faces, gentle transitions.
- Professional/corporate: clean cuts, minimal effects, structured narrative.
- Music video/montage: cut to rhythm, varied transitions, visual energy.
Let the brief guide tone, pacing, and structure.

Temporal Awareness:
- Each clip has a "date" field. Use it to understand when footage was captured.
- If the brief references a time period (e.g. "summer 2024"), \
only include clips whose dates fall within that range.
- When chronological order suits the narrative, arrange clips by date.

Pacing:
- Vary shot durations: mix shorter cuts (1.5-3s) with longer moments (4-8s).
- For photos, 2-5s is typical. For videos, trim to the strongest segment.

Visual Flow:
- Avoid placing visually similar shots back-to-back.
- Alternate between wide/establishing and close-up/detail shots.
- Mix photos and videos for variety when both are available.
- Prefer higher quality_score items when choosing between similar options.

Transitions & Effects:
- DEFAULT transition is "cut" (hard cut, no transition effect).
- Use "cut" for the vast majority of edit points.
- "fade" / "dissolve" ONLY for section boundaries or mood shifts.
- "fadeblack" ONLY for opening/closing or major dramatic pauses.
- Limit to 2-3 transition types total.
- When transition is "cut", set transition_duration to 0.
- For other transitions: 0.3-0.5s duration.
- Set ken_burns=true on photos for subtle motion.
- Set speed to 0.5-0.8 for slow-mo on climax moments, 1.2+ for time-lapse feel.

Technical Requirements:
- Every shot MUST reference a uuid from the provided manifest.
- Only include clips relevant to the creative brief.
- Total duration should approximate the requested target.
- Assign each shot a role: "opener", "highlight", "b-roll", "transition", or "closer".
- Include at least one opener and one closer.
- Provide a brief reason for each shot choice.

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
      "transition": "cut",
      "transition_duration": 0,
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
                trans = "cut"
                trans_dur = 0.0
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
