import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { searchMedia, thumbnailUrl, type MediaItem } from '../api'
import { Search, Loader2, Image, Film, Zap, Sparkles } from 'lucide-react'

export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [fast, setFast] = useState(false)
  const [results, setResults] = useState<(MediaItem & { relevance_score?: number })[]>([])
  const [searched, setSearched] = useState(false)

  const searchMut = useMutation({
    mutationFn: () => searchMedia({ query, fast, limit: 30 }),
    onSuccess: (data) => {
      setResults(data.results)
      setSearched(true)
    },
  })

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim()) searchMut.mutate()
  }

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Search</h1>
        <p className="text-sm text-zinc-400 mt-1">Find media using natural language</p>
      </div>

      {/* Search form */}
      <form onSubmit={handleSearch} className="mb-8">
        <div className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-zinc-500" />
          <input
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
            Fast mode: text search only (no CLIP semantic matching)
          </p>
        )}
      </form>

      {/* Results */}
      {searchMut.isPending && (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 animate-spin text-violet-400" />
          <span className="ml-3 text-sm text-zinc-400">
            {fast ? 'Searching descriptions...' : 'Computing CLIP embeddings & searching...'}
          </span>
        </div>
      )}

      {searched && !searchMut.isPending && results.length === 0 && (
        <div className="text-center py-16 text-zinc-500">
          <Search className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p>No results found for "{query}"</p>
          <p className="text-xs mt-1">Try different keywords or index more media</p>
        </div>
      )}

      {results.length > 0 && (
        <>
          <p className="text-sm text-zinc-400 mb-4">{results.length} results for "{query}"</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
            {results.map((item) => (
              <ResultCard key={item.uuid} item={item} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function ResultCard({ item }: { item: MediaItem & { relevance_score?: number } }) {
  const [imgError, setImgError] = useState(false)
  const desc = item.description as Record<string, any> | undefined
  const summary = desc?.summary || ''

  return (
    <div className="group relative bg-zinc-800/50 border border-zinc-700/40 rounded-lg overflow-hidden hover:border-violet-500/40 transition-all">
      <div className="aspect-square bg-zinc-800 overflow-hidden">
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
        {summary && (
          <p className="text-[11px] text-zinc-400 line-clamp-2 mt-1">{summary}</p>
        )}
        <p className="text-[10px] text-zinc-600 mt-1">{item.date?.slice(0, 10)}</p>
      </div>
    </div>
  )
}
