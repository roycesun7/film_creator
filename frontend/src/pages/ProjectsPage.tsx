import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { fetchProjects, createProject, deleteProjectApi, type ProjectSummary } from '../api'
import {
  Clapperboard, Plus, Loader2, Trash2, Clock, Film,
  Layers, FolderOpen, MoreVertical
} from 'lucide-react'
import { useToast } from '../components/Toast'

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
  })
}

function formatDuration(seconds: number): string {
  if (seconds <= 0) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return m > 0 ? `${m}:${String(s).padStart(2, '0')}` : `${s}s`
}

export default function ProjectsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newPrompt, setNewPrompt] = useState('')
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: fetchProjects,
  })

  const createMut = useMutation({
    mutationFn: () => createProject({
      name: newName || 'Untitled Project',
      prompt: newPrompt,
    }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setShowCreate(false)
      setNewName('')
      setNewPrompt('')
      navigate(`/project/${data.id}`)
    },
    onError: (err) => toast(err instanceof Error ? err.message : 'Failed to create project', 'error'),
  })

  const deleteMut = useMutation({
    mutationFn: deleteProjectApi,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setDeletingId(null)
      toast('Project deleted', 'success')
    },
    onError: (err) => toast(err instanceof Error ? err.message : 'Failed to delete', 'error'),
  })

  const projects = data?.projects || []

  return (
    <div className="p-4 sm:p-8 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">Projects</h1>
          <p className="text-sm text-zinc-400 mt-1">Your film projects with editable timelines</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" /> New Project
        </button>
      </div>

      {/* Create project modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-8" onClick={() => setShowCreate(false)}>
          <div
            className="bg-zinc-900 border border-zinc-700 rounded-xl max-w-lg w-full p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-semibold mb-4">New Project</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1.5">Project Name</label>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="My Summer 2025 Highlights"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-violet-500"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1.5">Creative Brief</label>
                <textarea
                  value={newPrompt}
                  onChange={(e) => setNewPrompt(e.target.value)}
                  placeholder="Describe the video you want to create... The AI will use this to select and arrange clips from your library."
                  rows={3}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-violet-500 resize-none"
                />
              </div>
              <div className="flex items-center justify-end gap-3">
                <button
                  onClick={() => setShowCreate(false)}
                  className="text-sm text-zinc-400 hover:text-zinc-200 px-3 py-2 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => createMut.mutate()}
                  disabled={createMut.isPending}
                  className="flex items-center gap-2 bg-violet-600 hover:bg-violet-500 disabled:bg-zinc-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
                >
                  {createMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Clapperboard className="w-4 h-4" />}
                  Create Project
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 animate-spin text-zinc-500" />
        </div>
      )}

      {!isLoading && projects.length === 0 && (
        <div className="text-center py-20 text-zinc-500">
          <FolderOpen className="w-16 h-16 mx-auto mb-4 opacity-20" />
          <p className="text-lg font-medium text-zinc-400">No projects yet</p>
          <p className="text-sm mt-2 max-w-md mx-auto">
            Create a project to start building your highlights video with the timeline editor.
          </p>
          <button
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-2 mt-6 px-5 py-2.5 bg-violet-600 hover:bg-violet-500 text-white rounded-lg transition-colors font-medium text-sm"
          >
            <Plus className="w-4 h-4" /> Create Your First Project
          </button>
        </div>
      )}

      {projects.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((p) => (
            <div
              key={p.id}
              className="group bg-zinc-800/50 border border-zinc-700/40 rounded-xl overflow-hidden hover:border-violet-500/40 transition-all cursor-pointer"
            >
              <button
                onClick={() => navigate(`/project/${p.id}`)}
                className="w-full text-left p-4"
              >
                <div className="flex items-start justify-between mb-2">
                  <h3 className="text-sm font-semibold text-zinc-200 line-clamp-1">{p.name}</h3>
                  <Clapperboard className="w-4 h-4 text-zinc-600 shrink-0 ml-2" />
                </div>
                {p.prompt && (
                  <p className="text-xs text-zinc-500 line-clamp-2 mb-3">{p.prompt}</p>
                )}
                <div className="flex items-center gap-3 text-[11px] text-zinc-500">
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {formatDuration(p.duration)}
                  </span>
                  <span className="flex items-center gap-1">
                    <Layers className="w-3 h-3" />
                    {p.track_count} tracks
                  </span>
                  {p.render_count > 0 && (
                    <span className="flex items-center gap-1">
                      <Film className="w-3 h-3" />
                      {p.render_count} render{p.render_count !== 1 ? 's' : ''}
                    </span>
                  )}
                </div>
                <p className="text-[10px] text-zinc-600 mt-2">
                  Updated {formatDate(p.updated_at)}
                </p>
              </button>
              <div className="border-t border-zinc-700/40 px-4 py-2 flex items-center justify-between">
                <span className="text-[10px] text-zinc-600 uppercase tracking-wide">{p.theme}</span>
                {deletingId === p.id ? (
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={(e) => { e.stopPropagation(); deleteMut.mutate(p.id) }}
                      className="text-[11px] text-red-400 hover:text-red-300 font-medium"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); setDeletingId(null) }}
                      className="text-[11px] text-zinc-500 hover:text-zinc-300"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={(e) => { e.stopPropagation(); setDeletingId(p.id) }}
                    className="p-1 rounded text-zinc-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
