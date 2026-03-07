import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchProject, updateProject, projectPreview, projectRender,
  fetchJob, thumbnailUrl, searchMedia, fetchMedia, uploadMusic,
  type ProjectData, type TimelineClip, type TimelineTrack, type TextElement,
  type MediaItem
} from '../api'
import {
  Loader2, Play, Save, Sparkles, Clapperboard, Film, Music, Type,
  Plus, Trash2, GripVertical, X, ChevronLeft, Clock, Eye,
  Volume2, VolumeX, Lock, Unlock, ArrowUp, ArrowDown, Download,
  Settings, Layers, RotateCcw, Upload, Link2, Search, ImagePlus,
  FolderOpen, GripHorizontal
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
  trackType,
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
    <div className="w-72 bg-zinc-900 border-l border-zinc-800 p-4 overflow-y-auto">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-zinc-200">Clip Properties</h3>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">
          <X className="w-4 h-4" />
        </button>
      </div>

      {clip.media_uuid && (
        <div className="mb-4 aspect-video bg-black rounded-lg overflow-hidden">
          <img
            src={thumbnailUrl(clip.media_uuid)}
            alt=""
            className="w-full h-full object-cover"
          />
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
    <div className="w-72 bg-zinc-900 border-l border-zinc-800 p-4 overflow-y-auto">
      <div className="flex items-center justify-between mb-4">
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
    <div className="w-72 bg-zinc-900 border-l border-zinc-800 flex flex-col h-full">
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
  const [zoom, setZoom] = useState(1.0)
  const [mediaBrowserOpen, setMediaBrowserOpen] = useState(false)
  const [undoStack, setUndoStack] = useState<ProjectData[]>([])
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [playheadPos, setPlayheadPos] = useState(0)
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
    mutationFn: () => projectPreview(projectId!),
    onSuccess: (data) => {
      setProject(data)
      setDirty(false)
      toast(`AI generated ${data.timeline.tracks[0]?.clips.length || 0} shots`, 'success')
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    },
    onError: (err) => toast(err instanceof Error ? err.message : 'Preview failed', 'error'),
  })

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
    const videoTrack = project.timeline.tracks.find(t => t.type === 'video')
    if (!videoTrack) return

    // Place at the end of existing clips
    let endPos = 0
    for (const c of videoTrack.clips) {
      const cEnd = c.position + c.duration
      if (cEnd > endPos) endPos = cEnd
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

    updateProjectLocal(p => ({
      ...p,
      timeline: {
        ...p.timeline,
        tracks: p.timeline.tracks.map(t =>
          t.id === videoTrack.id ? { ...t, clips: [...t.clips, newClip] } : t
        ),
        duration: Math.max(p.timeline.duration, endPos + clipDuration),
      },
    }))
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

      if (e.key === 'Escape') {
        setSelectedClipId(null)
        setSelectedTextId(null)
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
    <div className="flex flex-col h-full">
      {/* Top bar */}
      <div className="shrink-0 bg-zinc-900/90 border-b border-zinc-800 px-4 py-2.5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/projects')}
            className="p-1 rounded-lg hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>
          <div>
            <input
              type="text"
              value={project.name}
              onChange={(e) => updateProjectLocal(p => ({ ...p, name: e.target.value }))}
              className="bg-transparent text-sm font-semibold text-zinc-100 focus:outline-none border-b border-transparent focus:border-violet-500 transition-colors"
            />
            <div className="flex items-center gap-3 text-[10px] text-zinc-500 mt-0.5">
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {timelineDuration > 0 ? `${Math.floor(timelineDuration / 60)}:${String(Math.floor(timelineDuration % 60)).padStart(2, '0')}` : '0:00'}
              </span>
              <span>{clipCount} clips</span>
              <span>{project.timeline.tracks.length} tracks</span>
              {dirty && <span className="text-amber-400">Unsaved changes</span>}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={undo}
            disabled={undoStack.length === 0}
            className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 disabled:opacity-20 transition-colors"
            title="Undo (Ctrl+Z)"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
          <div className="w-px h-5 bg-zinc-800 mx-0.5" />
          <button
            onClick={() => saveMut.mutate()}
            disabled={!dirty || saveMut.isPending}
            className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-300 hover:bg-zinc-700 disabled:opacity-30 transition-colors border border-zinc-700"
            title="Save (Ctrl+S)"
          >
            {saveMut.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Save
          </button>
          <button
            onClick={() => setMediaBrowserOpen(!mediaBrowserOpen)}
            className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg transition-colors border ${
              mediaBrowserOpen
                ? 'bg-violet-600/20 text-violet-300 border-violet-500/40'
                : 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700 border-zinc-700'
            }`}
            title="Browse and add media (M)"
          >
            <ImagePlus className="w-3.5 h-3.5" />
            Media
          </button>
          <button
            onClick={() => previewMut.mutate()}
            disabled={!project.prompt || previewMut.isPending}
            className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-300 hover:bg-zinc-700 disabled:opacity-30 transition-colors border border-zinc-700"
            title="AI will select and arrange clips based on your creative brief"
          >
            {previewMut.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
            AI Arrange
          </button>
          <button
            onClick={() => setSettingsOpen(!settingsOpen)}
            className={`p-1.5 rounded-lg transition-colors ${settingsOpen ? 'bg-zinc-700 text-zinc-200' : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800'}`}
            title="Project settings"
          >
            <Settings className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => renderMut.mutate()}
            disabled={clipCount === 0 || renderMut.isPending || !!isJobRunning}
            className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-30 transition-colors"
          >
            {(renderMut.isPending || isJobRunning) ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Clapperboard className="w-3.5 h-3.5" />}
            Render
          </button>
        </div>
      </div>

      {/* Creative brief */}
      <div className="shrink-0 bg-zinc-900/50 border-b border-zinc-800 px-4 py-3">
        <label className="block text-[10px] font-medium text-zinc-500 uppercase tracking-wide mb-1.5">Creative Brief</label>
        <textarea
          value={project.prompt}
          onChange={(e) => updateProjectLocal(p => ({ ...p, prompt: e.target.value }))}
          placeholder="Describe what this video should be about... (e.g. 'A warm montage of our summer vacation — beaches, sunsets, and laughter')"
          rows={2}
          className="w-full bg-zinc-800/50 border border-zinc-700/50 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none"
        />
        {project.narrative_summary && (
          <p className="text-[11px] text-zinc-500 mt-1.5 italic">{project.narrative_summary}</p>
        )}
      </div>

      {/* Settings panel (collapsible) */}
      {settingsOpen && (
        <div className="shrink-0 bg-zinc-900/50 border-b border-zinc-800 px-4 py-3">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {/* Theme */}
            <div>
              <label className="block text-[10px] font-medium text-zinc-500 uppercase tracking-wide mb-1.5">Theme</label>
              <div className="grid grid-cols-3 gap-1">
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

            {/* Music */}
            <div>
              <label className="block text-[10px] font-medium text-zinc-500 uppercase tracking-wide mb-1.5">Background Music</label>
              {project.music_path ? (
                <div className="flex items-center gap-2">
                  <div className="flex-1 bg-zinc-800/50 border border-zinc-700/40 rounded-md px-2.5 py-1.5 text-xs text-zinc-300 truncate">
                    <Music className="w-3 h-3 inline mr-1.5 text-zinc-500" />
                    {project.music_path.split('/').pop()}
                  </div>
                  <button
                    onClick={() => updateProjectLocal(p => ({ ...p, music_path: '' }))}
                    className="p-1 text-zinc-500 hover:text-red-400 transition-colors"
                    title="Remove music"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ) : (
                <label className="flex items-center gap-1.5 text-xs font-medium px-3 py-2 rounded-md bg-zinc-800/60 border border-zinc-700/40 text-zinc-400 hover:text-zinc-200 hover:border-zinc-600 cursor-pointer transition-colors">
                  <Upload className="w-3.5 h-3.5" /> Upload Music
                  <input
                    type="file"
                    accept=".mp3,.wav,.aac,.m4a,.ogg,.flac"
                    className="hidden"
                    onChange={async (e) => {
                      const file = e.target.files?.[0]
                      if (!file) return
                      try {
                        const result = await uploadMusic(file)
                        updateProjectLocal(p => ({ ...p, music_path: result.path }))
                        toast(`Music uploaded: ${result.filename}`, 'success')
                      } catch (err) {
                        toast(err instanceof Error ? err.message : 'Upload failed', 'error')
                      }
                    }}
                  />
                </label>
              )}
            </div>

            {/* Music Volume */}
            <div>
              <label className="block text-[10px] font-medium text-zinc-500 uppercase tracking-wide mb-1.5">
                Music Volume: {Math.round((project.music_volume || 0.3) * 100)}%
              </label>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={project.music_volume || 0.3}
                onChange={(e) => updateProjectLocal(p => ({ ...p, music_volume: parseFloat(e.target.value) }))}
                className="w-full accent-violet-500"
              />
            </div>
          </div>
        </div>
      )}

      {/* Render progress */}
      {isJobRunning && job && (
        <div className="shrink-0 bg-violet-500/10 border-b border-violet-500/30 px-4 py-2.5">
          <div className="flex items-center justify-between text-xs mb-1.5">
            <span className="text-violet-200">{job.message}</span>
            <span className="text-violet-400 tabular-nums">{job.progress}%</span>
          </div>
          <div className="w-full h-1.5 bg-violet-900/50 rounded-full overflow-hidden">
            <div
              className="h-full bg-violet-500 rounded-full transition-all duration-700"
              style={{ width: `${job.progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Render complete */}
      {isJobDone && job?.output_path && (
        <div className="shrink-0 bg-emerald-500/10 border-b border-emerald-500/30 px-4 py-3 flex items-center justify-between">
          <p className="text-sm text-emerald-300 font-medium">Video rendered!</p>
          <div className="flex items-center gap-2">
            <a
              href={job.output_path}
              download
              className="flex items-center gap-1.5 text-xs font-medium bg-zinc-700/60 text-zinc-300 hover:bg-zinc-700 px-3 py-1.5 rounded-lg transition-colors"
            >
              <Download className="w-3.5 h-3.5" /> Download
            </a>
            <button
              onClick={() => {
                const url = window.location.origin + job.output_path
                navigator.clipboard.writeText(url).then(() => toast('URL copied', 'success'))
              }}
              className="flex items-center gap-1.5 text-xs font-medium bg-zinc-700/60 text-zinc-300 hover:bg-zinc-700 px-3 py-1.5 rounded-lg transition-colors"
            >
              <Link2 className="w-3.5 h-3.5" /> Copy Link
            </button>
            <button
              onClick={() => navigate('/videos')}
              className="flex items-center gap-1.5 text-xs font-medium bg-emerald-600/20 text-emerald-300 hover:bg-emerald-600/30 px-3 py-1.5 rounded-lg transition-colors"
            >
              <Film className="w-3.5 h-3.5" /> View Videos
            </button>
          </div>
        </div>
      )}

      {/* Main content: Timeline + Inspector */}
      <div className="flex flex-1 min-h-0">
        <div className="flex-1 flex flex-col min-w-0">
          {/* Zoom controls + timeline info */}
          <div className="shrink-0 flex items-center gap-2 bg-zinc-900/60 border-b border-zinc-800/80 px-4 py-1.5">
            <span className="text-[10px] text-zinc-500">Zoom</span>
            <input
              type="range"
              min={0.3}
              max={3}
              step={0.1}
              value={zoom}
              onChange={(e) => setZoom(parseFloat(e.target.value))}
              className="w-24 accent-violet-500"
            />
            <span className="text-[10px] text-zinc-500 tabular-nums w-8">{Math.round(zoom * 100)}%</span>
            <div className="w-px h-4 bg-zinc-800 mx-1" />
            <span className="text-[10px] text-zinc-400 capitalize">{project.theme.replace('_', ' ')}</span>
            <div className="w-px h-4 bg-zinc-800 mx-1" />
            <span className="text-[10px] text-red-400/70 tabular-nums">
              {Math.floor(playheadPos / 60)}:{String(Math.floor(playheadPos % 60)).padStart(2, '0')}.{String(Math.floor((playheadPos % 1) * 10)).padStart(1, '0')}
            </span>
            {project.music_path && (
              <>
                <div className="w-px h-4 bg-zinc-800 mx-1" />
                <span className="text-[10px] text-zinc-500 flex items-center gap-1">
                  <Music className="w-3 h-3" /> {project.music_path.split('/').pop()?.slice(0, 20)}
                </span>
              </>
            )}
            <div className="flex-1" />
            {selectedClipId && selectedClip && (
              <span className="text-[10px] text-violet-400 tabular-nums">
                Selected: {selectedClip.role} @ {selectedClip.position.toFixed(1)}s
              </span>
            )}
            {selectedTextId && selectedText && (
              <span className="text-[10px] text-indigo-400">
                Selected: "{selectedText.text.slice(0, 20)}"
              </span>
            )}
          </div>

          {/* Timeline with synchronized scrolling */}
          {(() => {
            const timelineWidth = Math.max(800, timelineDuration * pixelsPerSecond + 100)
            const hasContent = project.timeline.tracks.length > 0 && (clipCount > 0 || project.timeline.tracks.some(t => t.text_elements.length > 0))
            const tickInterval = zoom < 0.8 ? 5 : zoom < 1.5 ? 2 : 1

            if (!hasContent) {
              return (
                <div className="flex-1 flex flex-col items-center justify-center text-zinc-600 gap-4 px-8">
                  <Layers className="w-12 h-12 opacity-20" />
                  <div className="text-center">
                    <p className="text-sm font-medium text-zinc-400 mb-1">Empty Timeline</p>
                    <p className="text-xs text-zinc-600 max-w-md">
                      Write a creative brief and click "AI Arrange" to auto-generate a video, or open the Media Browser to manually add clips.
                    </p>
                  </div>
                  <div className="flex gap-3 mt-2">
                    <button
                      onClick={() => setMediaBrowserOpen(true)}
                      className="flex items-center gap-1.5 text-xs font-medium px-4 py-2 rounded-lg bg-violet-600/20 text-violet-300 hover:bg-violet-600/30 border border-violet-500/30 transition-colors"
                    >
                      <ImagePlus className="w-3.5 h-3.5" /> Open Media Browser
                    </button>
                    {project.prompt && (
                      <button
                        onClick={() => previewMut.mutate()}
                        disabled={previewMut.isPending}
                        className="flex items-center gap-1.5 text-xs font-medium px-4 py-2 rounded-lg bg-zinc-800 text-zinc-300 hover:bg-zinc-700 border border-zinc-700 transition-colors"
                      >
                        <Sparkles className="w-3.5 h-3.5" /> AI Arrange
                      </button>
                    )}
                  </div>
                  <p className="text-[10px] text-zinc-700 mt-1">Press <kbd className="px-1 py-0.5 rounded bg-zinc-800 text-zinc-500 text-[9px]">M</kbd> to toggle Media Browser</p>
                </div>
              )
            }

            return (
              <div className="flex-1 flex min-h-0">
                {/* Fixed track headers column */}
                <div className="w-40 shrink-0 flex flex-col">
                  {/* Ruler spacer */}
                  <div className="h-6 bg-zinc-900/80 border-r border-zinc-800 border-b border-b-zinc-800/80" />
                  {/* Track headers */}
                  <div className="flex-1 overflow-y-hidden">
                    {project.timeline.tracks.map(track => (
                      <TrackHeader
                        key={track.id}
                        track={track}
                        onToggleMute={() => toggleTrackMute(track.id)}
                        onToggleLock={() => toggleTrackLock(track.id)}
                      />
                    ))}
                  </div>
                </div>

                {/* Scrollable timeline content (ruler + all track clips) */}
                <div className="flex-1 overflow-auto min-w-0" ref={timelineScrollRef}>
                  <div style={{ width: `${timelineWidth}px` }}>
                    {/* Time ruler — click or drag to scrub */}
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
                        const onUp = () => {
                          el.removeEventListener('pointermove', onMove)
                          el.removeEventListener('pointerup', onUp)
                        }
                        el.addEventListener('pointermove', onMove)
                        el.addEventListener('pointerup', onUp)
                      }}
                    >
                      {Array.from({ length: Math.ceil(timelineDuration) + 1 }).map((_, i) => (
                        <div
                          key={i}
                          className="absolute top-0 bottom-0 flex flex-col items-center"
                          style={{ left: `${i * pixelsPerSecond}px` }}
                        >
                          <div className="w-px h-2 bg-zinc-600" />
                          {i % tickInterval === 0 && (
                            <span className="text-[8px] text-zinc-600 tabular-nums mt-0.5">
                              {Math.floor(i / 60)}:{String(i % 60).padStart(2, '0')}
                            </span>
                          )}
                        </div>
                      ))}
                      {/* Playhead marker on ruler */}
                      <div
                        className="absolute top-0 bottom-0 z-20 pointer-events-none"
                        style={{ left: `${playheadPos * pixelsPerSecond}px` }}
                      >
                        <div className="w-0 h-0 border-l-[5px] border-r-[5px] border-t-[6px] border-l-transparent border-r-transparent border-t-red-500 -translate-x-[5px]" />
                      </div>
                    </div>

                    {/* Track clip areas + playhead line */}
                    <div className="relative" style={{ minHeight: `${project.timeline.tracks.length * TRACK_HEIGHT}px` }}>
                      {/* Grid lines spanning all tracks */}
                      {Array.from({ length: Math.ceil(timelineDuration) + 1 }).map((_, i) => (
                        <div
                          key={i}
                          className="absolute top-0 bottom-0 w-px bg-zinc-800/50"
                          style={{ left: `${i * pixelsPerSecond}px` }}
                        />
                      ))}

                      {/* Playhead line */}
                      <div
                        className="absolute top-0 bottom-0 w-px bg-red-500 z-20 pointer-events-none"
                        style={{ left: `${playheadPos * pixelsPerSecond}px` }}
                      />

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

          {/* Storyboard strip (below timeline) */}
          {clipCount > 0 && (
            <div className="shrink-0 bg-zinc-900/80 border-t border-zinc-800 px-4 py-2.5">
              <p className="text-[10px] text-zinc-500 uppercase tracking-wide mb-2">Storyboard</p>
              <div className="flex gap-1 overflow-x-auto pb-1">
                {videoTrack?.clips.map((clip, i) => (
                  <button
                    key={clip.id}
                    onClick={() => setSelectedClipId(clip.id)}
                    className={`shrink-0 rounded overflow-hidden border transition-all ${
                      selectedClipId === clip.id
                        ? 'border-violet-500 ring-1 ring-violet-500/30'
                        : 'border-zinc-700/50 hover:border-zinc-600'
                    }`}
                    style={{ width: `${Math.max(48, Math.min(100, clip.duration * 14))}px` }}
                    title={`#${i + 1} ${clip.role} — ${clip.duration.toFixed(1)}s`}
                  >
                    <div className="aspect-[16/10] bg-zinc-800 relative">
                      <img
                        src={thumbnailUrl(clip.media_uuid)}
                        alt=""
                        className="w-full h-full object-cover"
                        onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                      />
                      <div className="absolute bottom-0 inset-x-0 bg-black/70 px-0.5 py-px">
                        <span className="text-[7px] text-zinc-300">{clip.duration.toFixed(1)}s</span>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Inspector panel */}
        {selectedClip && (
          <ClipInspector
            clip={selectedClip}
            onUpdate={(updates) => updateClip(selectedClip.id, updates)}
            onRemove={() => removeClip(selectedClip.id)}
            onClose={() => setSelectedClipId(null)}
          />
        )}
        {selectedText && (
          <TextElementInspector
            element={selectedText}
            onUpdate={(updates) => updateTextElement(selectedText.id, updates)}
            onRemove={() => removeTextElement(selectedText.id)}
            onClose={() => setSelectedTextId(null)}
          />
        )}

        {/* Media Browser panel */}
        {mediaBrowserOpen && (
          <MediaBrowser
            onAddClip={addClipFromMedia}
            onClose={() => setMediaBrowserOpen(false)}
          />
        )}
      </div>

      {/* Bottom toolbar */}
      <div className="shrink-0 bg-zinc-900/90 border-t border-zinc-800 px-4 py-2 flex items-center gap-3">
        {/* Text elements */}
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-zinc-500 uppercase tracking-wide">Text:</span>
          {[
            { style: 'title', label: 'Title' },
            { style: 'subtitle', label: 'Subtitle' },
            { style: 'caption', label: 'Caption' },
            { style: 'lower_third', label: 'Lower Third' },
          ].map(({ style, label }) => (
            <button
              key={style}
              onClick={() => addTextElement(style)}
              className="flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded-md bg-zinc-800 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700 border border-zinc-700/50 transition-colors"
            >
              <Type className="w-3 h-3" />
              {label}
            </button>
          ))}
        </div>

        <div className="w-px h-5 bg-zinc-800" />

        {/* Quick actions */}
        <button
          onClick={() => setMediaBrowserOpen(true)}
          className="flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded-md bg-zinc-800 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700 border border-zinc-700/50 transition-colors"
        >
          <ImagePlus className="w-3 h-3" /> Add Media
        </button>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Keyboard hints */}
        <div className="flex items-center gap-3 text-[9px] text-zinc-600">
          <span><kbd className="px-1 py-0.5 rounded bg-zinc-800/80 text-zinc-500">Del</kbd> Remove</span>
          <span><kbd className="px-1 py-0.5 rounded bg-zinc-800/80 text-zinc-500">Esc</kbd> Deselect</span>
          <span><kbd className="px-1 py-0.5 rounded bg-zinc-800/80 text-zinc-500">Ctrl+Z</kbd> Undo</span>
          <span><kbd className="px-1 py-0.5 rounded bg-zinc-800/80 text-zinc-500">M</kbd> Media</span>
        </div>
      </div>
    </div>
  )
}
