"""Music analysis for beat-synced video editing.

Uses librosa to detect beats, song structure, and energy progression
from a music track, producing a MusicAnalysis that the director uses
to align video cuts to musical beats and sections.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BeatInfo:
    """A single beat with timing and strength metadata."""

    time: float            # seconds
    strength: float        # 0-1 normalized onset strength
    is_downbeat: bool      # every Nth beat (N=beats_per_bar)
    metric_position: int   # 0=downbeat, 1-3=offbeats in 4/4


@dataclass
class MusicSection:
    """A labelled structural section of a song."""

    start: float           # seconds
    end: float             # seconds
    label: str             # "intro", "verse", "chorus", "bridge", "outro"
    avg_energy: float      # 0-1 normalized


@dataclass
class MusicAnalysis:
    """Complete analysis of a music track for video editing alignment."""

    duration: float                          # total track duration in seconds
    bpm: float                               # estimated BPM
    beat_grid: list[BeatInfo]                # all detected beats
    strong_beats: list[float]                # subset of beat times suitable for cut points
    sections: list[MusicSection]             # structural sections
    energy_curve: list[tuple[float, float]]  # [(time, energy_0_to_1), ...]
    buildups: list[tuple[float, float]]      # [(start, end), ...] sustained energy increase
    drops: list[tuple[float, float]]         # [(start, end), ...] sudden energy decrease


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_music(
    path: str,
    beats_per_bar: int = 4,
    n_sections: int = 8,
) -> MusicAnalysis:
    """Analyze a music track for beat-synced video editing.

    Parameters
    ----------
    path:
        Path to an audio file (mp3, wav, flac, etc.).
    beats_per_bar:
        Number of beats per bar / measure (4 for common time).
    n_sections:
        Target number of structural sections to detect.

    Returns
    -------
    MusicAnalysis
        Full analysis including beats, sections, and energy data.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    RuntimeError
        If the audio file cannot be loaded or analysed.
    """
    import librosa

    audio_path = Path(path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    logger.info("Loading audio: %s", path)
    try:
        y, sr = librosa.load(str(audio_path), sr=22050)
    except Exception as exc:
        raise RuntimeError(f"Failed to load audio file {path}: {exc}") from exc

    duration = float(librosa.get_duration(y=y, sr=sr))
    logger.info("Audio loaded: %.1fs at %d Hz", duration, sr)

    # ------------------------------------------------------------------
    # 1. Onset envelope and beat tracking
    # ------------------------------------------------------------------
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beat_frames = librosa.beat.beat_track(
        y=y, sr=sr, onset_envelope=onset_env,
    )
    # librosa may return tempo as an ndarray; extract scalar
    bpm = float(np.atleast_1d(tempo)[0])
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    logger.info("Detected BPM: %.1f  |  %d beats", bpm, len(beat_times))

    # ------------------------------------------------------------------
    # 2. Beat strength from onset envelope values at beat positions
    # ------------------------------------------------------------------
    onset_at_beats = onset_env[beat_frames] if len(beat_frames) > 0 else np.array([])
    if len(onset_at_beats) > 0:
        omin, omax = onset_at_beats.min(), onset_at_beats.max()
        if omax > omin:
            norm_strength = (onset_at_beats - omin) / (omax - omin)
        else:
            norm_strength = np.ones_like(onset_at_beats) * 0.5
    else:
        norm_strength = np.array([])

    median_strength = float(np.median(norm_strength)) if len(norm_strength) > 0 else 0.5

    # ------------------------------------------------------------------
    # 3. Build BeatInfo list with downbeat and metric position
    # ------------------------------------------------------------------
    beat_grid: list[BeatInfo] = []
    strong_beats: list[float] = []

    for i, (bt, st) in enumerate(zip(beat_times, norm_strength)):
        metric_pos = i % beats_per_bar
        is_downbeat = metric_pos == 0
        info = BeatInfo(
            time=round(float(bt), 4),
            strength=round(float(st), 4),
            is_downbeat=is_downbeat,
            metric_position=metric_pos,
        )
        beat_grid.append(info)

        # Strong beats = downbeats + any beat above median strength
        if is_downbeat or st >= median_strength:
            strong_beats.append(round(float(bt), 4))

    # ------------------------------------------------------------------
    # 4. RMS energy curve (smoothed, normalised to 0-1)
    # ------------------------------------------------------------------
    rms = librosa.feature.rms(y=y)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr)

    # Smooth with a moving average (~0.5s window)
    win_len = max(1, int(0.5 * sr / 512))  # 512 = default hop_length
    if win_len > 1 and len(rms) >= win_len:
        kernel = np.ones(win_len) / win_len
        rms_smooth = np.convolve(rms, kernel, mode="same")
    else:
        rms_smooth = rms.copy()

    rms_min, rms_max = rms_smooth.min(), rms_smooth.max()
    if rms_max > rms_min:
        rms_norm = (rms_smooth - rms_min) / (rms_max - rms_min)
    else:
        rms_norm = np.zeros_like(rms_smooth)

    energy_curve: list[tuple[float, float]] = [
        (round(float(t), 3), round(float(e), 4))
        for t, e in zip(rms_times, rms_norm)
    ]

    # ------------------------------------------------------------------
    # 5. Song structure via chroma + recurrence + agglomerative clustering
    # ------------------------------------------------------------------
    sections = _detect_song_structure(y, sr, n_sections, rms_norm, rms_times)

    # ------------------------------------------------------------------
    # 6. Detect buildups and drops from energy derivative
    # ------------------------------------------------------------------
    buildups, drops = _detect_energy_regions(rms_norm, rms_times)

    logger.info(
        "Analysis complete: %d sections, %d buildups, %d drops",
        len(sections), len(buildups), len(drops),
    )

    return MusicAnalysis(
        duration=round(duration, 3),
        bpm=round(bpm, 2),
        beat_grid=beat_grid,
        strong_beats=strong_beats,
        sections=sections,
        energy_curve=energy_curve,
        buildups=buildups,
        drops=drops,
    )


# ---------------------------------------------------------------------------
# Song structure detection
# ---------------------------------------------------------------------------

def _detect_song_structure(
    y: np.ndarray,
    sr: int,
    n_sections: int,
    rms_norm: np.ndarray,
    rms_times: np.ndarray,
) -> list[MusicSection]:
    """Detect song structure using chroma features and agglomerative clustering.

    Parameters
    ----------
    y:
        Audio time-series.
    sr:
        Sample rate.
    n_sections:
        Target number of structural sections.
    rms_norm:
        Normalised RMS energy array (used for per-section avg_energy).
    rms_times:
        Timestamps corresponding to rms_norm values.

    Returns
    -------
    list[MusicSection]
        Detected sections with labels and energy.
    """
    import librosa
    from sklearn.cluster import AgglomerativeClustering

    duration = float(librosa.get_duration(y=y, sr=sr))

    # Beat-synchronous chroma features
    _, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    if len(beat_frames) < 2:
        # Not enough beats — return a single section spanning the whole track
        return [MusicSection(start=0.0, end=round(duration, 3),
                             label="verse", avg_energy=0.5)]

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_sync = librosa.util.sync(chroma, beat_frames, aggregate=np.median)

    # Stack memory for temporal context (3-beat window)
    chroma_stack = librosa.feature.stack_memory(chroma_sync, n_steps=3, mode="edge")

    # Recurrence matrix from stacked chroma
    rec = librosa.segment.recurrence_matrix(
        chroma_stack, width=3, mode="affinity", sym=True,
    )

    # Clamp n_sections to number of available beat-synchronised frames
    effective_sections = min(n_sections, chroma_sync.shape[1])
    if effective_sections < 2:
        return [MusicSection(start=0.0, end=round(duration, 3),
                             label="verse", avg_energy=0.5)]

    # Agglomerative clustering on the recurrence / affinity matrix
    # Convert affinity to distance (1 - affinity, clipped)
    distance = np.clip(1.0 - rec, 0, None)
    clustering = AgglomerativeClustering(
        n_clusters=effective_sections,
        metric="precomputed",
        linkage="average",
    )
    labels = clustering.fit_predict(distance)

    # Map beat indices to times
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    # Build raw section boundaries from contiguous label runs
    raw_sections: list[dict] = []
    current_label = labels[0]
    section_start_idx = 0
    for i in range(1, len(labels)):
        if labels[i] != current_label:
            start_t = float(beat_times[section_start_idx]) if section_start_idx < len(beat_times) else 0.0
            end_t = float(beat_times[i]) if i < len(beat_times) else duration
            raw_sections.append({
                "start": start_t,
                "end": end_t,
                "cluster": int(current_label),
            })
            current_label = labels[i]
            section_start_idx = i
    # Final section
    start_t = float(beat_times[section_start_idx]) if section_start_idx < len(beat_times) else 0.0
    raw_sections.append({
        "start": start_t,
        "end": duration,
        "cluster": int(current_label),
    })

    # Compute average energy per section
    for sec in raw_sections:
        mask = (rms_times >= sec["start"]) & (rms_times < sec["end"])
        sec["avg_energy"] = float(np.mean(rms_norm[mask])) if mask.any() else 0.5

    # Label sections
    section_labels = _label_sections(raw_sections)

    result: list[MusicSection] = []
    for sec, lbl in zip(raw_sections, section_labels):
        result.append(MusicSection(
            start=round(sec["start"], 3),
            end=round(sec["end"], 3),
            label=lbl,
            avg_energy=round(sec["avg_energy"], 4),
        ))

    return result


def _label_sections(sections: list[dict]) -> list[str]:
    """Assign structural labels to sections based on cluster IDs and energy.

    Heuristic rules:
    - First section labelled "intro" if its energy is below overall median.
    - Last section labelled "outro" if its energy is below overall median.
    - Most common cluster gets "chorus" (typically highest energy).
    - Second most common gets "verse".
    - Remaining clusters get "bridge".
    - Sections with the same cluster ID share the same label.

    Parameters
    ----------
    sections:
        List of section dicts with "cluster" and "avg_energy" keys.

    Returns
    -------
    list[str]
        A label per section.
    """
    if not sections:
        return []

    median_energy = float(np.median([s["avg_energy"] for s in sections]))

    # Count clusters and their mean energies
    cluster_counts: dict[int, int] = {}
    cluster_energy: dict[int, list[float]] = {}
    for s in sections:
        c = s["cluster"]
        cluster_counts[c] = cluster_counts.get(c, 0) + 1
        cluster_energy.setdefault(c, []).append(s["avg_energy"])

    # Sort clusters by frequency (descending), break ties by energy
    sorted_clusters = sorted(
        cluster_counts.keys(),
        key=lambda c: (cluster_counts[c], np.mean(cluster_energy[c])),
        reverse=True,
    )

    # Assign base labels by cluster rank
    cluster_labels: dict[int, str] = {}
    base_labels = ["chorus", "verse", "bridge"]
    for i, c in enumerate(sorted_clusters):
        cluster_labels[c] = base_labels[min(i, len(base_labels) - 1)]

    # Build per-section labels
    labels = [cluster_labels[s["cluster"]] for s in sections]

    # Override first section to "intro" if low energy
    if len(labels) > 0 and sections[0]["avg_energy"] < median_energy:
        labels[0] = "intro"

    # Override last section to "outro" if low energy
    if len(labels) > 1 and sections[-1]["avg_energy"] < median_energy:
        labels[-1] = "outro"

    return labels


# ---------------------------------------------------------------------------
# Energy region detection (buildups & drops)
# ---------------------------------------------------------------------------

def _detect_energy_regions(
    rms_norm: np.ndarray,
    rms_times: np.ndarray,
    buildup_threshold: float = 0.05,
    drop_threshold: float = -0.15,
    min_buildup_duration: float = 2.0,
    min_drop_duration: float = 0.3,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Detect buildups and drops from energy derivative.

    A *buildup* is a sustained period where the smoothed energy derivative
    stays above ``buildup_threshold`` for at least ``min_buildup_duration``
    seconds.

    A *drop* is a region where the smoothed energy derivative falls below
    ``drop_threshold`` for at least ``min_drop_duration`` seconds.

    Parameters
    ----------
    rms_norm:
        Normalised RMS energy array.
    rms_times:
        Timestamps corresponding to rms_norm.
    buildup_threshold:
        Minimum positive derivative to count as rising energy.
    drop_threshold:
        Maximum negative derivative to count as falling energy.
    min_buildup_duration:
        Minimum duration in seconds for a buildup region.
    min_drop_duration:
        Minimum duration in seconds for a drop region.

    Returns
    -------
    tuple[list[tuple[float, float]], list[tuple[float, float]]]
        (buildups, drops) as lists of (start, end) tuples.
    """
    if len(rms_norm) < 3:
        return [], []

    # Energy derivative
    energy_diff = np.gradient(rms_norm)

    # Smooth the derivative (~1s window)
    dt = float(rms_times[1] - rms_times[0]) if len(rms_times) > 1 else 0.023
    smooth_win = max(1, int(1.0 / dt))
    if smooth_win > 1 and len(energy_diff) >= smooth_win:
        kernel = np.ones(smooth_win) / smooth_win
        energy_diff_smooth = np.convolve(energy_diff, kernel, mode="same")
    else:
        energy_diff_smooth = energy_diff

    buildups = _find_energy_regions(
        energy_diff_smooth, rms_times,
        threshold=buildup_threshold,
        min_duration=min_buildup_duration,
        above=True,
    )
    drops = _find_energy_regions(
        energy_diff_smooth, rms_times,
        threshold=drop_threshold,
        min_duration=min_drop_duration,
        above=False,
    )

    return buildups, drops


