import { useEffect, useState } from 'react'
import { Routes, Route, NavLink, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Film, LayoutDashboard, FolderOpen, Search, Clapperboard, Play, Menu, X, Layers } from 'lucide-react'
import { fetchStats, fetchVideos } from './api'
import { ErrorBoundary } from './components/ErrorBoundary'
import Dashboard from './pages/Dashboard'
import Library from './pages/Library'
import SearchPage from './pages/SearchPage'
import Studio from './pages/Studio'
import Videos from './pages/Videos'
import ProjectsPage from './pages/ProjectsPage'
import ProjectEditor from './pages/ProjectEditor'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard', shortcut: '1' },
  { to: '/library', icon: FolderOpen, label: 'Library', shortcut: '2' },
  { to: '/search', icon: Search, label: 'Search', shortcut: '3' },
  { to: '/projects', icon: Layers, label: 'Projects', shortcut: '4' },
  { to: '/studio', icon: Clapperboard, label: 'Studio', shortcut: '5' },
  { to: '/videos', icon: Play, label: 'Videos', shortcut: '6' },
]

export default function App() {
  const navigate = useNavigate()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const { data: stats } = useQuery({ queryKey: ['stats'], queryFn: fetchStats, refetchInterval: 10000 })
  const { data: videosData } = useQuery({ queryKey: ['videos'], queryFn: fetchVideos, refetchInterval: 10000 })

  const navBadges: Record<string, number | undefined> = {
    '/library': stats?.total,
    '/videos': videosData?.videos?.length,
  }

  // Global keyboard shortcuts: Ctrl+1-5 for navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger when typing in inputs
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      if ((e.ctrlKey || e.metaKey) && e.key >= '1' && e.key <= '6') {
        e.preventDefault()
        const idx = parseInt(e.key) - 1
        if (navItems[idx]) navigate(navItems[idx].to)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [navigate])

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Mobile header */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-50 bg-zinc-950 border-b border-zinc-800 flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <Film className="w-5 h-5 text-violet-400" />
          <span className="text-sm font-bold">Video Composer</span>
        </div>
        <button
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className="p-1.5 rounded-lg hover:bg-zinc-800 text-zinc-400"
        >
          {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>
      </div>

      {/* Mobile nav overlay */}
      {mobileMenuOpen && (
        <div className="md:hidden fixed inset-0 z-40 bg-black/60" onClick={() => setMobileMenuOpen(false)}>
          <nav
            className="absolute top-[52px] left-0 right-0 bg-zinc-950 border-b border-zinc-800 p-3"
            onClick={(e) => e.stopPropagation()}
          >
            {navItems.map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                onClick={() => setMobileMenuOpen(false)}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-violet-500/15 text-violet-300'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
                  }`
                }
              >
                <Icon className="w-4 h-4" />
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
      )}

      {/* Desktop Sidebar */}
      <nav className="w-56 shrink-0 border-r border-zinc-800 bg-zinc-950 hidden md:flex flex-col">
        <div className="flex items-center gap-2.5 px-5 py-5 border-b border-zinc-800">
          <Film className="w-6 h-6 text-violet-400" />
          <span className="text-base font-bold tracking-tight">Video Composer</span>
        </div>
        <div className="flex flex-col gap-0.5 p-3 flex-1">
          {navItems.map(({ to, icon: Icon, label, shortcut }) => {
            const badge = navBadges[to]
            return (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-violet-500/15 text-violet-300'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
                  }`
                }
              >
                <Icon className="w-4 h-4" />
                <span className="flex-1">{label}</span>
                {badge != null && badge > 0 && (
                  <span className="text-[10px] tabular-nums text-zinc-500 bg-zinc-800 px-1.5 py-0.5 rounded-full min-w-[20px] text-center">
                    {badge}
                  </span>
                )}
                <kbd className="text-[9px] text-zinc-600 font-mono hidden lg:inline">⌘{shortcut}</kbd>
              </NavLink>
            )
          })}
        </div>
        <div className="p-4 border-t border-zinc-800 text-xs text-zinc-600">
          AI-powered video editing
        </div>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto bg-zinc-900 pt-[52px] md:pt-0">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/library" element={<Library />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/project/:id" element={<ProjectEditor />} />
            <Route path="/studio" element={<ErrorBoundary fallbackMessage="Studio encountered an error"><Studio /></ErrorBoundary>} />
            <Route path="/videos" element={<Videos />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  )
}
