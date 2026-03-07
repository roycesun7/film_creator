import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { fetchStats, fetchJobs, fetchVideos, type Job } from '../api'
import {
  Image, Film, Cpu, BarChart3, Users, FolderOpen,
  Loader2, AlertCircle, Upload, Search, Clapperboard, Play, ArrowRight
} from 'lucide-react'

function StatCard({ icon: Icon, label, value, sub, color }: {
  icon: any; label: string; value: string | number; sub?: string; color: string
}) {
  return (
    <div className="bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-5">
      <div className="flex items-center gap-3 mb-3">
        <div className={`p-2 rounded-lg ${color}`}>
          <Icon className="w-4 h-4" />
        </div>
        <span className="text-sm text-zinc-400">{label}</span>
      </div>
      <p className="text-2xl font-bold">{value}</p>
      {sub && <p className="text-xs text-zinc-500 mt-1">{sub}</p>}
    </div>
  )
}

function JobBadge({ job }: { job: Job }) {
  const colors = {
    queued: 'bg-yellow-500/20 text-yellow-300',
    running: 'bg-blue-500/20 text-blue-300',
    completed: 'bg-green-500/20 text-green-300',
    failed: 'bg-red-500/20 text-red-300',
  }
  return (
    <div className="flex items-center justify-between bg-zinc-800/50 border border-zinc-700/40 rounded-lg px-4 py-3">
      <div>
        <span className="text-sm font-medium">{job.type}</span>
        <p className="text-xs text-zinc-400 mt-0.5">{job.message}</p>
      </div>
      <div className="flex items-center gap-3">
        {job.status === 'running' && (
          <div className="w-24 h-1.5 bg-zinc-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-violet-500 rounded-full transition-all duration-500"
              style={{ width: `${job.progress}%` }}
            />
          </div>
        )}
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${colors[job.status]}`}>
          {job.status}
        </span>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const { data: stats, isLoading, error, refetch } = useQuery({
    queryKey: ['stats'],
    queryFn: fetchStats,
    refetchInterval: 5000,
  })
  const { data: jobsData } = useQuery({
    queryKey: ['jobs'],
    queryFn: fetchJobs,
    refetchInterval: 3000,
  })
  const { data: videosData } = useQuery({
    queryKey: ['videos'],
    queryFn: fetchVideos,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-500" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-zinc-400">
        <AlertCircle className="w-8 h-8 text-red-400" />
        <p className="text-sm">Failed to load stats. Is the API server running?</p>
        <code className="text-xs bg-zinc-800 px-3 py-1.5 rounded">uvicorn api:app --reload</code>
        <button
          onClick={() => refetch()}
          className="mt-3 text-xs text-violet-400 hover:text-violet-300 underline"
        >
          Retry
        </button>
      </div>
    )
  }

  const s = stats!
  const jobs = jobsData?.jobs || []
  const recentJobs = jobs.slice().sort((a, b) => b.created_at - a.created_at).slice(0, 5)
  const recentVideos = videosData?.videos?.slice(0, 3) || []

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-sm text-zinc-400 mt-1">Your media library at a glance</p>
        </div>
        {s.total > 0 && (
          <button
            onClick={() => navigate('/studio')}
            className="flex items-center gap-2 bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            <Clapperboard className="w-4 h-4" /> Create Video
          </button>
        )}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard icon={BarChart3} label="Total Indexed" value={s.total} color="bg-violet-500/20 text-violet-300" />
        <StatCard icon={Image} label="Photos" value={s.photos} color="bg-blue-500/20 text-blue-300" />
        <StatCard icon={Film} label="Videos" value={s.videos} color="bg-emerald-500/20 text-emerald-300" />
        <StatCard icon={Cpu} label="With Embeddings" value={s.with_embeddings} sub={s.total > 0 ? `${Math.round((s.with_embeddings / s.total) * 100)}% coverage` : undefined} color="bg-orange-500/20 text-orange-300" />
      </div>

      {/* Embedding progress bar */}
      {s.total > 0 && s.with_embeddings < s.total && (
        <div className="mb-8 bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-5">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-zinc-300">Embedding Progress</span>
            <span className="text-sm text-zinc-400">{s.with_embeddings} / {s.total}</span>
          </div>
          <div className="w-full h-2 bg-zinc-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-violet-600 to-violet-400 rounded-full transition-all duration-700"
              style={{ width: `${Math.round((s.with_embeddings / s.total) * 100)}%` }}
            />
          </div>
          <p className="text-xs text-zinc-500 mt-2">
            {s.total - s.with_embeddings} items still need embeddings for semantic search
          </p>
        </div>
      )}

      {/* Quick actions */}
      {s.total > 0 && (
        <div className="grid grid-cols-3 gap-3 mb-8">
          <button
            onClick={() => navigate('/library')}
            className="flex items-center gap-3 bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-4 hover:border-zinc-600 transition-colors text-left group"
          >
            <div className="p-2 rounded-lg bg-blue-500/20">
              <Upload className="w-4 h-4 text-blue-300" />
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium text-zinc-200">Upload Media</p>
              <p className="text-xs text-zinc-500">Add photos & videos</p>
            </div>
            <ArrowRight className="w-4 h-4 text-zinc-600 group-hover:text-zinc-400 transition-colors" />
          </button>
          <button
            onClick={() => navigate('/search')}
            className="flex items-center gap-3 bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-4 hover:border-zinc-600 transition-colors text-left group"
          >
            <div className="p-2 rounded-lg bg-amber-500/20">
              <Search className="w-4 h-4 text-amber-300" />
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium text-zinc-200">Search Library</p>
              <p className="text-xs text-zinc-500">Find by description</p>
            </div>
            <ArrowRight className="w-4 h-4 text-zinc-600 group-hover:text-zinc-400 transition-colors" />
          </button>
          <button
            onClick={() => navigate('/studio')}
            className="flex items-center gap-3 bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-4 hover:border-zinc-600 transition-colors text-left group"
          >
            <div className="p-2 rounded-lg bg-violet-500/20">
              <Clapperboard className="w-4 h-4 text-violet-300" />
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium text-zinc-200">Create Video</p>
              <p className="text-xs text-zinc-500">AI-directed editing</p>
            </div>
            <ArrowRight className="w-4 h-4 text-zinc-600 group-hover:text-zinc-400 transition-colors" />
          </button>
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        {/* Date range & quality */}
        <div className="bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-zinc-300 mb-4">Library Info</h2>
          <div className="space-y-3 text-sm">
            {s.date_range && (
              <div className="flex justify-between">
                <span className="text-zinc-400">Date range</span>
                <span>{s.date_range.earliest?.slice(0, 10)} — {s.date_range.latest?.slice(0, 10)}</span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-zinc-400">With descriptions</span>
              <span>{s.with_descriptions}</span>
            </div>
            {s.avg_quality !== null && (
              <div className="flex justify-between">
                <span className="text-zinc-400">Avg quality score</span>
                <span>{s.avg_quality}</span>
              </div>
            )}
          </div>
        </div>

        {/* Top albums */}
        {s.top_albums.length > 0 && (
          <div className="bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-zinc-300 mb-4 flex items-center gap-2">
              <FolderOpen className="w-4 h-4" /> Top Albums
            </h2>
            <div className="space-y-2">
              {s.top_albums.map((a) => (
                <div key={a.name} className="flex justify-between text-sm">
                  <span className="text-zinc-300 truncate">{a.name}</span>
                  <span className="text-zinc-500 tabular-nums">{a.count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Top persons */}
        {s.top_persons.length > 0 && (
          <div className="bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-zinc-300 mb-4 flex items-center gap-2">
              <Users className="w-4 h-4" /> Top People
            </h2>
            <div className="space-y-2">
              {s.top_persons.map((p) => (
                <div key={p.name} className="flex justify-between text-sm">
                  <span className="text-zinc-300 truncate">{p.name}</span>
                  <span className="text-zinc-500 tabular-nums">{p.count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Recent jobs */}
        {recentJobs.length > 0 && (
          <div className="bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-zinc-300 mb-4">Recent Jobs</h2>
            <div className="space-y-2">
              {recentJobs.map((j) => <JobBadge key={j.id} job={j} />)}
            </div>
          </div>
        )}

        {/* Recent videos */}
        {recentVideos.length > 0 && (
          <div className="bg-zinc-800/50 border border-zinc-700/50 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-zinc-300 mb-4 flex items-center gap-2">
              <Play className="w-4 h-4" /> Recent Videos
            </h2>
            <div className="space-y-2">
              {recentVideos.map((v) => (
                <button
                  key={v.filename}
                  onClick={() => navigate('/videos')}
                  className="w-full flex items-center gap-3 p-2.5 rounded-lg hover:bg-zinc-700/30 transition-colors text-left"
                >
                  <div className="p-1.5 rounded bg-zinc-700/50">
                    <Film className="w-3.5 h-3.5 text-zinc-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-zinc-300 truncate">{v.filename.replace('.mp4', '').replace(/_/g, ' ')}</p>
                    <p className="text-[10px] text-zinc-500">{v.size_mb} MB</p>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {s.total === 0 && (
        <div className="mt-8 bg-violet-500/10 border border-violet-500/30 rounded-xl p-8 text-center">
          <Clapperboard className="w-10 h-10 text-violet-400 mx-auto mb-4 opacity-60" />
          <p className="text-violet-200 font-semibold text-lg mb-2">Welcome to Video Composer</p>
          <p className="text-sm text-violet-300/70 mb-6 max-w-md mx-auto">
            Upload your photos and videos, then let AI create beautiful montages from your library.
          </p>
          <button
            onClick={() => navigate('/library')}
            className="inline-flex items-center gap-2 bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-5 py-2.5 rounded-lg transition-colors"
          >
            <Upload className="w-4 h-4" /> Upload Your First Media
          </button>
        </div>
      )}
    </div>
  )
}
