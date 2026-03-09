import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchProject, updateProject, projectPreview, projectRender,
  fetchJob, thumbnailUrl, videoUrl, searchMedia, fetchMedia,
  uploadProjectMusic, deleteProjectMusic,
  searchMusicLibrary, selectLibraryMusic, suggestMusic,
  fetchMusicLibraryStatus, projectMusicUrl,
  type ProjectData, type TimelineClip, type TimelineTrack, type TextElement,
  type MediaItem, type MusicTrack
} from '../api'
import {
  Loader2, Play, Pause, Save, Sparkles, Clapperboard, Film, Music, Type,
  Plus, Trash2, X, ChevronLeft, Clock, SkipBack,
  Volume2, VolumeX, Lock, Unlock, Download,
  Settings, Layers, RotateCcw, Upload, Search, ImagePlus,
  FolderOpen, Library
} from 'lucide-react'
import { useToast } from '../components/Toast'

const PIXELS_PER_SECOND = 80
const TRACK_HEIGHT = 72
const MIN_CLIP_WIDTH = 32

const ROLE_COLORS: Record<string, string> = {
  opener: 'bg-amber-600/60 border-amber-500/40',
  highlight: 'bg-violet-600/60 border-violet-500/40',
  'b-roll': 'bg-zinc-600/60 border-zinc-500/40',
  transition: 'bg-blue-600/60 border-blue-500/40',
  closer: 'bg-emerald-600/60 border-emerald-500/40',
}

const TRACK_TYPE_ICONS: Record<string, typeof Film> = {
  video: Film,
  audio: Music,
  text: Type,
}

const THEME_OPTIONS = [
  { value: 'minimal', label: 'Minimal', color: '#000000' },
  { value: 'warm_nostalgic', label: 'Warm Nostalgic', color: '#1A0A00' },
  { value: 'bold_modern', label: 'Bold Modern', color: '#0D0D0D' },
  { value: 'cinematic', label: 'Cinematic', color: '#0A0A0A' },
  { value: 'documentary', label: 'Documentary', color: '#1A1A2E' },
  { value: 'social_vertical', label: 'Social (9:16)', color: '#000000' },
]

function TimelineClipComponent({
  clip,
  trackType: _trackType,
  pixelsPerSecond,
  onSelect,
  isSelected,
  onDragMove,
  onDragResize,
}: {
  clip: TimelineClip | TextElement
  trackType: string
  pixelsPerSecond: number
  onSelect: () => void
  isSelected: boolean
  onDragMove?: (newPosition: number) => void
  onDragResize?: (newDuration: number) => void
}) {
  const left = clip.position * pixelsPerSecond
  const width = Math.max(MIN_CLIP_WIDTH, clip.duration * pixelsPerSecond)
  const dragRef = useRef<{ startX: number; startPos: number; type: 'move' | 'resize'; startDur: number } | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [dragType, setDragType] = useState<'move' | 'resize' | null>(null)
  const elRef = useRef<HTMLDivElement>(null)

  const isTextElement = 'text' in clip && 'font_size' in clip
  const isMediaClip = 'media_uuid' in clip

  const roleClass = isMediaClip ? (ROLE_COLORS[(clip as TimelineClip).role] || 'bg-zinc-600/60 border-zinc-500/40') : 'bg-indigo-600/50 border-indigo-500/40'

  const handlePointerDown = useCallback((e: React.PointerEvent, type: 'move' | 'resize') => {
    e.stopPropagation()
    e.preventDefault()
    const el = elRef.current
    if (!el) return
    el.setPointerCapture(e.pointerId)
    dragRef.current = { startX: e.clientX, startPos: clip.position, type, startDur: clip.duration }
  }, [clip.position, clip.duration])

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current) return
    const dx = e.clientX - dragRef.current.startX
    // Only activate drag feedback after 3px threshold
    if (Math.abs(dx) > 3 && !isDragging) {
      setIsDragging(true)
      setDragType(dragRef.current.type)
    }
    if (dragRef.current.type === 'move' && onDragMove) {
      const rawPos = Math.max(0, dragRef.current.startPos + dx / pixelsPerSecond)
      // Snap to 0.25s grid
      const snapped = Math.round(rawPos * 4) / 4
      onDragMove(snapped)
    } else if (dragRef.current.type === 'resize' && onDragResize) {
      const rawDur = Math.max(0.5, dragRef.current.startDur + dx / pixelsPerSecond)
      const snapped = Math.round(rawDur * 4) / 4
      onDragResize(snapped)
    }
  }, [pixelsPerSecond, onDragMove, onDragResize, isDragging])

  const handlePointerUp = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current) return
    const el = elRef.current
    if (el) el.releasePointerCapture(e.pointerId)
    // If barely moved, treat as click/select
    if (Math.abs(e.clientX - dragRef.current.startX) < 3) {
      onSelect()
    }
    dragRef.current = null
    setIsDragging(false)
    setDragType(null)
  }, [onSelect])

  return (
    <div
      ref={elRef}
      onPointerDown={(e) => handlePointerDown(e, 'move')}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      className={`absolute top-1 bottom-1 rounded-md border overflow-hidden select-none ${roleClass} ${
        isSelected ? 'ring-2 ring-white/60 z-20' : 'hover:brightness-125'
      } ${isDragging ? 'opacity-80 shadow-lg shadow-black/40 z-30' : ''}`}
      style={{
        left: `${left}px`,
        width: `${width}px`,
        cursor: isDragging ? (dragType === 'resize' ? 'col-resize' : 'grabbing') : 'grab',
        touchAction: 'none',
        transition: isDragging ? 'none' : 'left 0.1s ease-out, width 0.1s ease-out',
      }}
      title={isTextElement ? (clip as TextElement).text : isMediaClip ? (clip as TimelineClip).reason : ''}
    >
      {/* Transition indicator on left edge */}
      {isMediaClip && (clip as TimelineClip).transition && (clip as TimelineClip).transition.type && (clip as TimelineClip).transition.type !== 'none' && (
        <div
          className="absolute left-0 top-0 bottom-0 w-1.5 bg-gradient-to-r from-violet-500/60 to-transparent z-10 pointer-events-auto"
          title={`${(clip as TimelineClip).transition.type} (${(clip as TimelineClip).transition.duration}s)`}
        />
      )}
      {/* Role badge */}
      {isMediaClip && (clip as TimelineClip).role && (
        <span className={`absolute top-0.5 right-1 text-[8px] font-bold uppercase opacity-60 pointer-events-none z-10 ${
          { opener: 'text-violet-300', highlight: 'text-amber-300', 'b-roll': 'text-zinc-400', closer: 'text-blue-300', transition: 'text-emerald-300' }[(clip as TimelineClip).role] || 'text-zinc-400'
        }`}>
          {(clip as TimelineClip).role}
        </span>
      )}
      {/* Drag position indicator */}
      {isDragging && (
        <div className="absolute -top-5 left-1/2 -translate-x-1/2 bg-black/90 text-[9px] text-white px-1.5 py-0.5 rounded whitespace-nowrap z-40 pointer-events-none">
          {dragType === 'move' ? `${clip.position.toFixed(1)}s` : `${clip.duration.toFixed(1)}s`}
        </div>
      )}
      <div className="flex items-center h-full px-1.5 gap-1.5 pointer-events-none">
        {isMediaClip && (clip as TimelineClip).media_uuid && (
          <div className="w-12 h-12 rounded shrink-0 overflow-hidden bg-black/30">
            <img
              src={thumbnailUrl((clip as TimelineClip).media_uuid)}
              alt=""
              className="w-full h-full object-cover"
              draggable={false}
              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
            />
          </div>
        )}
        {isTextElement && (
          <div className="w-8 h-8 rounded shrink-0 flex items-center justify-center bg-indigo-500/20">
            <Type className="w-4 h-4 text-indigo-300" />
          </div>
        )}
        <div className="flex-1 min-w-0 overflow-hidden">
          <p className="text-[10px] font-medium text-white/90 truncate leading-tight">
            {isTextElement
              ? (clip as TextElement).text || 'Text'
              : isMediaClip
              ? (clip as TimelineClip).role.charAt(0).toUpperCase() + (clip as TimelineClip).role.slice(1)
              : 'Clip'
            }
          </p>
          <p className="text-[9px] text-white/50 tabular-nums leading-tight">
            {clip.duration.toFixed(1)}s
          </p>
        </div>
      </div>
      {/* Resize handle on right edge */}
      <div
        onPointerDown={(e) => { e.stopPropagation(); handlePointerDown(e, 'resize') }}
        className="absolute right-0 top-0 bottom-0 w-2.5 cursor-col-resize hover:bg-white/20 pointer-events-auto flex items-center justify-center"
      >
        <div className="w-0.5 h-5 rounded-full bg-white/0 hover:bg-white/30 transition-colors" />
      </div>
    </div>
  )
}

function TrackHeader({
  track,
  onToggleMute,
  onToggleLock,
}: {
  track: TimelineTrack
  onToggleMute: () => void
  onToggleLock: () => void
}) {
  const TrackIcon = TRACK_TYPE_ICONS[track.type] || Film
  return (
    <div className="w-40 shrink-0 bg-zinc-900/80 border-r border-zinc-800 p-2 flex flex-col justify-center border-b border-b-zinc-800/80" style={{ height: `${TRACK_HEIGHT}px` }}>
      <div className="flex items-center gap-1.5 mb-1">
        <TrackIcon className="w-3.5 h-3.5 text-zinc-500" />
        <span className="text-[11px] font-medium text-zinc-300 truncate">{track.name}</span>
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={onToggleMute}
          className={`p-0.5 rounded transition-colors ${track.muted ? 'text-red-400' : 'text-zinc-600 hover:text-zinc-400'}`}
          title={track.muted ? 'Unmute' : 'Mute'}
        >
          {track.muted ? <VolumeX className="w-3 h-3" /> : <Volume2 className="w-3 h-3" />}
        </button>
        <button
          onClick={onToggleLock}
          className={`p-0.5 rounded transition-colors ${track.locked ? 'text-amber-400' : 'text-zinc-600 hover:text-zinc-400'}`}
          title={track.locked ? 'Unlock' : 'Lock'}
        >
          {track.locked ? <Lock className="w-3 h-3" /> : <Unlock className="w-3 h-3" />}
        </button>
      </div>
    </div>
  )
}

