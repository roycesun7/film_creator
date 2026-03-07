import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { searchMedia, thumbnailUrl, videoUrl, type MediaItem } from '../api'
import {
  Search, Loader2, Image, Film, Zap, Sparkles, Clapperboard,
  CheckSquare, Square, X, Clock, Tag, Users, AlertCircle,
  ChevronDown, ChevronUp, Filter
} from 'lucide-react'

type ResultItem = MediaItem & { relevance_score?: number }

export default function SearchPage() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [fast, setFast] = useState(false)
  const [results, setResults] = useState<ResultItem[]>([])
  const [searched, setSearched] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [detailItem, setDetailItem] = useState<ResultItem | null>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const [showFilters, setShowFilters] = useState(false)
  const [albumsFilter, setAlbumsFilter] = useState('')
  const [personsFilter, setPersonsFilter] = useState('')
  const [minQuality, setMinQuality] = useState<number | ''>('')

  // Auto-focus search input on mount
  useEffect(() => { searchInputRef.current?.focus() }, [])

  // Close detail modal on Escape
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && detailItem) setDetailItem(null)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [detailItem])

  const parseList = (val: string): string[] | undefined => {
    const items = val.split(',').map(s => s.trim()).filter(Boolean)
    return items.length > 0 ? items : undefined
  }

  const searchMut = useMutation({
    mutationFn: () => searchMedia({
      query,
      fast,
      limit: 30,
      albums: parseList(albumsFilter),
      persons: parseList(personsFilter),
      min_quality: minQuality !== '' ? minQuality : undefined,
    }),
    onSuccess: (data) => {
      setResults(data.results)
      setSearched(true)
      setSelected(new Set())
    },
  })

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim()) searchMut.mutate()
  }

  const toggleSelect = useCallback((uuid: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(uuid)) next.delete(uuid)
      else next.add(uuid)
      return next
    })
  }, [])

  const selectAll = () => setSelected(new Set(results.map(r => r.uuid)))

  const handleCreateVideo = () => {
    const uuids = Array.from(selected)
    navigate(`/studio?uuids=${uuids.join(',')}&prompt=${encodeURIComponent(query)}`)
  }

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Search</h1>
        <p className="text-sm text-zinc-400 mt-1">Find media using natural language</p>
      </div>

      <form onSubmit={handleSearch} className="mb-8">
        <div className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-zinc-500" />
          <input
            ref={searchInputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Describe what you're looking for... (e.g. 'beach sunset', 'birthday party')"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-xl pl-12 pr-36 py-3.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent"
          />
          <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-2">
            <button
              type="button"
              onClick={() => setFast(!fast)}
              className={`flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-lg transition-colors ${
                fast
                  ? 'bg-amber-500/20 text-amber-300'
                  : 'bg-zinc-700 text-zinc-400 hover:text-zinc-300'
              }`}
            >
              <Zap className="w-3 h-3" />
              Fast
            </button>
            <button
              type="submit"
              disabled={!query.trim() || searchMut.isPending}
              className="flex items-center gap-1.5 bg-violet-600 hover:bg-violet-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium px-4 py-1.5 rounded-lg transition-colors"
            >
              {searchMut.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Sparkles className="w-3.5 h-3.5" />
              )}
              Search
            </button>
          </div>
        </div>
        {fast && (
          <p className="text-xs text-amber-400/70 mt-2 pl-1">
            Fast mode: text search only (no semantic matching)
          </p>
        )}
      </form>

      <div className="mb-6 border border-zinc-700/50 rounded-lg overflow-hidden">
        <button
          onClick={() => setShowFilters(!showFilters)}
          className="w-full flex items-center justify-between px-4 py-2.5 text-xs font-medium text-zinc-400 hover:text-zinc-300 hover:bg-zinc-800/50 transition-colors"
        >
          <span className="flex items-center gap-2">
            <Filter className="w-3.5 h-3.5" />
            Filters
            {(albumsFilter || personsFilter || minQuality !== '') && (
              <span className="w-1.5 h-1.5 rounded-full bg-violet-400" />
            )}
          </span>
          {showFilters ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {showFilters && (
          <div className="px-4 pb-4 pt-2 border-t border-zinc-700/50 grid grid-cols-3 gap-4">
            <div>
              <label className="block text-[11px] font-medium text-zinc-500 mb-1">Albums</label>
              <input
                type="text"
                value={albumsFilter}
                onChange={(e) => setAlbumsFilter(e.target.value)}
                placeholder="e.g. Vacation, Summer"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-zinc-500 mb-1">Persons</label>
              <input
                type="text"
                value={personsFilter}
                onChange={(e) => setPersonsFilter(e.target.value)}
                placeholder="e.g. Alice, Bob"
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-zinc-500 mb-1">Min quality</label>
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
          </div>
        )}
      </div>

      {searchMut.isPending && (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 animate-spin text-violet-400" />
          <span className="ml-3 text-sm text-zinc-400">
            {fast ? 'Searching descriptions...' : 'Computing embeddings & searching...'}
          </span>
        </div>
      )}

      {searchMut.isError && (
        <div className="text-center py-12">
          <AlertCircle className="w-8 h-8 text-red-400 mx-auto mb-3" />
          <p className="text-sm text-red-300 mb-1">Search failed</p>
          <p className="text-xs text-zinc-500">{searchMut.error instanceof Error ? searchMut.error.message : 'An error occurred'}</p>
          <button
            onClick={() => searchMut.mutate()}
            className="mt-3 text-xs text-violet-400 hover:text-violet-300 underline"
          >
            Try again
          </button>
        </div>
      )}

      {searched && !searchMut.isPending && results.length === 0 && (
        <div className="text-center py-16 text-zinc-500">
          <Search className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p>No results found for &ldquo;{query}&rdquo;</p>
          <p className="text-xs mt-1">Try different keywords or index more media</p>
        </div>
      )}

      {results.length > 0 && (
        <>
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-zinc-400">{results.length} results for &ldquo;{query}&rdquo;</p>
            <div className="flex items-center gap-2">
              {selected.size > 0 && (
                <button
                  onClick={() => setSelected(new Set())}
                  className="flex items-center gap-1 text-xs text-zinc-400 hover:text-zinc-200 px-2 py-1 rounded-lg transition-colors"
                >
                  <X className="w-3 h-3" /> Clear
                </button>
              )}
              <button
                onClick={selectAll}
                className="flex items-center gap-1 text-xs text-zinc-400 hover:text-zinc-200 bg-zinc-800 px-2.5 py-1.5 rounded-lg transition-colors"
              >
                <CheckSquare className="w-3 h-3" /> Select All
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2 sm:gap-3">
            {results.map((item) => (
              <ResultCard
                key={item.uuid}
                item={item}
                isSelected={selected.has(item.uuid)}
                onToggleSelect={() => toggleSelect(item.uuid)}
                onDetail={() => setDetailItem(item)}
              />
            ))}
          </div>
        </>
      )}

      {selected.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 bg-zinc-900 border border-zinc-700 rounded-xl px-5 py-3 shadow-2xl">
          <span className="text-sm text-zinc-300">{selected.size} selected</span>
          <div className="w-px h-5 bg-zinc-700" />
          <button
            onClick={handleCreateVideo}
            className="flex items-center gap-2 bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            <Clapperboard className="w-4 h-4" /> Create Video
          </button>
        </div>
      )}

      {detailItem && <ResultDetail item={detailItem} onClose={() => setDetailItem(null)} />}
    </div>
  )
}

