import { useState, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchMedia, uploadFiles, thumbnailUrl, videoUrl, type MediaItem } from '../api'
import {
  Image, Film, ChevronLeft, ChevronRight,
  Loader2, Upload, X, Clock, Tag, Users, Plus, CheckCircle2
} from 'lucide-react'

function MediaCard({ item, onClick }: { item: MediaItem; onClick: () => void }) {
  const [imgError, setImgError] = useState(false)
  return (
    <button
      onClick={onClick}
      className="group relative aspect-square bg-zinc-800 rounded-lg overflow-hidden border border-zinc-700/40 hover:border-violet-500/50 transition-all hover:ring-1 hover:ring-violet-500/30"
    >
      {!imgError ? (
        <img
          src={thumbnailUrl(item.uuid)}
          alt=""
          className="w-full h-full object-cover"
          onError={() => setImgError(true)}
          loading="lazy"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center">
          {item.media_type === 'video' ? (
            <Film className="w-8 h-8 text-zinc-600" />
          ) : (
            <Image className="w-8 h-8 text-zinc-600" />
          )}
        </div>
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
      <div className="absolute bottom-0 left-0 right-0 p-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <p className="text-[10px] text-zinc-300 truncate">{item.date?.slice(0, 10) || 'No date'}</p>
      </div>
      <div className="absolute top-1.5 right-1.5 flex items-center gap-1">
        {item.media_type === 'video' && item.duration != null && item.duration > 0 && (
          <span className="text-[9px] font-bold bg-black/70 text-white px-1.5 py-0.5 rounded">
            {Math.floor(item.duration / 60)}:{String(Math.floor(item.duration % 60)).padStart(2, '0')}
          </span>
        )}
        <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded ${
          item.media_type === 'video'
            ? 'bg-emerald-500/80 text-white'
            : 'bg-blue-500/80 text-white'
        }`}>
          {item.media_type === 'video' ? 'VID' : 'IMG'}
        </span>
      </div>
      {item.quality_score != null && (
        <div className="absolute top-1.5 left-1.5">
          <span className="text-[9px] font-bold bg-black/50 text-zinc-200 px-1.5 py-0.5 rounded">
            Q{Math.round(item.quality_score)}
          </span>
        </div>
      )}
    </button>
  )
}

function MediaDetail({ item, onClose }: { item: MediaItem; onClose: () => void }) {
  const desc = item.description || {}
  const isVideo = item.media_type === 'video'

  function formatDuration(seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return m > 0 ? `${m}m ${s}s` : `${s}s`
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-8" onClick={onClose}>
      <div
        className="bg-zinc-900 border border-zinc-700 rounded-xl max-w-3xl w-full max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-3">
          <div className="flex items-center gap-2">
            <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${
              isVideo ? 'bg-emerald-500/80 text-white' : 'bg-blue-500/80 text-white'
            }`}>
              {isVideo ? 'Video' : 'Photo'}
            </span>
            <h2 className="text-sm font-semibold text-zinc-300">
              {item.path ? item.path.split('/').pop() : item.uuid.slice(0, 12)}
            </h2>
          </div>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-200">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-5">
          <div className="aspect-video bg-black rounded-lg overflow-hidden mb-5">
            {isVideo ? (
              <video
                src={videoUrl(item.uuid)}
                controls
                autoPlay
                className="w-full h-full object-contain"
                poster={thumbnailUrl(item.uuid)}
              />
            ) : (
              <img
                src={thumbnailUrl(item.uuid)}
                alt=""
                className="w-full h-full object-contain"
              />
            )}
          </div>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-zinc-400">
                <Clock className="w-3.5 h-3.5" />
                <span>{item.date?.slice(0, 10) || 'Unknown date'}</span>
              </div>
              {item.duration != null && item.duration > 0 && (
                <div className="flex items-center gap-2 text-zinc-400">
                  <Film className="w-3.5 h-3.5" />
                  <span>{formatDuration(item.duration)}</span>
                </div>
              )}
              {(item.width && item.height) && (
                <div className="text-zinc-400 text-xs">{item.width}x{item.height}</div>
              )}
            </div>
            <div className="space-y-2">
              {item.albums.length > 0 && (
                <div className="flex items-center gap-2 text-zinc-400">
                  <Tag className="w-3.5 h-3.5" />
                  <span className="truncate">{item.albums.join(', ')}</span>
                </div>
              )}
              {item.persons.length > 0 && (
                <div className="flex items-center gap-2 text-zinc-400">
                  <Users className="w-3.5 h-3.5" />
                  <span className="truncate">{item.persons.join(', ')}</span>
                </div>
              )}
            </div>
          </div>
          {desc.summary && (
            <div className="mt-4 p-3 bg-zinc-800/60 rounded-lg">
              <p className="text-xs text-zinc-500 mb-1">AI Description</p>
              <p className="text-sm text-zinc-300">{desc.summary}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function Library() {
  const queryClient = useQueryClient()
  const [offset, setOffset] = useState(0)
  const [sort, setSort] = useState('date')
  const [selected, setSelected] = useState<MediaItem | null>(null)
  const [dragging, setDragging] = useState(false)
  const [uploadResult, setUploadResult] = useState<{ count: number; visible: boolean } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const limit = 24

  const { data, isLoading } = useQuery({
    queryKey: ['media', offset, sort],
    queryFn: () => fetchMedia({ limit, offset, sort }),
  })

  const uploadMut = useMutation({
    mutationFn: (files: FileList | File[]) => uploadFiles(files),
    onSuccess: (data) => {
      setUploadResult({ count: data.uploaded, visible: true })
      // Refresh immediately — records are inserted before embedding starts
      queryClient.invalidateQueries({ queryKey: ['media'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
      // Hide success message after 4s
      setTimeout(() => setUploadResult(null), 4000)
    },
  })

  const handleFiles = useCallback((files: FileList | File[]) => {
    if (files.length > 0) {
      uploadMut.mutate(files)
    }
  }, [uploadMut])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    handleFiles(e.dataTransfer.files)
  }, [handleFiles])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
  }, [])

  const items = data?.items || []
  const total = data?.total || 0
  const totalPages = Math.ceil(total / limit)
  const currentPage = Math.floor(offset / limit) + 1

  return (
    <div
      className="p-8 max-w-7xl mx-auto min-h-full"
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="image/*,video/*"
        className="hidden"
        onChange={(e) => e.target.files && handleFiles(e.target.files)}
      />

      {/* Drag overlay */}
      {dragging && (
        <div className="fixed inset-0 z-50 bg-violet-500/10 border-2 border-dashed border-violet-500 flex items-center justify-center pointer-events-none">
          <div className="bg-zinc-900 border border-violet-500 rounded-2xl px-10 py-8 text-center">
            <Upload className="w-10 h-10 text-violet-400 mx-auto mb-3" />
            <p className="text-lg font-semibold text-violet-200">Drop files to upload</p>
            <p className="text-sm text-violet-300/60 mt-1">Photos and videos</p>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Library</h1>
          <p className="text-sm text-zinc-400 mt-1">{total} items indexed</p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={sort}
            onChange={(e) => { setSort(e.target.value); setOffset(0) }}
            className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-zinc-300 focus:outline-none focus:ring-1 focus:ring-violet-500"
          >
            <option value="date">Date</option>
            <option value="recent">Recently Added</option>
            <option value="quality">Quality</option>
          </select>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadMut.isPending}
            className="flex items-center gap-2 bg-violet-600 hover:bg-violet-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            {uploadMut.isPending ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Uploading...</>
            ) : (
              <><Plus className="w-4 h-4" /> Add Media</>
            )}
          </button>
        </div>
      </div>

      {/* Upload success banner */}
      {uploadResult?.visible && (
        <div className="mb-6 flex items-center gap-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg px-4 py-3">
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <span className="text-sm text-emerald-300">
            {uploadResult.count} file{uploadResult.count !== 1 ? 's' : ''} uploaded successfully. Generating embeddings in background...
          </span>
        </div>
      )}

      {/* Media grid */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 animate-spin text-zinc-500" />
        </div>
      ) : items.length === 0 ? (
        <button
          onClick={() => fileInputRef.current?.click()}
          className="w-full py-20 border-2 border-dashed border-zinc-700 hover:border-violet-500/50 rounded-2xl transition-colors group"
        >
          <Upload className="w-12 h-12 mx-auto mb-3 text-zinc-600 group-hover:text-violet-400 transition-colors" />
          <p className="text-zinc-400 group-hover:text-zinc-300 transition-colors">
            Click to choose files or drag & drop
          </p>
          <p className="text-xs text-zinc-600 mt-1">
            Photos: JPG, PNG, HEIC, WebP &bull; Videos: MP4, MOV, MKV, AVI
          </p>
        </button>
      ) : (
        <>
          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-2">
            {items.map((item) => (
              <MediaCard key={item.uuid} item={item} onClick={() => setSelected(item)} />
            ))}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-3 mt-6">
              <button
                onClick={() => setOffset(Math.max(0, offset - limit))}
                disabled={offset === 0}
                className="p-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="text-sm text-zinc-400">
                Page {currentPage} of {totalPages}
              </span>
              <button
                onClick={() => setOffset(offset + limit)}
                disabled={currentPage >= totalPages}
                className="p-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </>
      )}

      {selected && <MediaDetail item={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
