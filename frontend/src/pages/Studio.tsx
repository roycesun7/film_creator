import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  previewVideo, startGenerate, startCustomGenerate, fetchJob, thumbnailUrl, uploadMusic,
  type EDLResponse, type Shot, type CustomShotInput
} from '../api'
import {
  Sparkles, Loader2, Clock, Music, Film,
  Clapperboard, ChevronDown, ChevronUp, Eye, X, ArrowUp,
  ArrowDown, Upload, Filter, Download, RotateCcw, Link2
} from 'lucide-react'
import { useToast } from '../components/Toast'

const THEMES = [
  { value: 'minimal', label: 'Minimal', desc: 'Clean white text, crossfade, Ken Burns', transition: 'Crossfade', res: '1920x1080' },
  { value: 'warm_nostalgic', label: 'Warm Nostalgic', desc: 'Warm tones, fade-through-black', transition: 'Fade black', res: '1920x1080' },
  { value: 'bold_modern', label: 'Bold Modern', desc: 'Large bold text, high contrast', transition: 'Slide', res: '1920x1080' },
  { value: 'cinematic', label: 'Cinematic', desc: 'Desaturated warm tones, cinematic feel', transition: 'Crossfade', res: '1920x1080' },
  { value: 'documentary', label: 'Documentary', desc: 'Clean journalistic style, dark navy', transition: 'Fade black', res: '1920x1080' },
  { value: 'social_vertical', label: 'Social (9:16)', desc: 'Vertical format for mobile/social', transition: 'Crossfade', res: '1080x1920' },
]

const roleColors: Record<string, string> = {
  opener: 'bg-amber-500/20 text-amber-300',
  highlight: 'bg-violet-500/20 text-violet-300',
  'b-roll': 'bg-zinc-600/30 text-zinc-300',
  transition: 'bg-blue-500/20 text-blue-300',
  closer: 'bg-emerald-500/20 text-emerald-300',
}

interface ShotCardProps {
  shot: Shot
  index: number
  total: number
  onMoveUp: () => void
  onMoveDown: () => void
  onRemove: () => void
  onDurationChange: (newDuration: number) => void
}

function ShotCard({ shot, index, total, onMoveUp, onMoveDown, onRemove, onDurationChange }: ShotCardProps) {
  const [editingDuration, setEditingDuration] = useState(false)
  const [durationVal, setDurationVal] = useState(shot.duration.toFixed(1))

  return (
    <div className="flex items-start gap-3 bg-zinc-800/40 border border-zinc-700/40 rounded-lg p-3 hover:border-zinc-600 transition-colors group">
      {/* Reorder controls */}
      <div className="flex flex-col gap-0.5 shrink-0 pt-1">
        <button
          onClick={onMoveUp}
          disabled={index === 0}
          className="p-0.5 rounded hover:bg-zinc-700 disabled:opacity-20 disabled:cursor-not-allowed text-zinc-400 hover:text-zinc-200 transition-colors"
          title="Move up"
        >
          <ArrowUp className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={onMoveDown}
          disabled={index === total - 1}
          className="p-0.5 rounded hover:bg-zinc-700 disabled:opacity-20 disabled:cursor-not-allowed text-zinc-400 hover:text-zinc-200 transition-colors"
          title="Move down"
        >
          <ArrowDown className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="w-16 h-16 rounded-md overflow-hidden bg-zinc-800 shrink-0">
        <img
          src={thumbnailUrl(shot.uuid)}
          alt=""
          className="w-full h-full object-cover"
          onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
        />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs font-bold text-zinc-500">#{index + 1}</span>
          <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${roleColors[shot.role] || 'bg-zinc-700 text-zinc-300'}`}>
            {shot.role}
          </span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${
            shot.media_type === 'video' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-blue-500/15 text-blue-400'
          }`}>
            {shot.media_type}
          </span>
          {editingDuration ? (
            <input
              type="number"
              value={durationVal}
              onChange={(e) => setDurationVal(e.target.value)}
              onBlur={() => {
                const val = parseFloat(durationVal)
                if (val > 0 && val <= 30) onDurationChange(val)
                setEditingDuration(false)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const val = parseFloat(durationVal)
                  if (val > 0 && val <= 30) onDurationChange(val)
                  setEditingDuration(false)
                } else if (e.key === 'Escape') {
                  setDurationVal(shot.duration.toFixed(1))
                  setEditingDuration(false)
                }
              }}
              autoFocus
              min={0.5}
              max={30}
              step={0.5}
              className="w-14 text-[10px] text-zinc-300 bg-zinc-700 border border-zinc-600 rounded px-1 py-0.5 text-right tabular-nums focus:outline-none focus:ring-1 focus:ring-violet-500 ml-auto"
            />
          ) : (
            <button
              onClick={() => { setDurationVal(shot.duration.toFixed(1)); setEditingDuration(true) }}
              className="text-[10px] text-zinc-500 ml-auto tabular-nums hover:text-zinc-300 hover:bg-zinc-700/50 px-1 py-0.5 rounded transition-colors"
              title="Click to edit duration"
            >
              {shot.duration.toFixed(1)}s
            </button>
          )}
        </div>
        <p className="text-xs text-zinc-400 line-clamp-2">{shot.reason}</p>
      </div>

      {/* Remove button */}
      <button
        onClick={onRemove}
        className="p-1 rounded hover:bg-red-500/20 text-zinc-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all shrink-0"
        title="Remove shot"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}

