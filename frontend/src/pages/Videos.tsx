import { useQuery } from '@tanstack/react-query'
import { fetchVideos } from '../api'
import { Film, Play, Clock, HardDrive, Loader2 } from 'lucide-react'
import { useState } from 'react'

export default function Videos() {
  const { data, isLoading } = useQuery({
    queryKey: ['videos'],
    queryFn: fetchVideos,
  })
  const [playing, setPlaying] = useState<string | null>(null)

  const videos = data?.videos || []

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Videos</h1>
        <p className="text-sm text-zinc-400 mt-1">Your generated videos</p>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 animate-spin text-zinc-500" />
        </div>
      )}

      {!isLoading && videos.length === 0 && (
        <div className="text-center py-20 text-zinc-500">
          <Film className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>No videos generated yet</p>
          <p className="text-xs mt-1">Go to the Studio to create your first video</p>
        </div>
      )}

      {/* Video player */}
      {playing && (
        <div className="mb-8">
          <video
            src={playing}
            controls
            autoPlay
            className="w-full rounded-xl max-h-[500px] bg-black border border-zinc-700"
          />
        </div>
      )}

      {/* Video list */}
      <div className="space-y-3">
        {videos.map((v) => (
          <button
            key={v.filename}
            onClick={() => setPlaying(v.path)}
            className={`w-full flex items-center gap-4 p-4 rounded-xl border transition-all text-left ${
              playing === v.path
                ? 'bg-violet-500/10 border-violet-500/40'
                : 'bg-zinc-800/50 border-zinc-700/40 hover:border-zinc-600'
            }`}
          >
            <div className={`p-2.5 rounded-lg ${
              playing === v.path ? 'bg-violet-500/20' : 'bg-zinc-700/50'
            }`}>
              {playing === v.path ? (
                <Play className="w-5 h-5 text-violet-400" />
              ) : (
                <Film className="w-5 h-5 text-zinc-400" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{v.filename.replace('.mp4', '')}</p>
              <div className="flex items-center gap-3 mt-1 text-xs text-zinc-500">
                <span className="flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  {new Date(v.created_at).toLocaleDateString()}
                </span>
                <span className="flex items-center gap-1">
                  <HardDrive className="w-3 h-3" />
                  {v.size_mb} MB
                </span>
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