def _find_energy_regions(
    energy_diff_smooth: np.ndarray,
    times: np.ndarray,
    threshold: float,
    min_duration: float,
    above: bool = True,
) -> list[tuple[float, float]]:
    """Find contiguous time regions where energy derivative crosses a threshold.

    Parameters
    ----------
    energy_diff_smooth:
        Smoothed energy derivative array.
    times:
        Timestamps corresponding to the derivative values.
    threshold:
        The derivative threshold value.
    min_duration:
        Minimum duration in seconds for a region to be included.
    above:
        If True, find regions where derivative is *above* threshold (buildups).
        If False, find regions where derivative is *below* threshold (drops).

    Returns
    -------
    list[tuple[float, float]]
        List of (start_time, end_time) tuples.
    """
    if above:
        mask = energy_diff_smooth > threshold
    else:
        mask = energy_diff_smooth < threshold

    regions: list[tuple[float, float]] = []
    in_region = False
    start_idx = 0

    for i in range(len(mask)):
        if mask[i] and not in_region:
            in_region = True
            start_idx = i
        elif not mask[i] and in_region:
            in_region = False
            start_t = float(times[start_idx])
            end_t = float(times[i])
            if end_t - start_t >= min_duration:
                regions.append((round(start_t, 3), round(end_t, 3)))

    # Close final region if still active
    if in_region:
        start_t = float(times[start_idx])
        end_t = float(times[-1])
        if end_t - start_t >= min_duration:
            regions.append((round(start_t, 3), round(end_t, 3)))

    return regions