function TrackClips({
  track,
  pixelsPerSecond,
  timelineWidth,
  selectedClipId,
  onSelectClip,
  onMoveClip,
  onResizeClip,
}: {
  track: TimelineTrack
  pixelsPerSecond: number
  timelineWidth: number
  selectedClipId: string | null
  onSelectClip: (id: string) => void
  onMoveClip: (id: string, newPosition: number) => void
  onResizeClip: (id: string, newDuration: number) => void
}) {
  const allItems = track.type === 'text'
    ? track.text_elements.map(te => ({ ...te, _isText: true as const }))
    : track.clips.map(c => ({ ...c, _isText: false as const }))

  return (
    <div
      className="relative bg-zinc-900/40 border-b border-zinc-800/80"
      style={{ width: `${timelineWidth}px`, height: `${TRACK_HEIGHT}px` }}
    >
      {allItems.map((item) => (
        <TimelineClipComponent
          key={item.id}
          clip={item as any}
          trackType={track.type}
          pixelsPerSecond={pixelsPerSecond}
          onSelect={() => onSelectClip(item.id)}
          isSelected={selectedClipId === item.id}
          onDragMove={track.locked ? undefined : (pos) => onMoveClip(item.id, pos)}
          onDragResize={track.locked ? undefined : (dur) => onResizeClip(item.id, dur)}
        />
      ))}
    </div>
  )
}

function ClipInspector({
  clip,
  onUpdate,
  onRemove,
  onClose,
}: {
  clip: TimelineClip
  onUpdate: (updates: Partial<TimelineClip>) => void
  onRemove: () => void
  onClose: () => void
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-200">Clip Properties</h3>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">
          <X className="w-4 h-4" />
        </button>
      </div>

      {clip.media_uuid && (
        <div className="mb-4 aspect-video bg-black rounded-lg overflow-hidden relative group">
          {clip.media_type === 'video' ? (
            <video
              src={videoUrl(clip.media_uuid)}
              poster={thumbnailUrl(clip.media_uuid)}
              controls
              preload="metadata"
              className="w-full h-full object-cover"
            />
          ) : (
            <img
              src={thumbnailUrl(clip.media_uuid)}
              alt=""
              className="w-full h-full object-cover"
            />
          )}
        </div>
      )}

      <div className="space-y-3 text-xs">
        <div>
          <label className="block text-zinc-500 mb-1">Role</label>
          <select
            value={clip.role}
            onChange={(e) => onUpdate({ role: e.target.value })}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
          >
            <option value="opener">Opener</option>
            <option value="highlight">Highlight</option>
            <option value="b-roll">B-Roll</option>
            <option value="transition">Transition</option>
            <option value="closer">Closer</option>
          </select>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-zinc-500 mb-1">Duration (s)</label>
            <input
              type="number"
              value={clip.duration}
              onChange={(e) => {
                const val = parseFloat(e.target.value)
                if (val > 0 && val <= 60) onUpdate({ duration: val })
              }}
              min={0.5}
              max={60}
              step={0.5}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>
          <div>
            <label className="block text-zinc-500 mb-1">Position (s)</label>
            <input
              type="number"
              value={clip.position}
              onChange={(e) => onUpdate({ position: Math.max(0, parseFloat(e.target.value) || 0) })}
              min={0}
              step={0.5}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>
        </div>

        {clip.media_type === 'video' && (
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-zinc-500 mb-1">In Point (s)</label>
              <input
                type="number"
                value={clip.in_point}
                onChange={(e) => onUpdate({ in_point: Math.max(0, parseFloat(e.target.value) || 0) })}
                min={0}
                step={0.1}
                className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
            </div>
            <div>
              <label className="block text-zinc-500 mb-1">Out Point (s)</label>
              <input
                type="number"
                value={clip.out_point}
                onChange={(e) => onUpdate({ out_point: parseFloat(e.target.value) || 0 })}
                min={0}
                step={0.1}
                className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
            </div>
          </div>
        )}

        <div>
          <label className="block text-zinc-500 mb-1">Transition</label>
          <div className="flex gap-2">
            <select
              value={clip.transition.type}
              onChange={(e) => onUpdate({ transition: { ...clip.transition, type: e.target.value } })}
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
            >
              <option value="crossfade">Crossfade</option>
              <option value="fade_black">Fade Black</option>
              <option value="slide_left">Slide</option>
              <option value="none">None</option>
            </select>
            <input
              type="number"
              value={clip.transition.duration}
              onChange={(e) => onUpdate({ transition: { ...clip.transition, duration: parseFloat(e.target.value) || 0.5 } })}
              min={0}
              max={3}
              step={0.1}
              className="w-16 bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>
        </div>

        {clip.reason && (
          <div>
            <label className="block text-zinc-500 mb-1">AI Reasoning</label>
            <p className="text-[11px] text-zinc-400 bg-zinc-800/50 rounded px-2 py-1.5">{clip.reason}</p>
          </div>
        )}

        <div className="pt-2 border-t border-zinc-800">
          <button
            onClick={onRemove}
            className="flex items-center gap-1.5 text-xs text-red-400 hover:text-red-300 transition-colors"
          >
            <Trash2 className="w-3 h-3" /> Remove Clip
          </button>
        </div>
      </div>
    </div>
  )
}


function TextElementInspector({
  element,
  onUpdate,
  onRemove,
  onClose,
}: {
  element: TextElement
  onUpdate: (updates: Partial<TextElement>) => void
  onRemove: () => void
  onClose: () => void
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-zinc-200">Text Properties</h3>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="space-y-3 text-xs">
        <div>
          <label className="block text-zinc-500 mb-1">Text</label>
          <textarea
            value={element.text}
            onChange={(e) => onUpdate({ text: e.target.value })}
            rows={2}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none"
            placeholder="Enter text..."
          />
        </div>

        <div>
          <label className="block text-zinc-500 mb-1">Style</label>
          <select
            value={element.style}
            onChange={(e) => onUpdate({ style: e.target.value })}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
          >
            <option value="title">Title</option>
            <option value="subtitle">Subtitle</option>
            <option value="caption">Caption</option>
            <option value="lower_third">Lower Third</option>
          </select>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-zinc-500 mb-1">Position (s)</label>
            <input
              type="number"
              value={element.position}
              onChange={(e) => onUpdate({ position: Math.max(0, parseFloat(e.target.value) || 0) })}
              min={0}
              step={0.5}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>
          <div>
            <label className="block text-zinc-500 mb-1">Duration (s)</label>
            <input
              type="number"
              value={element.duration}
              onChange={(e) => {
                const val = parseFloat(e.target.value)
                if (val > 0 && val <= 60) onUpdate({ duration: val })
              }}
              min={0.5}
              max={60}
              step={0.5}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>
        </div>

        <div>
          <label className="block text-zinc-500 mb-1">Animation</label>
          <select
            value={element.animation}
            onChange={(e) => onUpdate({ animation: e.target.value })}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
          >
            <option value="fade">Fade In/Out</option>
            <option value="slide_up">Slide Up</option>
            <option value="typewriter">Typewriter</option>
            <option value="none">None</option>
          </select>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-zinc-500 mb-1">Font Size</label>
            <input
              type="number"
              value={element.font_size}
              onChange={(e) => onUpdate({ font_size: Math.max(8, parseInt(e.target.value) || 48) })}
              min={8}
              max={200}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>
          <div>
            <label className="block text-zinc-500 mb-1">Color</label>
            <input
              type="color"
              value={element.color}
              onChange={(e) => onUpdate({ color: e.target.value })}
              className="w-full h-7 bg-zinc-800 border border-zinc-700 rounded cursor-pointer"
            />
          </div>
        </div>

        <div>
          <label className="block text-zinc-500 mb-1">Vertical Position</label>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={element.y}
            onChange={(e) => onUpdate({ y: parseFloat(e.target.value) })}
            className="w-full accent-violet-500"
          />
          <div className="flex justify-between text-[9px] text-zinc-600">
            <span>Top</span>
            <span>Center</span>
            <span>Bottom</span>
          </div>
        </div>

        <div className="pt-2 border-t border-zinc-800">
          <button
            onClick={onRemove}
            className="flex items-center gap-1.5 text-xs text-red-400 hover:text-red-300 transition-colors"
          >
            <Trash2 className="w-3 h-3" /> Remove Text
          </button>
        </div>
      </div>
    </div>
  )
}