export default function Studio() {
  const toast = useToast()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [prompt, setPrompt] = useState('')
  const [duration, setDuration] = useState(60)
  const [theme, setTheme] = useState('minimal')
  const [shots, setShots] = useState<Shot[]>([])
  const [edlMeta, setEdlMeta] = useState<Omit<EDLResponse, 'shots'> | null>(null)
  const [generatingJobId, setGeneratingJobId] = useState<string | null>(null)
  const [edlModified, setEdlModified] = useState(false)
  const [selectedMediaUuids, setSelectedMediaUuids] = useState<string[]>([])

  // Music state
  const [musicPath, setMusicPath] = useState<string | null>(null)
  const [musicFilename, setMusicFilename] = useState<string | null>(null)
  const [musicUploading, setMusicUploading] = useState(false)

  // Advanced filters
  const [showFilters, setShowFilters] = useState(false)
  const [albumsFilter, setAlbumsFilter] = useState('')
  const [personsFilter, setPersonsFilter] = useState('')
  const [minQuality, setMinQuality] = useState<number | ''>('')
  const [numCandidates, setNumCandidates] = useState(30)

  // Pre-fill prompt and selected UUIDs from query params
  useEffect(() => {
    const uuids = searchParams.get('uuids') || searchParams.get('media')
    const searchPrompt = searchParams.get('prompt')
    if (uuids) {
      const uuidList = uuids.split(',').filter(Boolean)
      setSelectedMediaUuids(uuidList)
      if (!prompt && searchPrompt) {
        setPrompt(decodeURIComponent(searchPrompt))
      } else if (!prompt) {
        setPrompt(`Create a highlight video using ${uuidList.length} selected clip${uuidList.length > 1 ? 's' : ''} from my library`)
      }
    }
  }, [searchParams])

  // Computed total duration
  const totalDuration = useMemo(
    () => shots.reduce((sum, s) => sum + s.duration, 0),
    [shots],
  )

  const parseList = (val: string): string[] | undefined => {
    const items = val.split(',').map(s => s.trim()).filter(Boolean)
    return items.length > 0 ? items : undefined
  }

  const previewMut = useMutation({
    mutationFn: () => previewVideo({
      prompt,
      duration,
      albums: parseList(albumsFilter),
      persons: parseList(personsFilter),
      min_quality: minQuality !== '' ? minQuality : undefined,
      num_candidates: numCandidates,
      uuids: selectedMediaUuids.length > 0 ? selectedMediaUuids : undefined,
    }),
    onSuccess: (data) => {
      setShots(data.shots)
      setEdlMeta({
        title: data.title,
        narrative_summary: data.narrative_summary,
        music_mood: data.music_mood,
        estimated_duration: data.estimated_duration,
      })
      setEdlModified(false)
      if (data.shots.length === 0) {
        toast('No suitable shots found. Try a different prompt or add more media.', 'info')
      }
    },
    onError: (err) => toast(err instanceof Error ? err.message : 'Preview failed', 'error'),
  })

  const generateMut = useMutation({
    mutationFn: () => {
      // If the user has modified the shot list, use custom generate
      if (edlModified) {
        const customShots: CustomShotInput[] = shots.map(s => ({
          uuid: s.uuid,
          start_time: s.start_time,
          end_time: s.end_time,
          role: s.role,
          reason: s.reason,
        }))
        return startCustomGenerate({
          shots: customShots,
          title: edlMeta?.title || 'Custom Video',
          theme,
          music_path: musicPath || undefined,
        })
      }
      return startGenerate({
        prompt,
        duration,
        theme,
        music: musicPath || undefined,
        albums: parseList(albumsFilter),
        persons: parseList(personsFilter),
        min_quality: minQuality !== '' ? minQuality : undefined,
        num_candidates: numCandidates,
        uuids: selectedMediaUuids.length > 0 ? selectedMediaUuids : undefined,
      })
    },
    onSuccess: (data) => setGeneratingJobId(data.job_id),
    onError: (err) => toast(err instanceof Error ? err.message : 'Generation failed', 'error'),
  })

  const { data: job } = useQuery({
    queryKey: ['job', generatingJobId],
    queryFn: () => fetchJob(generatingJobId!),
    enabled: !!generatingJobId,
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
      toast('Video rendered successfully!', 'success')
    } else if (job?.status === 'failed') {
      toast('Render failed: ' + (job?.message || 'Unknown error'), 'error')
    }
  }, [job?.status, job?.message, toast])

  const handlePreview = (e: React.FormEvent) => {
    e.preventDefault()
    if (prompt.trim()) {
      setShots([])
      setEdlMeta(null)
      setGeneratingJobId(null)
      setEdlModified(false)
      previewMut.mutate()
    }
  }

  const handleMusicUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setMusicUploading(true)
    try {
      const result = await uploadMusic(file)
      setMusicPath(result.path)
      setMusicFilename(result.filename)
      toast('Music uploaded', 'success')
    } catch (err) {
      console.error('Music upload failed:', err)
      toast('Music upload failed', 'error')
    } finally {
      setMusicUploading(false)
    }
  }

  const clearMusic = () => {
    setMusicPath(null)
    setMusicFilename(null)
  }

  // Shot reordering
  const moveShot = useCallback((fromIndex: number, direction: 'up' | 'down') => {
    const toIndex = direction === 'up' ? fromIndex - 1 : fromIndex + 1
    setShots(prev => {
      const next = [...prev]
      const [moved] = next.splice(fromIndex, 1)
      next.splice(toIndex, 0, moved)
      return next
    })
    setEdlModified(true)
  }, [])

  const removeShot = useCallback((index: number) => {
    setShots(prev => prev.filter((_, i) => i !== index))
    setEdlModified(true)
  }, [])

  const updateShotDuration = useCallback((index: number, newDuration: number) => {
    setShots(prev => prev.map((s, i) => i === index ? { ...s, duration: newDuration } : s))
    setEdlModified(true)
  }, [])

  const isJobDone = job?.status === 'completed'
  const isJobFailed = job?.status === 'failed'
  const hasEdl = edlMeta && shots.length > 0

  return (
    <div className="p-4 sm:p-8 max-w-5xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Studio</h1>
        <p className="text-sm text-zinc-400 mt-1">Describe your video and let AI create it</p>
      </div>

      {/* Prompt form */}
      <form onSubmit={handlePreview} className="mb-8 space-y-4">
        <div>
          <label className="block text-xs font-medium text-zinc-400 mb-2">Creative Brief</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault()
                if (prompt.trim() && !previewMut.isPending) {
                  setShots([])
                  setEdlMeta(null)
                  setGeneratingJobId(null)
                  setEdlModified(false)
                  previewMut.mutate()
                }
              }
            }}
            placeholder="Describe the video you want to create... (e.g. 'A warm montage of our summer vacation — beaches, sunsets, and laughter')"
            rows={3}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent resize-none"
          />
          {selectedMediaUuids.length > 0 && (
            <div className="bg-violet-500/10 border border-violet-500/20 rounded-lg px-3 py-2.5">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2 text-xs text-violet-400">
                  <Film className="w-3.5 h-3.5" />
                  <span>{selectedMediaUuids.length} media item{selectedMediaUuids.length !== 1 ? 's' : ''} pre-selected</span>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedMediaUuids([])}
                  className="text-violet-400/60 hover:text-violet-300 transition-colors text-xs flex items-center gap-1"
                >
                  <X className="w-3 h-3" /> Clear
                </button>
              </div>
              <div className="flex gap-1.5 overflow-x-auto pb-1">
                {selectedMediaUuids.slice(0, 12).map((uuid) => (
                  <div key={uuid} className="w-12 h-12 rounded-md overflow-hidden bg-zinc-800 shrink-0 border border-violet-500/30">
                    <img
                      src={thumbnailUrl(uuid)}
                      alt=""
                      className="w-full h-full object-cover"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                    />
                  </div>
                ))}
                {selectedMediaUuids.length > 12 && (
                  <div className="w-12 h-12 rounded-md bg-zinc-800 shrink-0 border border-zinc-700 flex items-center justify-center text-xs text-zinc-400">
                    +{selectedMediaUuids.length - 12}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="flex gap-4">
          {/* Duration */}
          <div className="flex-1">
            <label className="block text-xs font-medium text-zinc-400 mb-2">Duration (seconds)</label>
            <input
              type="number"
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
              min={10}
              max={300}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>

          {/* Theme */}
          <div className="flex-1">
            <label className="block text-xs font-medium text-zinc-400 mb-2">Theme</label>
            <select
              value={theme}
              onChange={(e) => setTheme(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-1 focus:ring-violet-500"
            >
              {THEMES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
            {(() => {
              const t = THEMES.find((t) => t.value === theme)
              return t ? (
                <p className="text-[10px] text-zinc-500 mt-1">
                  {t.desc} &middot; {t.transition} &middot; {t.res}
                </p>
              ) : null
            })()}
          </div>
        </div>

        {/* Music upload */}
        <div>
          <label className="block text-xs font-medium text-zinc-400 mb-2">Music (optional)</label>
          <div className="flex items-center gap-3">
            {musicFilename ? (
              <div className="flex items-center gap-2 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm">
                <Music className="w-4 h-4 text-violet-400 shrink-0" />
                <span className="text-zinc-200 truncate max-w-[240px]">{musicFilename}</span>
                <button
                  type="button"
                  onClick={clearMusic}
                  className="p-0.5 rounded hover:bg-zinc-700 text-zinc-500 hover:text-zinc-300 transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ) : (
              <label className="flex items-center gap-2 bg-zinc-800 border border-zinc-700 border-dashed rounded-lg px-4 py-2 text-sm text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 cursor-pointer transition-colors">
                {musicUploading ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Uploading...</>
                ) : (
                  <><Upload className="w-4 h-4" /> Choose audio file</>
                )}
                <input
                  type="file"
                  accept="audio/*"
                  onChange={handleMusicUpload}
                  className="hidden"
                  disabled={musicUploading}
                />
              </label>
            )}
          </div>
        </div>

        {/* Advanced Filters (collapsible) */}
        <div className="border border-zinc-700/50 rounded-lg overflow-hidden">
          <button
            type="button"
            onClick={() => setShowFilters(!showFilters)}
            className="w-full flex items-center justify-between px-4 py-2.5 text-xs font-medium text-zinc-400 hover:text-zinc-300 hover:bg-zinc-800/50 transition-colors"
          >
            <span className="flex items-center gap-2">
              <Filter className="w-3.5 h-3.5" />
              Advanced Filters
            </span>
            {showFilters ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>

          {showFilters && (
            <div className="px-4 pb-4 pt-2 border-t border-zinc-700/50 space-y-3">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-[11px] font-medium text-zinc-500 mb-1">Albums (comma-separated)</label>
                  <input
                    type="text"
                    value={albumsFilter}
                    onChange={(e) => setAlbumsFilter(e.target.value)}
                    placeholder="e.g. Vacation, Summer 2024"
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-violet-500"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-zinc-500 mb-1">Persons (comma-separated)</label>
                  <input
                    type="text"
                    value={personsFilter}
                    onChange={(e) => setPersonsFilter(e.target.value)}
                    placeholder="e.g. Alice, Bob"
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-violet-500"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-zinc-500 mb-1">Min quality score (1-10)</label>
                  <input
                    type="number"
                    value={minQuality}
                    onChange={(e) => setMinQuality(e.target.value ? Number(e.target.value) : '')}
                    min={1}
                    max={10}
                    step={0.5}
                    placeholder="Any"
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-violet-500"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-zinc-500 mb-1">Number of candidates</label>
                  <input
                    type="number"
                    value={numCandidates}
                    onChange={(e) => setNumCandidates(Number(e.target.value) || 30)}
                    min={5}
                    max={200}
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-violet-500"
                  />
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={!prompt.trim() || previewMut.isPending}
            className="flex items-center gap-2 bg-zinc-700 hover:bg-zinc-600 disabled:bg-zinc-800 disabled:text-zinc-600 text-white text-sm font-medium px-5 py-2.5 rounded-lg transition-colors"
          >
            {previewMut.isPending ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Planning...</>
            ) : (
              <><Eye className="w-4 h-4" /> Preview Plan</>
            )}
          </button>
          <span className="text-[10px] text-zinc-600 hidden sm:inline">
            <kbd className="bg-zinc-800 px-1 rounded">⌘</kbd>+<kbd className="bg-zinc-800 px-1 rounded">Enter</kbd> to submit
          </span>
        </div>
      </form>

      {/* Planning skeleton */}
      {previewMut.isPending && (
        <div className="space-y-4 animate-pulse">
          <div className="bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-5">
            <div className="h-6 w-48 bg-zinc-700 rounded mb-3" />
            <div className="h-4 w-full bg-zinc-700/60 rounded mb-2" />
            <div className="h-4 w-2/3 bg-zinc-700/60 rounded" />
            <div className="flex gap-4 mt-4">
              <div className="h-3 w-16 bg-zinc-700/40 rounded" />
              <div className="h-3 w-20 bg-zinc-700/40 rounded" />
              <div className="h-3 w-24 bg-zinc-700/40 rounded" />
            </div>
          </div>
          <div className="flex gap-1">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-12 flex-1 bg-zinc-800 rounded" />
            ))}
          </div>
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-20 bg-zinc-800/40 border border-zinc-700/40 rounded-lg" />
            ))}
          </div>
        </div>
      )}

      {/* EDL Preview */}
      {hasEdl && (
        <div className="space-y-6">
          {/* Header */}
          <div className="bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-5">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-lg font-bold">{edlMeta.title}</h2>
                <p className="text-sm text-zinc-400 mt-1">{edlMeta.narrative_summary}</p>
              </div>
              <button
                onClick={() => generateMut.mutate()}
                disabled={generateMut.isPending || !!generatingJobId}
                className="flex items-center gap-2 bg-violet-600 hover:bg-violet-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-semibold px-5 py-2.5 rounded-lg transition-colors shrink-0"
              >
                {(generateMut.isPending || (generatingJobId && !isJobDone && !isJobFailed)) ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Rendering...</>
                ) : (
                  <><Clapperboard className="w-4 h-4" /> Render Video</>
                )}
              </button>
            </div>
            <div className="flex items-center gap-4 mt-3 text-xs text-zinc-500">
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {Math.floor(totalDuration / 60)}:{String(Math.floor(totalDuration % 60)).padStart(2, '0')}
                {edlModified && totalDuration !== edlMeta.estimated_duration && (
                  <span className="text-amber-400 ml-1">
                    (was {Math.floor(edlMeta.estimated_duration / 60)}:{String(Math.floor(edlMeta.estimated_duration % 60)).padStart(2, '0')})
                  </span>
                )}
              </span>
              <span className="flex items-center gap-1">
                <Film className="w-3 h-3" /> {shots.length} shots
                <span className="text-zinc-600 ml-0.5">
                  ({shots.filter(s => s.media_type === 'photo').length} photo, {shots.filter(s => s.media_type === 'video').length} video)
                </span>
              </span>
              <span className="flex items-center gap-1"><Music className="w-3 h-3" /> {musicFilename || edlMeta.music_mood}</span>
              <span className="text-zinc-600">Render: ~{Math.max(1, Math.ceil(totalDuration / 10))} min</span>
            </div>
            {edlModified && (
              <p className="text-[11px] text-amber-400/70 mt-2">
                Shot list has been modified. Render will use your custom arrangement.
              </p>
            )}
          </div>

          {/* Generation progress */}
          {job && (job.status === 'running' || job.status === 'queued') && (
            <div className="bg-violet-500/10 border border-violet-500/30 rounded-xl p-4">
              <div className="flex items-center justify-between text-sm mb-2">
                <span className="text-violet-200">{job.message}</span>
                <span className="text-violet-400">{job.progress}%</span>
              </div>
              <div className="w-full h-2 bg-violet-900/50 rounded-full overflow-hidden">
                <div
                  className="h-full bg-violet-500 rounded-full transition-all duration-700"
                  style={{ width: `${job.progress}%` }}
                />
              </div>
            </div>
          )}

          {/* Completed */}
          {isJobDone && job?.output_path && (
            <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-5">
              <div className="flex items-center justify-between mb-3">
                <p className="text-emerald-300 font-medium">Video rendered successfully!</p>
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
                      navigator.clipboard.writeText(url).then(() => {
                        toast('Video URL copied to clipboard', 'success')
                      }).catch(() => {
                        toast('Failed to copy URL', 'error')
                      })
                    }}
                    className="flex items-center gap-1.5 text-xs font-medium bg-zinc-700/60 text-zinc-300 hover:bg-zinc-700 px-3 py-1.5 rounded-lg transition-colors"
                  >
                    <Link2 className="w-3.5 h-3.5" /> Copy Link
                  </button>
                  <button
                    onClick={() => navigate('/videos')}
                    className="flex items-center gap-1.5 text-xs font-medium bg-emerald-600/20 text-emerald-300 hover:bg-emerald-600/30 px-3 py-1.5 rounded-lg transition-colors"
                  >
                    <Film className="w-3.5 h-3.5" /> View All Videos
                  </button>
                  <button
                    onClick={() => {
                      setGeneratingJobId(null)
                      setShots([])
                      setEdlMeta(null)
                      setEdlModified(false)
                      setPrompt('')
                    }}
                    className="flex items-center gap-1.5 text-xs font-medium bg-violet-600/20 text-violet-300 hover:bg-violet-600/30 px-3 py-1.5 rounded-lg transition-colors"
                  >
                    <RotateCcw className="w-3.5 h-3.5" /> New Video
                  </button>
                </div>
              </div>
              <video
                src={job.output_path}
                controls
                className="w-full rounded-lg max-h-[400px] bg-black"
              />
            </div>
          )}

          {isJobFailed && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 flex items-center justify-between">
              <p className="text-red-300 text-sm">Render failed: {job?.message}</p>
              <button
                onClick={() => { setGeneratingJobId(null); generateMut.mutate() }}
                className="flex items-center gap-1.5 text-xs font-medium bg-red-600/20 text-red-300 hover:bg-red-600/30 px-3 py-1.5 rounded-lg transition-colors shrink-0"
              >
                <RotateCcw className="w-3.5 h-3.5" /> Retry
              </button>
            </div>
          )}

          {/* Storyboard strip */}
          <div className="bg-zinc-800/30 border border-zinc-700/40 rounded-xl p-4">
            <p className="text-[11px] font-medium text-zinc-500 mb-3 uppercase tracking-wide">Storyboard</p>
            <div className="flex gap-1 overflow-x-auto pb-2">
              {shots.map((shot, i) => (
                <div
                  key={`strip-${shot.uuid}-${i}`}
                  className="shrink-0 relative"
                  style={{ width: `${Math.max(48, Math.min(120, shot.duration * 16))}px` }}
                  title={`#${i + 1} ${shot.role} — ${shot.duration.toFixed(1)}s`}
                >
                  <div className="aspect-[16/10] rounded overflow-hidden bg-zinc-800 border border-zinc-700/50">
                    <img
                      src={thumbnailUrl(shot.uuid)}
                      alt=""
                      className="w-full h-full object-cover"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                    />
                  </div>
                  <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent px-1 py-0.5 rounded-b">
                    <span className="text-[8px] text-zinc-300 font-medium">{shot.duration.toFixed(1)}s</span>
                  </div>
                  <div className={`absolute top-0.5 left-0.5 text-[7px] font-bold uppercase px-1 rounded ${roleColors[shot.role] || 'bg-zinc-700 text-zinc-300'}`}>
                    {shot.role.slice(0, 3)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Shot list */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-zinc-300">
                Shot List ({shots.length})
                <span className="text-zinc-500 font-normal ml-2">
                  {totalDuration.toFixed(1)}s total
                </span>
              </h3>
              {edlModified && (
                <button
                  onClick={() => {
                    if (previewMut.data) {
                      setShots(previewMut.data.shots)
                      setEdlModified(false)
                    }
                  }}
                  className="text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors"
                >
                  Reset to original
                </button>
              )}
            </div>
            <div className="space-y-2">
              {shots.map((shot, i) => (
                <ShotCard
                  key={`${shot.uuid}-${i}`}
                  shot={shot}
                  index={i}
                  total={shots.length}
                  onMoveUp={() => moveShot(i, 'up')}
                  onMoveDown={() => moveShot(i, 'down')}
                  onRemove={() => removeShot(i)}
                  onDurationChange={(d) => updateShotDuration(i, d)}
                />
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!hasEdl && !previewMut.isPending && (
        <div className="text-center py-16 text-zinc-600">
          <Sparkles className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">Enter a creative brief and click Preview Plan</p>
          <p className="text-xs mt-1">The AI director will select shots from your library and create an edit plan</p>
        </div>
      )}
    </div>
  )
}