# ---------------------------------------------------------------------------
# Convenience: get_cut_points
# ---------------------------------------------------------------------------

def get_cut_points(
    analysis: MusicAnalysis,
    min_interval: float = 1.5,
    prefer_downbeats: bool = True,
) -> list[float]:
    """Get recommended cut point times from the music analysis.

    Filters the strong_beats to ensure a minimum interval between cuts.
    If *prefer_downbeats* is True, downbeats are prioritised: they are
    placed first, then remaining strong beats fill gaps that exceed
    ``min_interval``.

    Parameters
    ----------
    analysis:
        A MusicAnalysis produced by :func:`analyze_music`.
    min_interval:
        Minimum time in seconds between consecutive cut points.
    prefer_downbeats:
        If True, prioritise downbeats over regular strong beats.

    Returns
    -------
    list[float]
        Sorted list of cut-point times in seconds.
    """
    if not analysis.beat_grid:
        return []

    if prefer_downbeats:
        # Phase 1: select downbeats that respect min_interval
        downbeats = [b.time for b in analysis.beat_grid if b.is_downbeat]
        selected = _filter_by_interval(downbeats, min_interval)

        # Phase 2: fill remaining gaps with other strong beats
        other_strong = sorted(
            set(analysis.strong_beats) - set(downbeats)
        )
        candidates = sorted(selected + other_strong)
        selected = _filter_by_interval(candidates, min_interval)
    else:
        selected = _filter_by_interval(sorted(analysis.strong_beats), min_interval)

    return selected


