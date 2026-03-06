import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  previewVideo, startGenerate, fetchJob, thumbnailUrl,
  type EDLResponse, type Shot
} from '../api'
import {
  Sparkles, Loader2, Play, Clock, Music, Film, Image,
  Clapperboard, ChevronDown, Eye
} from 'lucide-react'

const THEMES = [
  { value: 'minimal', label: 'Minimal', desc: 'Clean white text, crossfade, Ken Burns' },
  { value: 'warm_nostalgic', label: 'Warm Nostalgic', desc: 'Warm tones, fade-through-black' },
  { value: 'bold_modern', label: 'Bold Modern', desc: 'Large bold text, high contrast' },
]

const roleColors: Record<string, string> = {
  opener: 'bg-amber-500/20 text-amber-300',
  highlight: 'bg-violet-500/20 text-violet-300',
  'b-roll': 'bg-zinc-600/30 text-zinc-300',
  transition: 'bg-blue-500/20 text-blue-300',
  closer: 'bg-emerald-500/20 text-emerald-300',
}

function ShotCard({ shot, index }: { shot: Shot; index: number }) {
  return (
    <div className="flex items-start gap-3 bg-zinc-800/40 border border-zinc-700/40 rounded-lg p-3 hover:border-zinc-600 transition-colors">
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
          <span className="text-[10px] text-zinc-500 ml-auto tabular-nums">{shot.duration.toFixed(1)}s</span>
        </div>
        <p className="text-xs text-zinc-400 line-clamp-2">{shot.reason}</p>
      </div>
    </div>
  )
}

export default function Studio() {
  const [prompt, setPrompt] = useState('')
  const [duration, setDuration] = useState(60)
  const [theme, setTheme] = useState('minimal')
  const [edl, setEdl] = useState<EDLResponse | null>(null)
  const [generatingJobId, setGeneratingJobId] = useState<string | null>(null)

  const previewMut = useMutation({
    mutationFn: () => previewVideo({ prompt, duration }),
    onSuccess: (data) => setEdl(data),
  })

  const generateMut = useMutation({
    mutationFn: () => startGenerate({ prompt, duration, theme }),
    onSuccess: (data) => setGeneratingJobId(data.job_id),
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

  const handlePreview = (e: React.FormEvent) => {
    e.preventDefault()
    if (prompt.trim()) {
      setEdl(null)
      setGeneratingJobId(null)
      previewMut.mutate()
    }
  }

  const isJobDone = job?.status === 'completed'
  const isJobFailed = job?.status === 'failed'

  return (
    <div className="p-8 max-w-5xl mx-auto">
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
            placeholder="Describe the video you want to create... (e.g. 'A warm montage of our summer vacation — beaches, sunsets, and laughter')"
            rows={3}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent resize-none"
          />
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
            <p className="text-[10px] text-zinc-500 mt-1">
              {THEMES.find((t) => t.value === theme)?.desc}
            </p>
          </div>
        </div>

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
      </form>

      {/* EDL Preview */}
      {edl && (
        <div className="space-y-6">
          {/* Header */}
          <div className="bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-5">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-lg font-bold">{edl.title}</h2>
                <p className="text-sm text-zinc-400 mt-1">{edl.narrative_summary}</p>
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
              <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> {edl.estimated_duration.toFixed(0)}s</span>
              <span className="flex items-center gap-1"><Film className="w-3 h-3" /> {edl.shots.length} shots</span>
              <span className="flex items-center gap-1"><Music className="w-3 h-3" /> {edl.music_mood}</span>
            </div>
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
              <p className="text-emerald-300 font-medium mb-3">Video rendered successfully!</p>
              <video
                src={job.output_path}
                controls
                className="w-full rounded-lg max-h-[400px] bg-black"
              />
            </div>
          )}

          {isJobFailed && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4">
              <p className="text-red-300 text-sm">Render failed: {job?.message}</p>
            </div>
          )}

          {/* Shot list */}
          <div>
            <h3 className="text-sm font-semibold text-zinc-300 mb-3">Shot List ({edl.shots.length})</h3>
            <div className="space-y-2">
              {edl.shots.map((shot, i) => (
                <ShotCard key={`${shot.uuid}-${i}`} shot={shot} index={i} />
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!edl && !previewMut.isPending && (
        <div className="text-center py-16 text-zinc-600">
          <Sparkles className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">Enter a creative brief and click Preview Plan</p>
          <p className="text-xs mt-1">The AI director will select shots from your library and create an edit plan</p>
        </div>
      )}
    </div>
  )
}
