import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchVideos, deleteVideo, videoThumbnailUrl } from '../api'
import { Film, Play, Clock, HardDrive, Loader2, Download, Trash2, X, Clapperboard } from 'lucide-react'
import { useState, useRef, useEffect, useCallback } from 'react'
import { useToast } from '../components/Toast'

function formatTitle(filename: string): string {
  return filename.replace(/\.mp4$/i, '').replace(/_/g, ' ')
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function Videos() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const { data, isLoading } = useQuery({
    queryKey: ['videos'],
    queryFn: fetchVideos,
  })
  const [playing, setPlaying] = useState<string | null>(null)
  const [playingFilename, setPlayingFilename] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)

  // Keyboard controls for video player
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (!playing) return
    const target = e.target as HTMLElement
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') return

    const vid = videoRef.current
    if (!vid) return

    switch (e.key) {
      case ' ':
      case 'k':
        e.preventDefault()
        vid.paused ? vid.play() : vid.pause()
        break
      case 'ArrowLeft':
        e.preventDefault()
        vid.currentTime = Math.max(0, vid.currentTime - 5)
        break
      case 'ArrowRight':
        e.preventDefault()
        vid.currentTime = Math.min(vid.duration, vid.currentTime + 5)
        break
      case 'j':
        e.preventDefault()
        vid.currentTime = Math.max(0, vid.currentTime - 10)
        break
      case 'l':
        e.preventDefault()
        vid.currentTime = Math.min(vid.duration, vid.currentTime + 10)
        break
      case 'f':
        e.preventDefault()
        document.fullscreenElement ? document.exitFullscreen() : vid.requestFullscreen()
        break
      case 'm':
        e.preventDefault()
        vid.muted = !vid.muted
        break
      case 'Escape':
        setPlaying(null)
        setPlayingFilename(null)
        break
    }
  }, [playing])

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  const deleteMut = useMutation({
    mutationFn: deleteVideo,
    onSuccess: (_data, filename) => {
      queryClient.invalidateQueries({ queryKey: ['videos'] })
      toast('Video deleted', 'success')
      // If the deleted video was playing, stop playback
      if (playingFilename === filename) {
        setPlaying(null)
        setPlayingFilename(null)
      }
    },
    onError: () => toast('Failed to delete video', 'error'),
  })

  const videos = data?.videos || []

  const handlePlay = (path: string, filename: string) => {
    setPlaying(path)
    setPlayingFilename(filename)
  }

  const handleDelete = (filename: string) => {
    setConfirmingDelete(filename)
  }

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Videos</h1>
        <p className="text-sm text-zinc-400 mt-1">Your generated videos</p>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 animate-spin text-zinc-500" />
        </div>
      )}

      {/* Empty state */}
      {!isLoading && videos.length === 0 && (
        <div className="text-center py-20 text-zinc-500">
          <Film className="w-16 h-16 mx-auto mb-4 opacity-20" />
          <p className="text-lg font-medium text-zinc-400">No videos generated yet</p>
          <p className="text-sm mt-2 text-zinc-500 max-w-md mx-auto">
            Head over to the Studio to create your first video from your media library.
          </p>
          <a
            href="/studio"
            className="inline-flex items-center gap-2 mt-6 px-5 py-2.5 bg-violet-600 hover:bg-violet-500 text-white rounded-lg transition-colors font-medium text-sm"
          >
            <Clapperboard className="w-4 h-4" />
            Go to Studio
          </a>
        </div>
      )}

      {/* Video player */}
      {playing && (
        <div className="mb-8 relative">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold text-zinc-200">
              {playingFilename ? formatTitle(playingFilename) : 'Now Playing'}
            </h2>
            <button
              onClick={() => { setPlaying(null); setPlayingFilename(null) }}
              className="p-1.5 rounded-lg hover:bg-zinc-700/50 text-zinc-400 hover:text-zinc-200 transition-colors"
              title="Close player"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <video
            ref={videoRef}
            key={playing}
            src={playing}
            controls
            autoPlay
            className="w-full rounded-xl max-h-[500px] bg-black border border-zinc-700"
          />
          <div className="flex items-center gap-4 mt-2 text-[10px] text-zinc-600">
            <span><kbd className="bg-zinc-800 px-1 rounded">Space</kbd> Play/Pause</span>
            <span><kbd className="bg-zinc-800 px-1 rounded">&larr;</kbd><kbd className="bg-zinc-800 px-1 rounded">&rarr;</kbd> &plusmn;5s</span>
            <span><kbd className="bg-zinc-800 px-1 rounded">J</kbd>/<kbd className="bg-zinc-800 px-1 rounded">L</kbd> &plusmn;10s</span>
            <span><kbd className="bg-zinc-800 px-1 rounded">F</kbd> Fullscreen</span>
            <span><kbd className="bg-zinc-800 px-1 rounded">M</kbd> Mute</span>
            <span><kbd className="bg-zinc-800 px-1 rounded">Esc</kbd> Close</span>
          </div>
        </div>
      )}

      {/* Video grid */}
      {videos.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {videos.map((v) => {
            const isActive = playing === v.path
            return (
              <div
                key={v.filename}
                className={`group rounded-xl border overflow-hidden transition-all ${
                  isActive
                    ? 'bg-violet-500/10 border-violet-500/40 ring-1 ring-violet-500/30'
                    : 'bg-zinc-800/50 border-zinc-700/40 hover:border-zinc-600'
                }`}
              >
                {/* Thumbnail area */}
                <button
                  onClick={() => handlePlay(v.path, v.filename)}
                  className="relative w-full aspect-video bg-zinc-900 overflow-hidden block"
                >
                  <img
                    src={videoThumbnailUrl(v.filename)}
                    alt={formatTitle(v.filename)}
                    className="w-full h-full object-cover"
                    onError={(e) => {
                      // Hide broken image, show fallback
                      (e.target as HTMLImageElement).style.display = 'none'
                    }}
                  />
                  {/* Play overlay */}
                  <div className="absolute inset-0 flex items-center justify-center bg-black/30 opacity-0 group-hover:opacity-100 transition-opacity">
                    <div className="w-14 h-14 rounded-full bg-violet-600/90 flex items-center justify-center shadow-lg">
                      <Play className="w-7 h-7 text-white ml-1" fill="white" />
                    </div>
                  </div>
                  {/* Active indicator */}
                  {isActive && (
                    <div className="absolute top-2 right-2 px-2 py-1 bg-violet-600 rounded text-xs font-medium text-white">
                      Playing
                    </div>
                  )}
                </button>

                {/* Card info */}
                <div className="p-3">
                  <p className="text-sm font-medium truncate text-zinc-200" title={formatTitle(v.filename)}>
                    {formatTitle(v.filename)}
                  </p>
                  <div className="flex items-center gap-3 mt-1.5 text-xs text-zinc-500">
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {formatDate(v.created_at)}
                    </span>
                    <span className="flex items-center gap-1">
                      <HardDrive className="w-3 h-3" />
                      {v.size_mb} MB
                    </span>
                  </div>

                  {/* Action buttons */}
                  <div className="flex items-center gap-1 mt-3 pt-3 border-t border-zinc-700/50">
                    <button
                      onClick={() => handlePlay(v.path, v.filename)}
                      className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-violet-600/20 text-violet-400 hover:bg-violet-600/30 transition-colors"
                    >
                      <Play className="w-3.5 h-3.5" />
                      Play
                    </button>
                    <a
                      href={v.path}
                      download={v.filename}
                      className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-zinc-700/40 text-zinc-300 hover:bg-zinc-700/60 transition-colors"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Download className="w-3.5 h-3.5" />
                      Download
                    </a>
                    {confirmingDelete === v.filename ? (
                      <>
                        <button
                          onClick={() => { deleteMut.mutate(v.filename); setConfirmingDelete(null) }}
                          disabled={deleteMut.isPending}
                          className="px-2 py-1.5 text-xs font-medium rounded-lg bg-red-600/20 text-red-400 hover:bg-red-600/30 transition-colors disabled:opacity-50"
                        >
                          Delete
                        </button>
                        <button
                          onClick={() => setConfirmingDelete(null)}
                          className="px-2 py-1.5 text-xs font-medium rounded-lg text-zinc-500 hover:text-zinc-300 transition-colors"
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button
                        onClick={() => handleDelete(v.filename)}
                        disabled={deleteMut.isPending}
                        className="p-1.5 rounded-lg text-zinc-500 hover:text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50"
                        title="Delete video"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