def _filter_by_interval(times: list[float], min_interval: float) -> list[float]:
    """Keep only times that are at least *min_interval* apart.

    Parameters
    ----------
    times:
        Sorted list of candidate times.
    min_interval:
        Minimum gap in seconds.

    Returns
    -------
    list[float]
        Filtered sorted list.
    """
    if not times:
        return []

    result = [times[0]]
    for t in times[1:]:
        if t - result[-1] >= min_interval:
            result.append(t)
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _analysis_to_dict(analysis: MusicAnalysis) -> dict:
    """Convert a MusicAnalysis to a JSON-serialisable dict."""
    return {
        "duration": analysis.duration,
        "bpm": analysis.bpm,
        "beat_count": len(analysis.beat_grid),
        "strong_beat_count": len(analysis.strong_beats),
        "strong_beats": analysis.strong_beats,
        "sections": [asdict(s) for s in analysis.sections],
        "buildups": analysis.buildups,
        "drops": analysis.drops,
        "energy_curve_samples": len(analysis.energy_curve),
    }


def main() -> None:
    """CLI entry point: analyse a music file and print JSON summary."""
    if len(sys.argv) < 2:
        print(f"Usage: python -m curate.music_analysis <path_to_audio>", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    audio_path = sys.argv[1]
    try:
        analysis = analyze_music(audio_path)
    except (FileNotFoundError, RuntimeError) as exc:
        logger.error("%s", exc)
        sys.exit(1)

    summary = _analysis_to_dict(analysis)
    cut_points = get_cut_points(analysis)
    summary["cut_points"] = cut_points
    summary["cut_point_count"] = len(cut_points)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