function MediaBrowser({
  onAddClip,
  onClose,
}: {
  onAddClip: (item: MediaItem) => void
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [mediaType, setMediaType] = useState<string>('')

  // Browse mode: show recent media
  const browseQuery = useQuery({
    queryKey: ['media-browser', mediaType],
    queryFn: () => fetchMedia({ limit: 50, sort: 'recent', media_type: mediaType || undefined }),
  })

  // Search mode
  const searchMut = useMutation({
    mutationFn: (q: string) => searchMedia({ query: q, limit: 30 }),
  })

  const handleSearch = () => {
    if (query.trim()) searchMut.mutate(query.trim())
  }

  const items: MediaItem[] = query && searchMut.data
    ? searchMut.data.results
    : browseQuery.data?.items || []

  const isLoading = browseQuery.isLoading || searchMut.isPending

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-zinc-800">
        <h3 className="text-xs font-semibold text-zinc-300 flex items-center gap-1.5">
          <FolderOpen className="w-3.5 h-3.5" /> Media Browser
        </h3>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Search bar */}
      <div className="px-3 py-2 border-b border-zinc-800/60 space-y-2">
        <div className="flex gap-1.5">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="Search media..."
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded-md px-2 py-1 text-xs text-zinc-200 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-violet-500"
          />
          <button
            onClick={handleSearch}
            disabled={!query.trim()}
            className="p-1.5 rounded-md bg-zinc-800 border border-zinc-700 text-zinc-400 hover:text-zinc-200 disabled:opacity-30 transition-colors"
          >
            <Search className="w-3 h-3" />
          </button>
        </div>
        <div className="flex gap-1">
          {['', 'photo', 'video'].map(t => (
            <button
              key={t}
              onClick={() => { setMediaType(t); if (query) searchMut.reset() }}
              className={`text-[10px] px-2 py-0.5 rounded-full transition-colors ${
                mediaType === t ? 'bg-violet-600/30 text-violet-300' : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {t || 'All'}
            </button>
          ))}
          {query && (
            <button
              onClick={() => { setQuery(''); searchMut.reset() }}
              className="text-[10px] px-2 py-0.5 text-zinc-500 hover:text-zinc-300 ml-auto"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto p-2">
        {isLoading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-4 h-4 animate-spin text-zinc-500" />
          </div>
        )}

        {!isLoading && items.length === 0 && (
          <div className="text-center py-8 text-zinc-600 text-xs">
            {query ? 'No results found' : 'No media in library'}
          </div>
        )}

        <div className="grid grid-cols-2 gap-1.5">
          {items.map(item => (
            <div
              key={item.uuid}
              className="group relative rounded-lg overflow-hidden border border-zinc-700/40 hover:border-violet-500/40 transition-colors bg-zinc-800"
            >
              <div className="aspect-square">
                <img
                  src={thumbnailUrl(item.uuid)}
                  alt=""
                  className="w-full h-full object-cover"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                />
              </div>
              <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center">
                <button
                  onClick={() => onAddClip(item)}
                  className="opacity-0 group-hover:opacity-100 transition-opacity bg-violet-600 hover:bg-violet-500 text-white text-[10px] font-medium px-2 py-1 rounded-md flex items-center gap-1"
                >
                  <Plus className="w-3 h-3" /> Add
                </button>
              </div>
              <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent px-1.5 pb-1 pt-3">
                <div className="flex items-center justify-between">
                  <span className="text-[8px] text-zinc-300 uppercase">{item.media_type}</span>
                  {item.duration && (
                    <span className="text-[8px] text-zinc-400 tabular-nums">
                      {item.duration > 60
                        ? `${Math.floor(item.duration / 60)}:${String(Math.floor(item.duration % 60)).padStart(2, '0')}`
                        : `${Math.floor(item.duration)}s`
                      }
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}


function TimelinePreview({
  tracks,
  playheadPos,
  onPlayheadChange,
  timelineDuration,
  isPlaying,
  setIsPlaying,
  projectId,
  hasMusicTrack,
  musicVolume,
}: {
  tracks: TimelineTrack[]
  playheadPos: number
  onPlayheadChange: (pos: number) => void
  timelineDuration: number
  isPlaying: boolean
  setIsPlaying: (v: boolean) => void
  projectId?: string
  hasMusicTrack?: boolean
  musicVolume?: number
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const rafRef = useRef(0)
  const lastFrameRef = useRef(0)
  const currentSrcRef = useRef('')
  const playheadRef = useRef(playheadPos)
  const durationRef = useRef(timelineDuration)

  playheadRef.current = playheadPos
  durationRef.current = timelineDuration

  const videoTrack = tracks.find(t => t.type === 'video')
  const sortedClips = useMemo(() => {
    const c = videoTrack?.clips || []
    return [...c].sort((a, b) => a.position - b.position)
  }, [videoTrack])

  const activeClip = useMemo(() =>
    sortedClips.find(c => playheadPos >= c.position && playheadPos < c.position + c.duration) || null,
    [sortedClips, playheadPos]
  )

  const activeTexts = useMemo(() =>
    tracks
      .filter(t => t.type === 'text' && !t.muted)
      .flatMap(t => t.text_elements)
      .filter(te => playheadPos >= te.position && playheadPos < te.position + te.duration),
    [tracks, playheadPos]
  )

  // Sync video source when active clip changes
  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    if (!activeClip || activeClip.media_type !== 'video') {
      if (currentSrcRef.current) {
        video.pause()
        video.removeAttribute('src')
        video.load()
        currentSrcRef.current = ''
      }
      return
    }

    const src = videoUrl(activeClip.media_uuid)
    const sourceTime = activeClip.in_point + (playheadPos - activeClip.position)

    if (currentSrcRef.current !== src) {
      currentSrcRef.current = src
      video.src = src
      video.currentTime = sourceTime
      if (isPlaying) video.play().catch(() => {})
    }
  }, [activeClip?.id])

  // Seek when scrubbing (not playing)
  useEffect(() => {
    if (isPlaying) return
    const video = videoRef.current
    if (!video || !activeClip || activeClip.media_type !== 'video') return
    const sourceTime = activeClip.in_point + (playheadPos - activeClip.position)
    if (Math.abs(video.currentTime - sourceTime) > 0.1) {
      video.currentTime = sourceTime
    }
  }, [playheadPos, isPlaying, activeClip])

  // Playback loop
  useEffect(() => {
    if (!isPlaying) {
      cancelAnimationFrame(rafRef.current)
      videoRef.current?.pause()
      audioRef.current?.pause()
      return
    }

    const video = videoRef.current
    if (video && currentSrcRef.current) {
      video.play().catch(() => {})
    }

    // Start music playback
    const audio = audioRef.current
    if (audio && audio.src) {
      audio.currentTime = playheadRef.current
      audio.play().catch(() => {})
    }

    lastFrameRef.current = performance.now()

    const tick = (now: number) => {
      const dt = (now - lastFrameRef.current) / 1000
      lastFrameRef.current = now

      const newPos = playheadRef.current + dt
      if (newPos >= durationRef.current) {
        setIsPlaying(false)
        onPlayheadChange(0)
        videoRef.current?.pause()
        audioRef.current?.pause()
        return
      }

      onPlayheadChange(newPos)
      rafRef.current = requestAnimationFrame(tick)
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [isPlaying, onPlayheadChange, setIsPlaying])

  // When play starts/stops, sync video and music
  useEffect(() => {
    const video = videoRef.current
    if (video && currentSrcRef.current) {
      if (isPlaying) {
        const clip = sortedClips.find(c => playheadRef.current >= c.position && playheadRef.current < c.position + c.duration)
        if (clip && clip.media_type === 'video') {
          video.currentTime = clip.in_point + (playheadRef.current - clip.position)
          video.play().catch(() => {})
        }
      } else {
        video.pause()
      }
    }

    const audio = audioRef.current
    if (audio && audio.src) {
      if (isPlaying) {
        audio.currentTime = playheadRef.current
        audio.play().catch(() => {})
      } else {
        audio.pause()
      }
    }
  }, [isPlaying])

  // Sync music volume
  useEffect(() => {
    const audio = audioRef.current
    if (audio) {
      audio.volume = musicVolume ?? 0.3
    }
  }, [musicVolume])

  // Seek music when scrubbing
  useEffect(() => {
    if (isPlaying) return
    const audio = audioRef.current
    if (audio && audio.src) {
      audio.currentTime = playheadPos
    }
  }, [playheadPos, isPlaying])

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60)
    const sec = Math.floor(s % 60)
    return `${m}:${String(sec).padStart(2, '0')}`
  }

  return (
    <div className="flex-1 flex flex-col bg-black min-h-0">
      <div className="relative flex-1 mx-auto w-full bg-black overflow-hidden" style={{ aspectRatio: '16/9' }}>
        {/* Video layer */}
        <video
          ref={videoRef}
          className={`absolute inset-0 w-full h-full object-contain ${
            activeClip?.media_type === 'video' ? '' : 'hidden'
          }`}
          playsInline
          preload="auto"
        />

        {/* Background music audio */}
        {projectId && hasMusicTrack && (
          <audio
            ref={audioRef}
            src={projectMusicUrl(projectId)}
            preload="auto"
          />
        )}

        {/* Photo layer */}
        {activeClip?.media_type === 'photo' && (
          <img
            src={thumbnailUrl(activeClip.media_uuid)}
            alt=""
            className="absolute inset-0 w-full h-full object-contain"
          />
        )}

        {/* Empty states */}
        {!activeClip && sortedClips.length > 0 && (
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-zinc-700 text-xs">No clip at playhead</span>
          </div>
        )}
        {sortedClips.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-zinc-700 text-sm">Add clips to preview</span>
          </div>
        )}

        {/* Text overlays */}
        {activeTexts.map(te => (
          <div
            key={te.id}
            className="absolute left-0 right-0 text-center pointer-events-none"
            style={{ top: `${te.y * 100}%`, transform: 'translateY(-50%)' }}
          >
            <span
              style={{
                fontSize: `${Math.max(te.font_size * 0.4, 12)}px`,
                color: te.color,
                backgroundColor: te.bg_color || 'transparent',
                padding: '2px 8px',
                fontFamily: te.font_family,
              }}
            >
              {te.text}
            </span>
          </div>
        ))}
      </div>

      {/* Transport controls */}
      <div className="flex items-center justify-center gap-3 px-4 py-1.5 bg-zinc-900/80">
        <button
          onClick={() => { onPlayheadChange(0); setIsPlaying(false) }}
          className="p-1 rounded-md hover:bg-zinc-700/60 text-zinc-500 hover:text-zinc-300 transition-colors"
          title="Go to start"
        >
          <SkipBack className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={() => {
            if (!isPlaying && playheadPos >= timelineDuration && timelineDuration > 0) {
              onPlayheadChange(0)
            }
            setIsPlaying(!isPlaying)
          }}
          className="p-1.5 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 transition-colors"
          title={isPlaying ? 'Pause (Space)' : 'Play (Space)'}
        >
          {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
        </button>
        <span className="text-[11px] text-zinc-400 tabular-nums min-w-[80px] text-center">
          {formatTime(playheadPos)} / {formatTime(timelineDuration)}
        </span>
        {activeClip && (
          <span className="text-[10px] text-zinc-600 capitalize">{activeClip.role}</span>
        )}
      </div>
    </div>
  )
}


export default function ProjectEditor() {
  const { id: projectId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()

  const [project, setProject] = useState<ProjectData | null>(null)
  const [dirty, setDirty] = useState(false)
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null)
  const [selectedTextId, setSelectedTextId] = useState<string | null>(null)
  const [renderJobId, setRenderJobId] = useState<string | null>(null)
  const [arrangeJobId, setArrangeJobId] = useState<string | null>(null)
  const [previewVideoUrl, setPreviewVideoUrl] = useState<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [zoom, setZoom] = useState(1.0)
  const [mediaBrowserOpen, setMediaBrowserOpen] = useState(false)
  const [undoStack, setUndoStack] = useState<ProjectData[]>([])
  const [playheadPos, setPlayheadPos] = useState(0)
  const [musicUploading, setMusicUploading] = useState(false)
  const [musicInfo, setMusicInfo] = useState<{ bpm?: number; duration?: number; sections?: number } | null>(null)
  const [musicBrowserOpen, setMusicBrowserOpen] = useState(false)
  const [musicSearchQuery, setMusicSearchQuery] = useState('')
  const [musicSearchMood, setMusicSearchMood] = useState('')
  const [musicSearchGenre, setMusicSearchGenre] = useState('')
  const [musicSearchResults, setMusicSearchResults] = useState<MusicTrack[]>([])
  const [musicSearching, setMusicSearching] = useState(false)
  const [musicSelecting, setMusicSelecting] = useState<string | null>(null)
  const [musicPreviewTrackId, setMusicPreviewTrackId] = useState<string | null>(null)
  const [musicLibraryAvailable, setMusicLibraryAvailable] = useState<boolean | null>(null)
  const [musicSuggesting, setMusicSuggesting] = useState(false)
  const musicPreviewRef = useRef<HTMLAudioElement | null>(null)
  const timelineScrollRef = useRef<HTMLDivElement>(null)

  const pixelsPerSecond = PIXELS_PER_SECOND * zoom

  const { data: fetchedProject, isLoading, error: loadError } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => fetchProject(projectId!),
    enabled: !!projectId,
    retry: 1,
  })

  // Sync fetched data into local state (only when not dirty)
  useEffect(() => {
    if (fetchedProject && !dirty) {
      setProject(fetchedProject)
    }
  }, [fetchedProject])

  // Check music library availability on mount
  useEffect(() => {
    fetchMusicLibraryStatus()
      .then(res => setMusicLibraryAvailable(res.available))
      .catch(() => setMusicLibraryAvailable(false))
  }, [])

  // Cleanup music preview audio on unmount
  useEffect(() => {
    return () => {
      if (musicPreviewRef.current) {
        musicPreviewRef.current.pause()
        musicPreviewRef.current = null
      }
    }
  }, [])

  const saveMut = useMutation({
    mutationFn: () => updateProject(projectId!, project!),
    onSuccess: (data) => {
      setProject(data)
      setDirty(false)
      toast('Project saved', 'success')
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    },
    onError: (err) => toast(err instanceof Error ? err.message : 'Save failed', 'error'),
  })

  const previewMut = useMutation({
    mutationFn: async () => {
      // Save first so the backend has the latest prompt
      if (project && dirty) {
        await updateProject(projectId!, project)
      }
      return projectPreview(projectId!)
    },
    onSuccess: (data) => {
      setArrangeJobId(data.job_id)
    },
    onError: (err) => toast(err instanceof Error ? err.message : 'Preview failed', 'error'),
  })

  // Poll the AI arrange job for progress
  const { data: arrangeJob } = useQuery({
    queryKey: ['job', arrangeJobId],
    queryFn: () => fetchJob(arrangeJobId!),
    enabled: !!arrangeJobId,
    refetchInterval: (query) => {
      const j = query.state.data
      return j && (j.status === 'queued' || j.status === 'running') ? 800 : false
    },
  })

  const prevArrangeStatus = useRef(arrangeJob?.status)
  useEffect(() => {
    const prev = prevArrangeStatus.current
    prevArrangeStatus.current = arrangeJob?.status
    if (prev === arrangeJob?.status) return
    if (arrangeJob?.status === 'completed') {
      // Load the updated project from the job result
      if ((arrangeJob as any)?.project) {
        setProject((arrangeJob as any).project)
        setDirty(false)
      }
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      const shots = (arrangeJob as any)?.project?.timeline?.tracks?.[0]?.clips?.length || 0
      toast(`AI arranged ${shots} shots`, 'success')
      setArrangeJobId(null)
    } else if (arrangeJob?.status === 'failed') {
      toast('AI arrange failed: ' + (arrangeJob?.message || ''), 'error')
      setArrangeJobId(null)
    }
  }, [arrangeJob?.status])

  const isArranging = !!arrangeJobId && arrangeJob?.status !== 'completed' && arrangeJob?.status !== 'failed'

  const renderMut = useMutation({
    mutationFn: () => projectRender(projectId!),
    onSuccess: (data) => {
      setRenderJobId(data.job_id)
      toast('Rendering started', 'success')
    },
    onError: (err) => toast(err instanceof Error ? err.message : 'Render failed', 'error'),
  })

  const { data: job } = useQuery({
    queryKey: ['job', renderJobId],
    queryFn: () => fetchJob(renderJobId!),
    enabled: !!renderJobId,
    refetchInterval: (query) => {
      const j = query.state.data
      return j && (j.status === 'queued' || j.status === 'running') ? 2000 : false
    },
  })

  const prevJobStatus = useRef(job?.status)
  useEffect(() => {
    const prev = prevJobStatus.current
    prevJobStatus.current = job?.status
    if (prev === job?.status) return
    if (job?.status === 'completed') {
      toast('Video rendered!', 'success')
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    } else if (job?.status === 'failed') {
      toast('Render failed: ' + (job?.message || ''), 'error')
    }
  }, [job?.status])

  // Mutation helpers
  const updateProjectLocal = useCallback((updater: (p: ProjectData) => ProjectData) => {
    setProject(prev => {
      if (!prev) return prev
      // Push current state to undo stack (limit 30)
      setUndoStack(stack => [...stack.slice(-29), prev])
      const updated = updater(prev)
      return updated
    })
    setDirty(true)
  }, [])

  const undo = useCallback(() => {
    setUndoStack(stack => {
      if (stack.length === 0) return stack
      const prev = stack[stack.length - 1]
      setProject(prev)
      return stack.slice(0, -1)
    })
  }, [])

  // Music library callbacks
  const handleMusicSearch = useCallback(async () => {
    setMusicSearching(true)
    try {
      const result = await searchMusicLibrary({
        query: musicSearchQuery,
        mood: musicSearchMood,
        genre: musicSearchGenre,
        limit: 20,
      })
      setMusicSearchResults(result.tracks)
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Music search failed', 'error')
    } finally {
      setMusicSearching(false)
    }
  }, [musicSearchQuery, musicSearchMood, musicSearchGenre, toast])

  const handleMusicPreview = useCallback((track: MusicTrack) => {
    if (musicPreviewTrackId === track.id) {
      if (musicPreviewRef.current) {
        musicPreviewRef.current.pause()
        musicPreviewRef.current = null
      }
      setMusicPreviewTrackId(null)
    } else {
      if (musicPreviewRef.current) {
        musicPreviewRef.current.pause()
      }
      const audio = new Audio(track.preview_url)
      audio.volume = 0.5
      audio.play().catch(() => {})
      audio.onended = () => setMusicPreviewTrackId(null)
      musicPreviewRef.current = audio
      setMusicPreviewTrackId(track.id)
    }
  }, [musicPreviewTrackId])

  const handleSelectLibraryTrack = useCallback(async (track: MusicTrack) => {
    if (!projectId) return
    setMusicSelecting(track.id)
    try {
      if (musicPreviewRef.current) {
        musicPreviewRef.current.pause()
        musicPreviewRef.current = null
        setMusicPreviewTrackId(null)
      }
      const result = await selectLibraryMusic(projectId, track.id)
      updateProjectLocal(p => ({ ...p, music_path: result.music_path }))
      setMusicInfo({ bpm: result.bpm, duration: result.duration, sections: result.sections })
      toast(`Music set: ${track.title} by ${track.artist}`, 'success')
      setMusicBrowserOpen(false)
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Failed to select track', 'error')
    } finally {
      setMusicSelecting(null)
    }
  }, [projectId, toast, updateProjectLocal])

  const handleSuggestMusic = useCallback(async () => {
    if (!projectId) return
    setMusicSuggesting(true)
    setMusicBrowserOpen(true)
    try {
      const result = await suggestMusic(projectId)
      setMusicSearchResults(result.tracks)
      setMusicSearchQuery('')
      setMusicSearchMood('')
      setMusicSearchGenre('')
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Music suggestion failed', 'error')
    } finally {
      setMusicSuggesting(false)
    }
  }, [projectId, toast])

  const updateClip = useCallback((clipId: string, updates: Partial<TimelineClip>) => {
    updateProjectLocal(p => ({
      ...p,
      timeline: {
        ...p.timeline,
        tracks: p.timeline.tracks.map(track => ({
          ...track,
          clips: track.clips.map(c => c.id === clipId ? { ...c, ...updates } : c),
        })),
      },
    }))
  }, [updateProjectLocal])

  const removeClip = useCallback((clipId: string) => {
    updateProjectLocal(p => ({
      ...p,
      timeline: {
        ...p.timeline,
        tracks: p.timeline.tracks.map(track => ({
          ...track,
          clips: track.clips.filter(c => c.id !== clipId),
        })),
      },
    }))
    setSelectedClipId(null)
  }, [updateProjectLocal])

  const toggleTrackMute = useCallback((trackId: string) => {
    updateProjectLocal(p => ({
      ...p,
      timeline: {
        ...p.timeline,
        tracks: p.timeline.tracks.map(t => t.id === trackId ? { ...t, muted: !t.muted } : t),
      },
    }))
  }, [updateProjectLocal])

  const toggleTrackLock = useCallback((trackId: string) => {
    updateProjectLocal(p => ({
      ...p,
      timeline: {
        ...p.timeline,
        tracks: p.timeline.tracks.map(t => t.id === trackId ? { ...t, locked: !t.locked } : t),
      },
    }))
  }, [updateProjectLocal])

  const updateTextElement = useCallback((textId: string, updates: Partial<TextElement>) => {
    updateProjectLocal(p => ({
      ...p,
      timeline: {
        ...p.timeline,
        tracks: p.timeline.tracks.map(track => ({
          ...track,
          text_elements: track.text_elements.map(te => te.id === textId ? { ...te, ...updates } : te),
        })),
      },
    }))
  }, [updateProjectLocal])

  const removeTextElement = useCallback((textId: string) => {
    updateProjectLocal(p => ({
      ...p,
      timeline: {
        ...p.timeline,
        tracks: p.timeline.tracks.map(track => ({
          ...track,
          text_elements: track.text_elements.filter(te => te.id !== textId),
        })),
      },
    }))
    setSelectedTextId(null)
  }, [updateProjectLocal])

  const addTextElement = useCallback((style: string = 'caption') => {
    const id = Math.random().toString(36).slice(2, 14)
    const textTrack = project?.timeline.tracks.find(t => t.type === 'text')
    if (!project) return

    const newElement: TextElement = {
      id,
      text: style === 'title' ? 'Title' : style === 'lower_third' ? 'Name | Location' : 'Caption text',
      position: 0,
      duration: style === 'title' ? 3.0 : 4.0,
      x: 0.5,
      y: style === 'lower_third' ? 0.8 : style === 'caption' ? 0.85 : 0.5,
      font_size: style === 'title' ? 56 : style === 'lower_third' ? 32 : 28,
      font_family: 'Helvetica',
      color: '#FFFFFF',
      bg_color: '',
      animation: 'fade',
      style,
    }

    if (textTrack) {
      updateProjectLocal(p => ({
        ...p,
        timeline: {
          ...p.timeline,
          tracks: p.timeline.tracks.map(t =>
            t.id === textTrack.id
              ? { ...t, text_elements: [...t.text_elements, newElement] }
              : t
          ),
        },
      }))
    } else {
      // Create a text track
      const newTrack: TimelineTrack = {
        id: Math.random().toString(36).slice(2, 10),
        name: 'Titles',
        type: 'text',
        clips: [],
        text_elements: [newElement],
        muted: false,
        locked: false,
        volume: 1.0,
      }
      updateProjectLocal(p => ({
        ...p,
        timeline: {
          ...p.timeline,
          tracks: [...p.timeline.tracks, newTrack],
        },
      }))
    }
    setSelectedTextId(id)
    setSelectedClipId(null)
  }, [project, updateProjectLocal])

  const handleSelectClip = useCallback((id: string) => {
    setSelectedClipId(id)
    setSelectedTextId(null)
  }, [])

  const handleSelectText = useCallback((id: string) => {
    setSelectedTextId(id)
    setSelectedClipId(null)
  }, [])

  const addClipFromMedia = useCallback((item: MediaItem) => {
    if (!project) return
    const existingVideoTrack = project.timeline.tracks.find(t => t.type === 'video')

    // Place at the end of existing clips
    let endPos = 0
    if (existingVideoTrack) {
      for (const c of existingVideoTrack.clips) {
        const cEnd = c.position + c.duration
        if (cEnd > endPos) endPos = cEnd
      }
    }

    const clipDuration = item.media_type === 'video' ? Math.min(item.duration || 5, 10) : 4.0
    const newClip: TimelineClip = {
      id: Math.random().toString(36).slice(2, 14),
      media_uuid: item.uuid,
      media_path: item.path,
      media_type: item.media_type,
      in_point: 0,
      out_point: item.media_type === 'video' ? clipDuration : 0,
      position: endPos,
      duration: clipDuration,
      volume: 1.0,
      effects: [],
      transition: { type: 'crossfade', duration: 0.5 },
      role: 'highlight',
      reason: '',
    }

    updateProjectLocal(p => {
      let tracks = p.timeline.tracks
      let targetTrackId: string

      if (existingVideoTrack) {
        targetTrackId = existingVideoTrack.id
        tracks = tracks.map(t =>
          t.id === targetTrackId ? { ...t, clips: [...t.clips, newClip] } : t
        )
      } else {
        // Create a default video track with the new clip
        const newTrack = {
          id: Math.random().toString(36).slice(2, 10),
          name: 'Main Video',
          type: 'video',
          clips: [newClip],
          text_elements: [],
          muted: false,
          locked: false,
          volume: 1.0,
        }
        tracks = [newTrack, ...tracks]
      }

      return {
        ...p,
        timeline: {
          ...p.timeline,
          tracks,
          duration: Math.max(p.timeline.duration, endPos + clipDuration),
        },
      }
    })
    setSelectedClipId(newClip.id)
    setSelectedTextId(null)
  }, [project, updateProjectLocal])

  const moveClip = useCallback((clipId: string, newPosition: number) => {
    updateProjectLocal(p => ({
      ...p,
      timeline: {
        ...p.timeline,
        tracks: p.timeline.tracks.map(track => ({
          ...track,
          clips: track.clips.map(c => c.id === clipId ? { ...c, position: newPosition } : c),
          text_elements: track.text_elements.map(te => te.id === clipId ? { ...te, position: newPosition } : te),
        })),
      },
    }))
  }, [updateProjectLocal])

  const resizeClip = useCallback((clipId: string, newDuration: number) => {
    updateProjectLocal(p => ({
      ...p,
      timeline: {
        ...p.timeline,
        tracks: p.timeline.tracks.map(track => ({
          ...track,
          clips: track.clips.map(c => c.id === clipId ? { ...c, duration: newDuration } : c),
          text_elements: track.text_elements.map(te => te.id === clipId ? { ...te, duration: newDuration } : te),
        })),
      },
    }))
  }, [updateProjectLocal])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      if (e.key === ' ' || e.key === 'k') {
        e.preventDefault()
        setIsPlaying(prev => !prev)
      }
      if (e.key === 'Escape') {
        setSelectedClipId(null)
        setSelectedTextId(null)
        setIsPlaying(false)
      }
      if ((e.key === 'Delete' || e.key === 'Backspace') && (selectedClipId || selectedTextId)) {
        e.preventDefault()
        if (selectedClipId) removeClip(selectedClipId)
        if (selectedTextId) removeTextElement(selectedTextId)
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'z') {
        e.preventDefault()
        undo()
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault()
        if (dirty && project) saveMut.mutate()
      }
      if (e.key === 'm' && !e.metaKey && !e.ctrlKey) {
        setMediaBrowserOpen(prev => !prev)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedClipId, selectedTextId, dirty, project, undo, removeClip, removeTextElement, saveMut])

  // Find selected clip or text element
  const selectedClip = useMemo(() => {
    if (!project || !selectedClipId) return null
    for (const track of project.timeline.tracks) {
      const clip = track.clips.find(c => c.id === selectedClipId)
      if (clip) return clip
    }
    return null
  }, [project, selectedClipId])

  const selectedText = useMemo(() => {
    if (!project || !selectedTextId) return null
    for (const track of project.timeline.tracks) {
      const te = track.text_elements.find(t => t.id === selectedTextId)
      if (te) return te
    }
    return null
  }, [project, selectedTextId])

  // Auto-compute timeline duration from clip/text positions
  const timelineDuration = useMemo(() => {
    if (!project) return 0
    let maxEnd = 0
    for (const track of project.timeline.tracks) {
      for (const c of track.clips) {
        maxEnd = Math.max(maxEnd, c.position + c.duration)
      }
      for (const te of track.text_elements) {
        maxEnd = Math.max(maxEnd, te.position + te.duration)
      }
    }
    // Add a little padding and round up
    return Math.max(maxEnd + 2, project.timeline.duration || 0)
  }, [project])
  const videoTrack = project?.timeline.tracks.find(t => t.type === 'video')
  const clipCount = videoTrack?.clips.length || 0
  const [sidePanel, setSidePanel] = useState<'brief' | 'inspector' | 'media' | 'settings' | 'renders'>('brief')

  // Auto-switch to inspector when a clip/text is selected
  useEffect(() => {
    if (selectedClipId || selectedTextId) setSidePanel('inspector')
  }, [selectedClipId, selectedTextId])

  // Auto-switch to media when media browser opens
  useEffect(() => {
    if (mediaBrowserOpen) setSidePanel('media')
  }, [mediaBrowserOpen])

  const isJobRunning = job && (job.status === 'queued' || job.status === 'running')
  const isJobDone = job?.status === 'completed'

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-500" />
      </div>
    )
  }

  if (loadError || !project) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-zinc-500">
        <Layers className="w-12 h-12 opacity-20" />
        <p className="text-sm font-medium text-zinc-400">
          {loadError ? 'Failed to load project' : 'Project not found'}
        </p>
        <p className="text-xs text-zinc-600 max-w-sm text-center">
          {loadError instanceof Error ? loadError.message : 'The project may have been deleted, or the server is not running.'}
        </p>
        <button
          onClick={() => navigate('/projects')}
          className="mt-2 flex items-center gap-1.5 text-xs font-medium px-4 py-2 rounded-lg bg-zinc-800 text-zinc-300 hover:bg-zinc-700 border border-zinc-700 transition-colors"
        >
          <ChevronLeft className="w-3.5 h-3.5" /> Back to Projects
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-zinc-950">
      {/* Top bar — compact toolbar */}
      <div className="shrink-0 bg-zinc-900/90 border-b border-zinc-800 px-3 py-1.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate('/projects')}
            className="p-1 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <input
            type="text"
            value={project.name}
            onChange={(e) => updateProjectLocal(p => ({ ...p, name: e.target.value }))}
            className="bg-transparent text-sm font-semibold text-zinc-100 focus:outline-none border-b border-transparent focus:border-violet-500 transition-colors w-48"
          />
          <div className="flex items-center gap-2 text-[10px] text-zinc-500">
            <span>{clipCount} clips</span>
            <span className="text-zinc-700">|</span>
            <span>{timelineDuration > 0 ? `${Math.floor(timelineDuration / 60)}:${String(Math.floor(timelineDuration % 60)).padStart(2, '0')}` : '0:00'}</span>
            {dirty && <span className="text-amber-400 ml-1">unsaved</span>}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={undo} disabled={undoStack.length === 0} className="p-1.5 rounded text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 disabled:opacity-20 transition-colors" title="Undo (Ctrl+Z)">
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
          <button onClick={() => saveMut.mutate()} disabled={!dirty || saveMut.isPending} className="flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded bg-zinc-800 text-zinc-300 hover:bg-zinc-700 disabled:opacity-30 transition-colors border border-zinc-700" title="Save (Ctrl+S)">
            {saveMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />} Save
          </button>
          <button
            onClick={() => renderMut.mutate()}
            disabled={clipCount === 0 || renderMut.isPending || !!isJobRunning}
            className="flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-30 transition-colors"
          >
            {(renderMut.isPending || isJobRunning) ? <Loader2 className="w-3 h-3 animate-spin" /> : <Clapperboard className="w-3 h-3" />} Export
          </button>
        </div>
      </div>

      {/* Render progress bar (only when rendering) */}
      {isJobRunning && job && (
        <div className="shrink-0 bg-violet-500/10 border-b border-violet-500/30 px-4 py-1.5">
          <div className="flex items-center justify-between text-[10px] mb-1">
            <span className="text-violet-300">{job.message}</span>
            <span className="text-violet-400 tabular-nums">{job.progress}%</span>
          </div>
          <div className="w-full h-1 bg-violet-900/50 rounded-full overflow-hidden">
            <div className="h-full bg-violet-500 rounded-full transition-all duration-700" style={{ width: `${job.progress}%` }} />
          </div>
        </div>
      )}

      {/* ===== MAIN AREA: Preview + Side Panel ===== */}
      <div className="flex flex-1 min-h-0">
        {/* LEFT: Preview Monitor */}
        <div className="flex-1 flex flex-col min-w-0 bg-black">
          <TimelinePreview
            tracks={project.timeline.tracks}
            playheadPos={playheadPos}
            onPlayheadChange={setPlayheadPos}
            timelineDuration={timelineDuration}
            isPlaying={isPlaying}
            setIsPlaying={setIsPlaying}
            projectId={projectId}
            hasMusicTrack={!!project.music_path}
            musicVolume={project.music_volume}
          />

          {/* Render complete overlay inside monitor */}
          {isJobDone && job?.output_path && (
            <div className="shrink-0 bg-emerald-500/10 border-t border-emerald-500/30 px-3 py-2">
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-emerald-300 font-medium">Export ready</span>
                <a href={job.output_path} download className="flex items-center gap-1 text-[11px] font-medium bg-zinc-700/60 text-zinc-300 hover:bg-zinc-700 px-2 py-1 rounded transition-colors">
                  <Download className="w-3 h-3" /> Download
                </a>
                <button onClick={() => { setPreviewVideoUrl(job.output_path!); setSidePanel('renders') }} className="flex items-center gap-1 text-[11px] font-medium text-zinc-400 hover:text-zinc-200 px-2 py-1 rounded transition-colors">
                  <Play className="w-3 h-3" /> Watch
                </button>
                <button onClick={() => setRenderJobId(null)} className="ml-auto text-zinc-600 hover:text-zinc-400 transition-colors">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}
        </div>

        {/* RIGHT: Side Panel with tabs */}
        <div className="w-80 shrink-0 flex flex-col border-l border-zinc-800 bg-zinc-900/70">
          {/* Tab bar */}
          <div className="shrink-0 flex border-b border-zinc-800">
            {([
              { key: 'brief' as const, icon: Sparkles, label: 'Brief' },
              { key: 'media' as const, icon: ImagePlus, label: 'Media' },
              { key: 'inspector' as const, icon: Layers, label: 'Inspect' },
              { key: 'settings' as const, icon: Settings, label: 'Settings' },
              ...(project.render_history.length > 0 ? [{ key: 'renders' as const, icon: Film, label: 'Renders' }] : []),
            ]).map(({ key, icon: Icon, label }) => (
              <button
                key={key}
                onClick={() => { setSidePanel(key); setMediaBrowserOpen(key === 'media') }}
                title={label}
                className={`flex-1 flex items-center justify-center gap-1 py-2 text-[10px] font-medium transition-colors border-b-2 ${
                  sidePanel === key
                    ? 'text-violet-300 border-violet-500 bg-violet-500/5'
                    : 'text-zinc-500 border-transparent hover:text-zinc-300 hover:bg-zinc-800/50'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                <span className="hidden sm:inline truncate">{label}</span>
              </button>
            ))}
          </div>

          {/* Panel content */}
          <div className="flex-1 overflow-y-auto">
            {/* Brief tab */}
            {sidePanel === 'brief' && (
              <div className="p-3 space-y-3">
                <div>
                  <label className="block text-[10px] font-medium text-zinc-500 uppercase tracking-wide mb-1.5">Creative Brief</label>
                  <textarea
                    value={project.prompt}
                    onChange={(e) => updateProjectLocal(p => ({ ...p, prompt: e.target.value }))}
                    onKeyDown={(e) => {
                      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && project.prompt && !isArranging) {
                        e.preventDefault()
                        previewMut.mutate()
                      }
                    }}
                    disabled={isArranging}
                    placeholder="Describe what this video should be about..."
                    rows={4}
                    className="w-full bg-zinc-800/50 border border-zinc-700/50 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none disabled:opacity-50"
                  />
                  {isArranging ? (
                    <div className="mt-2 space-y-1.5">
                      <div className="flex items-center gap-2">
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-violet-400 shrink-0" />
                        <span className="text-xs text-zinc-300 truncate">{arrangeJob?.message || 'Starting...'}</span>
                      </div>
                      <div className="h-1.5 w-full bg-zinc-800 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-violet-500 rounded-full transition-all duration-500 ease-out"
                          style={{ width: `${arrangeJob?.progress || 0}%` }}
                        />
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => previewMut.mutate()}
                      disabled={!project.prompt || previewMut.isPending}
                      className="w-full mt-2 flex items-center justify-center gap-1.5 text-xs font-medium px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-30 transition-colors"
                      title="AI Arrange (Ctrl+Enter)"
                    >
                      {previewMut.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                      AI Arrange
                    </button>
                  )}
                  {project.narrative_summary && !isArranging && (
                    <div className="mt-3 bg-zinc-800/50 border border-zinc-700/50 rounded-lg p-4">
                      <h4 className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wide mb-1.5">Director's Vision</h4>
                      <p className="text-sm text-zinc-300 leading-relaxed">{project.narrative_summary}</p>
                      {project.music_mood && (
                        <div className="flex items-center gap-1.5 mt-2.5 text-xs text-zinc-400">
                          <Music className="w-3 h-3 text-violet-400 shrink-0" />
                          <span>Mood: <span className="text-zinc-300">{project.music_mood}</span></span>
                        </div>
                      )}
                    </div>
                  )}
                  {!project.narrative_summary && project.prompt && !isArranging && (
                    <p className="text-[10px] text-zinc-600 mt-1.5">
                      <kbd className="px-1 py-0.5 rounded bg-zinc-800 text-zinc-500 text-[9px]">Ctrl+Enter</kbd> to generate
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Inspector tab */}
            {sidePanel === 'inspector' && (
              <div className="p-3">
                {selectedClip ? (
                  <ClipInspector
                    clip={selectedClip}
                    onUpdate={(updates) => updateClip(selectedClip.id, updates)}
                    onRemove={() => removeClip(selectedClip.id)}
                    onClose={() => setSelectedClipId(null)}
                  />
                ) : selectedText ? (
                  <TextElementInspector
                    element={selectedText}
                    onUpdate={(updates) => updateTextElement(selectedText.id, updates)}
                    onRemove={() => removeTextElement(selectedText.id)}
                    onClose={() => setSelectedTextId(null)}
                  />
                ) : (
                  <div className="text-center py-12 text-zinc-600">
                    <Layers className="w-8 h-8 mx-auto mb-2 opacity-20" />
                    <p className="text-xs">Select a clip or text element to inspect</p>
                  </div>
                )}
              </div>
            )}

            {/* Media tab */}
            {sidePanel === 'media' && (
              <MediaBrowser
                onAddClip={addClipFromMedia}
                onClose={() => { setMediaBrowserOpen(false); setSidePanel('brief') }}
              />
            )}

            {/* Settings tab */}
            {sidePanel === 'settings' && (
              <div className="p-3 space-y-4">
                <div>
                  <label className="block text-[10px] font-medium text-zinc-500 uppercase tracking-wide mb-1.5">Theme</label>
                  <div className="grid grid-cols-2 gap-1">
                    {THEME_OPTIONS.map(t => (
                      <button
                        key={t.value}
                        onClick={() => updateProjectLocal(p => ({ ...p, theme: t.value }))}
                        className={`text-[10px] px-2 py-1.5 rounded-md border transition-colors ${
                          project.theme === t.value
                            ? 'bg-violet-600/20 border-violet-500/40 text-violet-300'
                            : 'bg-zinc-800/60 border-zinc-700/40 text-zinc-400 hover:text-zinc-200 hover:border-zinc-600'
                        }`}
                      >
                        {t.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="block text-[10px] font-medium text-zinc-500 uppercase tracking-wide mb-1.5">Background Music</label>
                  {project.music_path ? (
                    <div className="space-y-2">
                      <div className="bg-zinc-800/50 border border-zinc-700/40 rounded-md p-2.5">
                        <div className="flex items-center gap-2 mb-2">
                          <div className="w-8 h-8 rounded-md bg-violet-600/20 border border-violet-500/30 flex items-center justify-center shrink-0">
                            <Music className="w-4 h-4 text-violet-400" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs text-zinc-300 truncate font-medium">{project.music_path.split('/').pop()}</p>
                            {musicInfo?.duration != null && (
                              <p className="text-[10px] text-zinc-500">{Math.floor(musicInfo.duration / 60)}:{String(Math.floor(musicInfo.duration % 60)).padStart(2, '0')}</p>
                            )}
                          </div>
                          <button
                            onClick={async () => {
                              try {
                                await deleteProjectMusic(projectId!)
                                updateProjectLocal(p => ({ ...p, music_path: '' }))
                                setMusicInfo(null)
                                toast('Music removed', 'success')
                              } catch (err) {
                                toast(err instanceof Error ? err.message : 'Failed to remove', 'error')
                              }
                            }}
                            className="p-1 text-zinc-500 hover:text-red-400 transition-colors shrink-0"
                            title="Remove music"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                        {(musicInfo?.bpm != null || musicInfo?.sections != null) && (
                          <div className="flex items-center gap-3 text-[10px]">
                            {musicInfo.bpm != null && (
                              <span className="flex items-center gap-1 text-violet-300 font-medium bg-violet-600/10 border border-violet-500/20 rounded px-1.5 py-0.5">
                                <Clock className="w-3 h-3" /> {musicInfo.bpm} BPM
                              </span>
                            )}
                            {musicInfo.sections != null && (
                              <span className="text-zinc-500">{musicInfo.sections} section{musicInfo.sections !== 1 ? 's' : ''} detected</span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <label className={`flex flex-col items-center gap-1.5 text-xs font-medium px-3 py-4 rounded-md border border-dashed transition-colors ${
                      musicUploading
                        ? 'bg-violet-600/10 border-violet-500/30 text-violet-300 cursor-wait'
                        : 'bg-zinc-800/40 border-zinc-700/40 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 cursor-pointer'
                    }`}>
                      {musicUploading ? (
                        <>
                          <Loader2 className="w-5 h-5 animate-spin text-violet-400" />
                          <span className="text-[11px]">Uploading & analyzing...</span>
                        </>
                      ) : (
                        <>
                          <Upload className="w-5 h-5" />
                          <span className="text-[11px]">Upload Music</span>
                          <span className="text-[9px] text-zinc-600 font-normal">MP3, WAV, M4A, AAC, FLAC, OGG</span>
                        </>
                      )}
                      <input
                        type="file"
                        accept=".mp3,.wav,.aac,.m4a,.ogg,.flac"
                        className="hidden"
                        disabled={musicUploading}
                        onChange={async (e) => {
                          const file = e.target.files?.[0]
                          if (!file) return
                          setMusicUploading(true)
                          try {
                            const result = await uploadProjectMusic(projectId!, file)
                            updateProjectLocal(p => ({ ...p, music_path: result.music_path }))
                            setMusicInfo({ bpm: result.bpm, duration: result.duration, sections: result.sections })
                            const bpmStr = result.bpm ? ` (${result.bpm} BPM)` : ''
                            toast(`Music uploaded: ${result.filename}${bpmStr}`, 'success')
                          } catch (err) {
                            toast(err instanceof Error ? err.message : 'Upload failed', 'error')
                          } finally {
                            setMusicUploading(false)
                            // Reset the input so the same file can be re-selected
                            e.target.value = ''
                          }
                        }}
                      />
                    </label>
                  )}
                </div>

                {/* Music Library Browser */}
                {musicLibraryAvailable && (
                  <div>
                    <div className="flex items-center gap-2 mb-1.5">
                      {!musicBrowserOpen ? (
                        <>
                          <button
                            onClick={() => setMusicBrowserOpen(true)}
                            className="flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1.5 rounded-md bg-zinc-800/60 border border-zinc-700/40 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 transition-colors"
                          >
                            <Library className="w-3.5 h-3.5" />
                            Browse Library
                          </button>
                          {project.music_mood && (
                            <button
                              onClick={handleSuggestMusic}
                              disabled={musicSuggesting}
                              className="flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1.5 rounded-md bg-violet-600/15 border border-violet-500/30 text-violet-300 hover:bg-violet-600/25 hover:border-violet-500/50 transition-colors disabled:opacity-50"
                            >
                              {musicSuggesting ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              ) : (
                                <Sparkles className="w-3.5 h-3.5" />
                              )}
                              AI Suggest
                            </button>
                          )}
                        </>
                      ) : (
                        <button
                          onClick={() => {
                            setMusicBrowserOpen(false)
                            if (musicPreviewRef.current) {
                              musicPreviewRef.current.pause()
                              musicPreviewRef.current = null
                              setMusicPreviewTrackId(null)
                            }
                          }}
                          className="flex items-center gap-1 text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors"
                        >
                          <X className="w-3.5 h-3.5" />
                          Close Library
                        </button>
                      )}
                    </div>

                    {musicBrowserOpen && (
                      <div className="bg-zinc-800/40 border border-zinc-700/40 rounded-md p-2.5 space-y-2">
                        {/* Search controls */}
                        <div className="flex gap-1.5">
                          <input
                            type="text"
                            placeholder="Search music..."
                            value={musicSearchQuery}
                            onChange={e => setMusicSearchQuery(e.target.value)}
                            onKeyDown={e => { if (e.key === 'Enter') handleMusicSearch() }}
                            className="flex-1 bg-zinc-900/60 border border-zinc-700/40 rounded px-2 py-1 text-[11px] text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-violet-500/50"
                          />
                          <button
                            onClick={handleMusicSearch}
                            disabled={musicSearching}
                            className="px-2 py-1 bg-violet-600/20 border border-violet-500/30 rounded text-violet-300 hover:bg-violet-600/30 transition-colors disabled:opacity-50"
                          >
                            {musicSearching ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <Search className="w-3.5 h-3.5" />
                            )}
                          </button>
                        </div>
                        <div className="flex gap-1.5">
                          <select
                            value={musicSearchMood}
                            onChange={e => setMusicSearchMood(e.target.value)}
                            className="flex-1 bg-zinc-900/60 border border-zinc-700/40 rounded px-1.5 py-1 text-[10px] text-zinc-300 focus:outline-none focus:border-violet-500/50"
                          >
                            <option value="">Any mood</option>
                            <option value="happy">Happy</option>
                            <option value="chill">Chill</option>
                            <option value="epic">Epic</option>
                            <option value="dramatic">Dramatic</option>
                            <option value="romantic">Romantic</option>
                            <option value="sad">Sad</option>
                            <option value="energetic">Energetic</option>
                            <option value="ambient">Ambient</option>
                            <option value="dark">Dark</option>
                            <option value="inspirational">Inspirational</option>
                            <option value="nostalgic">Nostalgic</option>
                            <option value="peaceful">Peaceful</option>
                          </select>
                          <select
                            value={musicSearchGenre}
                            onChange={e => setMusicSearchGenre(e.target.value)}
                            className="flex-1 bg-zinc-900/60 border border-zinc-700/40 rounded px-1.5 py-1 text-[10px] text-zinc-300 focus:outline-none focus:border-violet-500/50"
                          >
                            <option value="">Any genre</option>
                            <option value="pop">Pop</option>
                            <option value="electronic">Electronic</option>
                            <option value="rock">Rock</option>
                            <option value="classical">Classical</option>
                            <option value="acoustic">Acoustic</option>
                            <option value="jazz">Jazz</option>
                            <option value="hip-hop">Hip-Hop</option>
                            <option value="ambient">Ambient</option>
                            <option value="folk">Folk</option>
                            <option value="indie">Indie</option>
                            <option value="country">Country</option>
                            <option value="blues">Blues</option>
                            <option value="lofi">Lo-Fi</option>
                          </select>
                        </div>

                        {/* Results list */}
                        {musicSearchResults.length > 0 ? (
                          <div className="max-h-64 overflow-y-auto space-y-1 pr-0.5">
                            {musicSearchResults.map(track => (
                              <div
                                key={track.id}
                                className="bg-zinc-900/50 border border-zinc-700/30 rounded-md p-2 hover:border-zinc-600/50 transition-colors"
                              >
                                <div className="flex items-start gap-2">
                                  {track.image_url && (
                                    <img
                                      src={track.image_url}
                                      alt=""
                                      className="w-8 h-8 rounded shrink-0 object-cover bg-zinc-800"
                                      onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                                    />
                                  )}
                                  <div className="flex-1 min-w-0">
                                    <p className="text-[11px] font-medium text-zinc-200 truncate">{track.title}</p>
                                    <p className="text-[10px] text-zinc-500 truncate">{track.artist}</p>
                                    <div className="flex items-center gap-2 mt-1 flex-wrap">
                                      <span className="text-[9px] text-zinc-500 tabular-nums">
                                        {Math.floor(track.duration / 60)}:{String(track.duration % 60).padStart(2, '0')}
                                      </span>
                                      {track.bpm && (
                                        <span className="text-[9px] text-zinc-500">{track.bpm} BPM</span>
                                      )}
                                      {track.genre && (
                                        <span className="text-[9px] px-1 py-0.5 rounded bg-zinc-800/80 text-zinc-400">{track.genre}</span>
                                      )}
                                      <span className="text-[8px] text-zinc-600">{track.license}</span>
                                    </div>
                                  </div>
                                </div>
                                <div className="flex items-center gap-1.5 mt-1.5">
                                  <button
                                    onClick={() => handleMusicPreview(track)}
                                    className={`flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded transition-colors ${
                                      musicPreviewTrackId === track.id
                                        ? 'bg-violet-600/20 text-violet-300 border border-violet-500/30'
                                        : 'text-zinc-400 hover:text-zinc-200 border border-zinc-700/40 hover:border-zinc-600'
                                    }`}
                                  >
                                    {musicPreviewTrackId === track.id ? (
                                      <><Pause className="w-3 h-3" /> Stop</>
                                    ) : (
                                      <><Play className="w-3 h-3" /> Preview</>
                                    )}
                                  </button>
                                  <button
                                    onClick={() => handleSelectLibraryTrack(track)}
                                    disabled={musicSelecting === track.id}
                                    className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-violet-600/15 border border-violet-500/25 text-violet-300 hover:bg-violet-600/25 transition-colors disabled:opacity-50"
                                  >
                                    {musicSelecting === track.id ? (
                                      <><Loader2 className="w-3 h-3 animate-spin" /> Downloading...</>
                                    ) : (
                                      <><Download className="w-3 h-3" /> Use Track</>
                                    )}
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : musicSearching ? (
                          <div className="flex items-center justify-center py-6 text-zinc-500">
                            <Loader2 className="w-4 h-4 animate-spin mr-2" />
                            <span className="text-[11px]">Searching...</span>
                          </div>
                        ) : (
                          <p className="text-center text-[10px] text-zinc-600 py-4">
                            Search for royalty-free music or use AI Suggest
                          </p>
                        )}
                        <p className="text-[8px] text-zinc-700 text-center">
                          Music provided by Jamendo under Creative Commons licenses
                        </p>
                      </div>
                    )}
                  </div>
                )}

                <div>
                  <label className="block text-[10px] font-medium text-zinc-500 uppercase tracking-wide mb-1.5">
                    Music Volume: {Math.round((project.music_volume || 0.3) * 100)}%
                  </label>
                  <input
                    type="range" min={0} max={1} step={0.05}
                    value={project.music_volume || 0.3}
                    onChange={(e) => updateProjectLocal(p => ({ ...p, music_volume: parseFloat(e.target.value) }))}
                    className="w-full accent-violet-500"
                  />
                </div>
              </div>
            )}

            {/* Renders tab */}
            {sidePanel === 'renders' && (
              <div className="p-3 space-y-3">
                {previewVideoUrl && (
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-[10px] font-medium text-zinc-400 uppercase tracking-wide">Playback</span>
                      <div className="flex items-center gap-1">
                        <a href={previewVideoUrl} download className="flex items-center gap-1 text-[10px] text-zinc-400 hover:text-zinc-200 transition-colors">
                          <Download className="w-3 h-3" /> Download
                        </a>
                        <button onClick={() => setPreviewVideoUrl(null)} className="text-zinc-600 hover:text-zinc-400 transition-colors">
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                    <video key={previewVideoUrl} src={previewVideoUrl} controls autoPlay className="w-full rounded-lg bg-black" />
                  </div>
                )}
                <div>
                  <span className="text-[10px] font-medium text-zinc-500 uppercase tracking-wide">Export History</span>
                  <div className="mt-1.5 space-y-1">
                    {project.render_history.slice().reverse().map((r) => (
                      <button
                        key={r.id}
                        onClick={() => setPreviewVideoUrl(r.output_path)}
                        className={`w-full flex items-center gap-2 text-[11px] px-2.5 py-1.5 rounded-md border transition-colors ${
                          previewVideoUrl === r.output_path
                            ? 'text-violet-300 bg-violet-600/20 border-violet-500/40'
                            : 'text-zinc-400 hover:text-zinc-200 bg-zinc-800/60 hover:bg-zinc-700/60 border-zinc-700/40'
                        }`}
                      >
                        <Play className="w-3 h-3 shrink-0" />
                        <span className="truncate">{new Date(r.rendered_at * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                        <span className="text-zinc-600 ml-auto shrink-0">{r.resolution}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ===== BOTTOM: Timeline ===== */}
      <div className="shrink-0 flex flex-col border-t border-zinc-800" style={{ height: '40%', minHeight: '200px' }}>
        {/* Timeline toolbar */}
        <div className="shrink-0 flex items-center gap-2 bg-zinc-900/80 border-b border-zinc-800/80 px-3 py-1">
          <span className="text-[10px] text-zinc-500">Zoom</span>
          <input type="range" min={0.3} max={3} step={0.1} value={zoom} onChange={(e) => setZoom(parseFloat(e.target.value))} className="w-20 accent-violet-500" />
          <span className="text-[10px] text-zinc-500 tabular-nums w-8">{Math.round(zoom * 100)}%</span>
          <div className="w-px h-3 bg-zinc-800 mx-1" />
          <span className="text-[10px] text-red-400/70 tabular-nums">
            {Math.floor(playheadPos / 60)}:{String(Math.floor(playheadPos % 60)).padStart(2, '0')}.{String(Math.floor((playheadPos % 1) * 10)).padStart(1, '0')}
          </span>
          <div className="w-px h-3 bg-zinc-800 mx-1" />
          <span className="text-[10px] text-zinc-400 capitalize">{project.theme.replace('_', ' ')}</span>
          {project.music_path && (
            <>
              <div className="w-px h-3 bg-zinc-800 mx-1" />
              <span className="text-[10px] text-zinc-500 flex items-center gap-1">
                <Music className="w-3 h-3" /> {project.music_path.split('/').pop()?.slice(0, 15)}
              </span>
            </>
          )}
          <div className="flex-1" />
          {/* Quick add buttons */}
          <button onClick={() => { setMediaBrowserOpen(true); setSidePanel('media') }} className="flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700 border border-zinc-700/50 transition-colors">
            <ImagePlus className="w-3 h-3" /> Media
          </button>
          {[
            { style: 'title', label: 'Title' },
            { style: 'subtitle', label: 'Sub' },
            { style: 'lower_third', label: 'L3rd' },
          ].map(({ style, label }) => (
            <button key={style} onClick={() => addTextElement(style)} className="flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700 border border-zinc-700/50 transition-colors">
              <Type className="w-3 h-3" /> {label}
            </button>
          ))}
        </div>

        {/* Timeline content */}
        {(() => {
          const timelineWidth = Math.max(800, timelineDuration * pixelsPerSecond + 100)
          const hasContent = project.timeline.tracks.length > 0 && (clipCount > 0 || project.timeline.tracks.some(t => t.text_elements.length > 0))
          const tickInterval = zoom < 0.8 ? 5 : zoom < 1.5 ? 2 : 1

          if (!hasContent) {
            return (
              <div className="flex-1 flex flex-col items-center justify-center text-zinc-600 gap-3">
                <Layers className="w-10 h-10 opacity-20" />
                <p className="text-sm font-medium text-zinc-400">Empty Timeline</p>
                <p className="text-xs text-zinc-600 max-w-sm text-center">
                  Write a creative brief and click "AI Arrange", or add media manually.
                </p>
                {isArranging ? (
                  <div className="w-64 space-y-2">
                    <div className="flex items-center gap-2 justify-center">
                      <Loader2 className="w-4 h-4 animate-spin text-violet-400" />
                      <span className="text-xs text-zinc-300">{arrangeJob?.message || 'Starting...'}</span>
                    </div>
                    <div className="h-1.5 w-full bg-zinc-800 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-violet-500 rounded-full transition-all duration-500 ease-out"
                        style={{ width: `${arrangeJob?.progress || 0}%` }}
                      />
                    </div>
                  </div>
                ) : (
                  <div className="flex gap-2">
                    <button onClick={() => { setMediaBrowserOpen(true); setSidePanel('media') }} className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-violet-600/20 text-violet-300 hover:bg-violet-600/30 border border-violet-500/30 transition-colors">
                      <ImagePlus className="w-3.5 h-3.5" /> Add Media
                    </button>
                    {project.prompt && (
                      <button onClick={() => previewMut.mutate()} disabled={previewMut.isPending} className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-300 hover:bg-zinc-700 border border-zinc-700 transition-colors">
                        <Sparkles className="w-3.5 h-3.5" /> AI Arrange
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          }

          return (
            <div className="flex-1 flex min-h-0">
              {/* Fixed track headers */}
              <div className="w-36 shrink-0 flex flex-col">
                <div className="h-6 bg-zinc-900/80 border-r border-zinc-800 border-b border-b-zinc-800/80" />
                <div className="flex-1 overflow-y-hidden">
                  {project.timeline.tracks.map(track => (
                    <TrackHeader key={track.id} track={track} onToggleMute={() => toggleTrackMute(track.id)} onToggleLock={() => toggleTrackLock(track.id)} />
                  ))}
                </div>
              </div>

              {/* Scrollable timeline */}
              <div className="flex-1 overflow-auto min-w-0" ref={timelineScrollRef}>
                <div style={{ width: `${timelineWidth}px` }}>
                  {/* Time ruler */}
                  <div
                    className="relative h-6 bg-zinc-900/60 border-b border-zinc-800/80 sticky top-0 z-10 cursor-pointer"
                    onPointerDown={(e) => {
                      const rect = e.currentTarget.getBoundingClientRect()
                      const updatePos = (clientX: number) => {
                        const x = clientX - rect.left
                        setPlayheadPos(Math.max(0, Math.round(x / pixelsPerSecond * 4) / 4))
                      }
                      updatePos(e.clientX)
                      e.currentTarget.setPointerCapture(e.pointerId)
                      const el = e.currentTarget
                      const onMove = (ev: PointerEvent) => updatePos(ev.clientX)
                      const onUp = () => { el.removeEventListener('pointermove', onMove); el.removeEventListener('pointerup', onUp) }
                      el.addEventListener('pointermove', onMove)
                      el.addEventListener('pointerup', onUp)
                    }}
                  >
                    {Array.from({ length: Math.ceil(timelineDuration) + 1 }).map((_, i) => (
                      <div key={i} className="absolute top-0 bottom-0 flex flex-col items-center" style={{ left: `${i * pixelsPerSecond}px` }}>
                        <div className="w-px h-2 bg-zinc-600" />
                        {i % tickInterval === 0 && (
                          <span className="text-[8px] text-zinc-600 tabular-nums mt-0.5">
                            {Math.floor(i / 60)}:{String(i % 60).padStart(2, '0')}
                          </span>
                        )}
                      </div>
                    ))}
                    <div className="absolute top-0 bottom-0 z-20 pointer-events-none" style={{ left: `${playheadPos * pixelsPerSecond}px` }}>
                      <div className="w-0 h-0 border-l-[5px] border-r-[5px] border-t-[6px] border-l-transparent border-r-transparent border-t-red-500 -translate-x-[5px]" />
                    </div>
                  </div>

                  {/* Track clip areas */}
                  <div className="relative" style={{ minHeight: `${project.timeline.tracks.length * TRACK_HEIGHT}px` }}>
                    {Array.from({ length: Math.ceil(timelineDuration) + 1 }).map((_, i) => (
                      <div key={i} className="absolute top-0 bottom-0 w-px bg-zinc-800/50" style={{ left: `${i * pixelsPerSecond}px` }} />
                    ))}
                    <div className="absolute top-0 bottom-0 w-px bg-red-500 z-20 pointer-events-none" style={{ left: `${playheadPos * pixelsPerSecond}px` }} />
                    {project.timeline.tracks.map(track => (
                      <TrackClips
                        key={track.id}
                        track={track}
                        pixelsPerSecond={pixelsPerSecond}
                        timelineWidth={timelineWidth}
                        selectedClipId={selectedClipId || selectedTextId}
                        onSelectClip={(id) => {
                          const isText = track.text_elements.some(te => te.id === id)
                          if (isText) handleSelectText(id)
                          else handleSelectClip(id)
                        }}
                        onMoveClip={moveClip}
                        onResizeClip={resizeClip}
                      />
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )
        })()}
      </div>

      {/* Bottom status bar */}
      <div className="shrink-0 bg-zinc-900/90 border-t border-zinc-800 px-3 py-1 flex items-center gap-3 text-[9px] text-zinc-600">
        <span><kbd className="px-1 py-0.5 rounded bg-zinc-800/80 text-zinc-500">Space</kbd> Play</span>
        <span><kbd className="px-1 py-0.5 rounded bg-zinc-800/80 text-zinc-500">Del</kbd> Remove</span>
        <span><kbd className="px-1 py-0.5 rounded bg-zinc-800/80 text-zinc-500">Ctrl+Z</kbd> Undo</span>
        <span><kbd className="px-1 py-0.5 rounded bg-zinc-800/80 text-zinc-500">M</kbd> Media</span>
        <span><kbd className="px-1 py-0.5 rounded bg-zinc-800/80 text-zinc-500">Ctrl+S</kbd> Save</span>
      </div>
    </div>
  )
}
