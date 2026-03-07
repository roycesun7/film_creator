import { useState, useRef, useCallback, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useToast } from '../components/Toast'
import { fetchMedia, uploadFiles, deleteMediaItem, startIndex, thumbnailUrl, videoUrl, type MediaItem } from '../api'
import {
  Image, Film, ChevronLeft, ChevronRight,
  Loader2, Upload, X, Clock, Tag, Users, Plus,
  Trash2, CheckSquare, Square, MousePointerClick, Clapperboard, Zap, MessageSquare, AlertCircle, Sparkles
} from 'lucide-react'

function MediaCard({
  item,
  onClick,
  selectMode,
  isSelected,
  onToggleSelect,
}: {
  item: MediaItem
  onClick: () => void
  selectMode: boolean
  isSelected: boolean
  onToggleSelect: () => void
}) {
  const [imgError, setImgError] = useState(false)
  const [hovering, setHovering] = useState(false)
  const videoRef = useRef<HTMLVideoElement>(null)
  const isVideo = item.media_type === 'video'

  useEffect(() => {
    if (!isVideo || !videoRef.current) return
    if (hovering) {
      videoRef.current.play().catch(() => {})
    } else {
      videoRef.current.pause()
      videoRef.current.currentTime = 0
    }
  }, [hovering, isVideo])

  return (
    <button
      onClick={selectMode ? onToggleSelect : onClick}
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      className={`group relative aspect-square bg-zinc-800 rounded-lg overflow-hidden border transition-all ${
        isSelected
          ? 'border-violet-500 ring-2 ring-violet-500/40'
          : 'border-zinc-700/40 hover:border-violet-500/50 hover:ring-1 hover:ring-violet-500/30'
      }`}
    >
      {isVideo && hovering && (
        <video
          ref={videoRef}
          src={videoUrl(item.uuid)}
          muted
          loop
          playsInline
          className="absolute inset-0 w-full h-full object-cover z-[1]"
        />
      )}
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
          {isVideo ? (
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

      {selectMode && (
        <div className="absolute top-1.5 left-1.5 z-10">
          {isSelected ? (
            <CheckSquare className="w-5 h-5 text-violet-400 drop-shadow-lg" />
          ) : (
            <Square className="w-5 h-5 text-zinc-400 drop-shadow-lg" />
          )}
        </div>
      )}

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
      {item.quality_score != null && !selectMode && (
        <div className="absolute top-1.5 left-1.5">
          <span className="text-[9px] font-bold bg-black/50 text-zinc-200 px-1.5 py-0.5 rounded">
            Q{Math.round(item.quality_score)}
          </span>
        </div>
      )}
    </button>
  )
}

function MediaDetail({
  item,
  onClose,
  onDelete,
  isDeleting,
}: {
  item: MediaItem
  onClose: () => void
  onDelete: () => void
  isDeleting: boolean
}) {
  const desc = item.description || {}
  const isVideo = item.media_type === 'video'
  const hasDescription = desc.summary || Object.keys(desc).length > 0

  function formatDuration(seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return m > 0 ? `${m}m ${s}s` : `${s}s`
  }

  const [confirmDelete, setConfirmDelete] = useState(false)

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
          <div className="flex items-center gap-2">
            {!confirmDelete ? (
              <button
                onClick={() => setConfirmDelete(true)}
                className="text-zinc-400 hover:text-red-400 transition-colors p-1 rounded hover:bg-red-500/10"
                title="Delete"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            ) : (
              <div className="flex items-center gap-1.5">
                <button
                  onClick={onDelete}
                  disabled={isDeleting}
                  className="flex items-center gap-1 text-xs font-medium bg-red-600 hover:bg-red-500 disabled:bg-red-800 text-white px-2.5 py-1 rounded-md transition-colors"
                >
                  {isDeleting ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <Trash2 className="w-3 h-3" />
                  )}
                  Delete
                </button>
                <button
                  onClick={() => setConfirmDelete(false)}
                  className="text-zinc-400 hover:text-zinc-200 text-xs px-2 py-1 rounded-md hover:bg-zinc-800 transition-colors"
                >
                  Cancel
                </button>
              </div>
            )}
            <button onClick={onClose} className="text-zinc-400 hover:text-zinc-200">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
        <div className="p-5">
          <div className="aspect-video bg-black rounded-lg overflow-hidden mb-5 flex items-center justify-center">
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
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
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
              <div className="flex items-center gap-2 text-zinc-400">
                <Zap className="w-3.5 h-3.5" />
                <span className={hasDescription ? 'text-emerald-400' : 'text-zinc-500'}>
                  {hasDescription ? 'Embedded' : 'Not embedded'}
                </span>
              </div>
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

          {item.labels.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-1.5">
              {item.labels.map((label) => (
                <span
                  key={label}
                  className="text-[11px] font-medium bg-zinc-800 text-zinc-300 border border-zinc-700 px-2 py-0.5 rounded-full"
                >
                  {label}
                </span>
              ))}
            </div>
          )}

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
  const navigate = useNavigate()
  const toast = useToast()
  const [offset, setOffset] = useState(0)
  const [sort, setSort] = useState('date')
  const [selected, setSelected] = useState<MediaItem | null>(null)
  const [dragging, setDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const limit = 24

  const [mediaTypeFilter, setMediaTypeFilter] = useState<string>('')
  const [autoDescribe, setAutoDescribe] = useState(false)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedUuids, setSelectedUuids] = useState<Set<string>>(new Set())

  // Close modal on Escape
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && selected) setSelected(null)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selected])

  const { data, isLoading, error: mediaError, refetch: refetchMedia } = useQuery({
    queryKey: ['media', offset, sort, mediaTypeFilter],
    queryFn: () => fetchMedia({ limit, offset, sort, media_type: mediaTypeFilter || undefined }),
  })

  const uploadMut = useMutation({
    mutationFn: (files: FileList | File[]) => uploadFiles(files, autoDescribe),
    onSuccess: (data) => {
      toast(`${data.uploaded} file${data.uploaded !== 1 ? 's' : ''} uploaded. Embedding in background...`, 'success')
      queryClient.invalidateQueries({ queryKey: ['media'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (err) => toast(err instanceof Error ? err.message : 'Upload failed', 'error'),
  })

  const deleteMut = useMutation({
    mutationFn: (uuid: string) => deleteMediaItem(uuid),
    onSuccess: () => {
      setSelected(null)
      toast('Media deleted', 'success')
      queryClient.invalidateQueries({ queryKey: ['media'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (err) => toast(err instanceof Error ? err.message : 'Delete failed', 'error'),
  })

  const bulkDeleteMut = useMutation({
    mutationFn: async (uuids: string[]) => {
      await Promise.all(uuids.map((uuid) => deleteMediaItem(uuid)))
    },
    onSuccess: () => {
      setSelectedUuids(new Set())
      setSelectMode(false)
      toast('Selected items deleted', 'success')
      queryClient.invalidateQueries({ queryKey: ['media'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (err) => toast(err instanceof Error ? err.message : 'Bulk delete failed', 'error'),
  })

  const indexMut = useMutation({
    mutationFn: () => startIndex({ describe: true }),
    onSuccess: () => {
      toast('Embedding started — this runs in the background', 'success')
    },
    onError: (err) => toast(err instanceof Error ? err.message : 'Failed to start embedding', 'error'),
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

  function toggleSelect(uuid: string) {
    setSelectedUuids((prev) => {
      const next = new Set(prev)
      if (next.has(uuid)) {
        next.delete(uuid)
      } else {
        next.add(uuid)
      }
      return next
    })
  }

  function exitSelectMode() {
    setSelectMode(false)
    setSelectedUuids(new Set())
  }

  function handleSelectAll() {
    if (selectedUuids.size === items.length) {
      setSelectedUuids(new Set())
    } else {
      setSelectedUuids(new Set(items.map((i) => i.uuid)))
    }
  }

  function handleCreateVideo() {
    const params = new URLSearchParams()
    params.set('media', Array.from(selectedUuids).join(','))
    navigate(`/studio?${params.toString()}`)
  }

  const items = data?.items || []
  const total = data?.total || 0
  const totalPages = Math.ceil(total / limit)
  const currentPage = Math.floor(offset / limit) + 1

  return (
    <div
      className="p-4 sm:p-8 max-w-7xl mx-auto min-h-full"
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="image/*,video/*"
        className="hidden"
        onChange={(e) => e.target.files && handleFiles(e.target.files)}
      />

      {dragging && (
        <div className="fixed inset-0 z-50 bg-violet-500/10 border-2 border-dashed border-violet-500 flex items-center justify-center pointer-events-none">
          <div className="bg-zinc-900 border border-violet-500 rounded-2xl px-10 py-8 text-center">
            <Upload className="w-10 h-10 text-violet-400 mx-auto mb-3" />
            <p className="text-lg font-semibold text-violet-200">Drop files to upload</p>
            <p className="text-sm text-violet-300/60 mt-1">Photos and videos</p>
          </div>
        </div>
      )}

      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold">Library</h1>
          <p className="text-sm text-zinc-400 mt-1">{total} items indexed</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          <div className="flex items-center bg-zinc-800 border border-zinc-700 rounded-lg overflow-hidden">
            {([['', 'All'], ['photo', 'Photos'], ['video', 'Videos']] as const).map(([value, label]) => (
              <button
                key={value}
                onClick={() => { setMediaTypeFilter(value); setOffset(0) }}
                className={`text-sm font-medium px-3 py-1.5 transition-colors ${
                  mediaTypeFilter === value
                    ? 'bg-violet-600 text-white'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
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
            onClick={() => selectMode ? exitSelectMode() : setSelectMode(true)}
            className={`flex items-center gap-2 text-sm font-medium px-4 py-2 rounded-lg transition-colors ${
              selectMode
                ? 'bg-violet-600 text-white hover:bg-violet-500'
                : 'bg-zinc-800 text-zinc-300 border border-zinc-700 hover:bg-zinc-700'
            }`}
          >
            <MousePointerClick className="w-4 h-4" />
            {selectMode ? 'Cancel' : 'Select'}
          </button>
          <button
            onClick={() => setAutoDescribe(!autoDescribe)}
            className={`flex items-center gap-1.5 text-xs font-medium px-3 py-2 rounded-lg transition-colors ${
              autoDescribe
                ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                : 'bg-zinc-800 text-zinc-400 border border-zinc-700 hover:text-zinc-300'
            }`}
            title="Auto-describe uploads with AI"
          >
            <MessageSquare className="w-3.5 h-3.5" />
            AI Describe
          </button>
          <button
            onClick={() => indexMut.mutate()}
            disabled={indexMut.isPending}
            className="flex items-center gap-1.5 text-xs font-medium px-3 py-2 rounded-lg bg-zinc-800 text-zinc-400 border border-zinc-700 hover:text-zinc-300 hover:bg-zinc-700 disabled:opacity-50 transition-colors"
            title="Run AI embedding on all unprocessed media"
          >
            {indexMut.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Sparkles className="w-3.5 h-3.5" />
            )}
            Embed All
          </button>
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

      {isLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="aspect-square bg-zinc-800 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : mediaError ? (
        <div className="text-center py-12">
          <AlertCircle className="w-8 h-8 text-red-400 mx-auto mb-3" />
          <p className="text-sm text-red-300 mb-1">Failed to load media</p>
          <p className="text-xs text-zinc-500">{mediaError instanceof Error ? mediaError.message : 'An error occurred'}</p>
          <button
            onClick={() => refetchMedia()}
            className="mt-3 text-xs text-violet-400 hover:text-violet-300 underline"
          >
            Retry
          </button>
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
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2">
            {items.map((item) => (
              <MediaCard
                key={item.uuid}
                item={item}
                onClick={() => setSelected(item)}
                selectMode={selectMode}
                isSelected={selectedUuids.has(item.uuid)}
                onToggleSelect={() => toggleSelect(item.uuid)}
              />
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

      {selectMode && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 bg-zinc-900 border border-zinc-700 rounded-xl px-5 py-3 shadow-2xl shadow-black/50">
          <span className="text-sm text-zinc-400">
            {selectedUuids.size} of {items.length} selected
          </span>
          <div className="w-px h-6 bg-zinc-700" />
          <button
            onClick={handleSelectAll}
            className="flex items-center gap-1.5 text-sm text-zinc-400 hover:text-zinc-200 px-2 py-1 rounded-md hover:bg-zinc-800 transition-colors"
          >
            <CheckSquare className="w-3.5 h-3.5" />
            {selectedUuids.size === items.length ? 'Deselect All' : 'Select All'}
          </button>
          {selectedUuids.size > 0 && (
            <>
              <div className="w-px h-6 bg-zinc-700" />
              <button
                onClick={() => bulkDeleteMut.mutate(Array.from(selectedUuids))}
                disabled={bulkDeleteMut.isPending}
                className="flex items-center gap-1.5 text-sm font-medium bg-red-600 hover:bg-red-500 disabled:bg-red-800 text-white px-3 py-1.5 rounded-lg transition-colors"
              >
                {bulkDeleteMut.isPending ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Trash2 className="w-3.5 h-3.5" />
                )}
                Delete ({selectedUuids.size})
              </button>
              <button
                onClick={handleCreateVideo}
                className="flex items-center gap-1.5 text-sm font-medium bg-violet-600 hover:bg-violet-500 text-white px-3 py-1.5 rounded-lg transition-colors"
              >
                <Clapperboard className="w-3.5 h-3.5" />
                Create Video
              </button>
            </>
          )}
        </div>
      )}

      {selected && (
        <MediaDetail
          item={selected}
          onClose={() => setSelected(null)}
          onDelete={() => deleteMut.mutate(selected.uuid)}
          isDeleting={deleteMut.isPending}
        />
      )}
    </div>
  )
}