function ResultCard({ item, isSelected, onToggleSelect, onDetail }: {
  item: ResultItem
  isSelected: boolean
  onToggleSelect: () => void
  onDetail: () => void
}) {
  const [imgError, setImgError] = useState(false)
  const desc = item.description as Record<string, any> | undefined
  const summary = desc?.summary || ''

  return (
    <div className={`group relative bg-zinc-800/50 border rounded-lg overflow-hidden transition-all cursor-pointer ${
      isSelected ? 'border-violet-500 ring-1 ring-violet-500/30' : 'border-zinc-700/40 hover:border-violet-500/40'
    }`}>
      <div className="aspect-square bg-zinc-800 overflow-hidden" onClick={onDetail}>
        {!imgError ? (
          <img
            src={thumbnailUrl(item.uuid)}
            alt=""
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
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
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); onToggleSelect() }}
        className="absolute top-1.5 left-1.5 p-0.5 rounded bg-black/50 hover:bg-black/70 transition-colors"
      >
        {isSelected ? (
          <CheckSquare className="w-4 h-4 text-violet-400" />
        ) : (
          <Square className="w-4 h-4 text-zinc-400 opacity-0 group-hover:opacity-100 transition-opacity" />
        )}
      </button>
      <div className="p-2.5">
        <div className="flex items-center justify-between mb-1">
          <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded ${
            item.media_type === 'video'
              ? 'bg-emerald-500/20 text-emerald-300'
              : 'bg-blue-500/20 text-blue-300'
          }`}>
            {item.media_type}
          </span>
          {item.relevance_score != null && (
            <span className="text-[10px] text-zinc-500 tabular-nums">
              {(item.relevance_score * 100).toFixed(1)}%
            </span>
          )}
        </div>
        {item.relevance_score != null && (
          <div className="w-full h-1 bg-zinc-700 rounded-full overflow-hidden mt-1.5">
            <div
              className="h-full bg-violet-500/60 rounded-full"
              style={{ width: `${Math.min(item.relevance_score * 100, 100)}%` }}
            />
          </div>
        )}
        {summary && (
          <p className="text-[11px] text-zinc-400 line-clamp-2 mt-1.5">{summary}</p>
        )}
        <p className="text-[10px] text-zinc-600 mt-1">{item.date?.slice(0, 10)}</p>
      </div>
    </div>
  )
}

function ResultDetail({ item, onClose }: { item: ResultItem; onClose: () => void }) {
  const desc = item.description as Record<string, any> | undefined
  const isVideo = item.media_type === 'video'

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
            <span className="text-sm font-semibold text-zinc-300">{item.uuid.slice(0, 12)}</span>
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
              {item.date && (
                <div className="flex items-center gap-2 text-zinc-400">
                  <Clock className="w-3.5 h-3.5" />
                  <span>{item.date.slice(0, 10)}</span>
                </div>
              )}
              {(item.width && item.height) && (
                <div className="text-zinc-400 text-xs">{item.width}x{item.height}</div>
              )}
              {item.relevance_score != null && (
                <div className="text-xs text-violet-400">
                  Relevance: {(item.relevance_score * 100).toFixed(1)}%
                </div>
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
          {desc?.summary && (
            <div className="mt-4 p-3 bg-zinc-800/60 rounded-lg">
              <p className="text-xs text-zinc-500 mb-1">AI Description</p>
              <p className="text-sm text-zinc-300">{desc.summary}</p>
            </div>
          )}
          {item.labels.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {item.labels.map(label => (
                <span key={label} className="text-[10px] px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400 border border-zinc-700">
                  {label}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
