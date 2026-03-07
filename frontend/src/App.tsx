import { useEffect } from 'react'
import { Routes, Route, NavLink, useNavigate } from 'react-router-dom'
import { Film, LayoutDashboard, FolderOpen, Search, Clapperboard, Play } from 'lucide-react'
import Dashboard from './pages/Dashboard'
import Library from './pages/Library'
import SearchPage from './pages/SearchPage'
import Studio from './pages/Studio'
import Videos from './pages/Videos'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard', shortcut: '1' },
  { to: '/library', icon: FolderOpen, label: 'Library', shortcut: '2' },
  { to: '/search', icon: Search, label: 'Search', shortcut: '3' },
  { to: '/studio', icon: Clapperboard, label: 'Studio', shortcut: '4' },
  { to: '/videos', icon: Play, label: 'Videos', shortcut: '5' },
]

export default function App() {
  const navigate = useNavigate()

  // Global keyboard shortcuts: Ctrl+1-5 for navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger when typing in inputs
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      if ((e.ctrlKey || e.metaKey) && e.key >= '1' && e.key <= '5') {
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
      {/* Sidebar */}
      <nav className="w-56 shrink-0 border-r border-zinc-800 bg-zinc-950 flex flex-col">
        <div className="flex items-center gap-2.5 px-5 py-5 border-b border-zinc-800">
          <Film className="w-6 h-6 text-violet-400" />
          <span className="text-base font-bold tracking-tight">Video Composer</span>
        </div>
        <div className="flex flex-col gap-0.5 p-3 flex-1">
          {navItems.map(({ to, icon: Icon, label, shortcut }) => (
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
              <kbd className="text-[9px] text-zinc-600 font-mono">⌘{shortcut}</kbd>
            </NavLink>
          ))}
        </div>
        <div className="p-4 border-t border-zinc-800 text-xs text-zinc-600">
          AI-powered video editing
        </div>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto bg-zinc-900">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/library" element={<Library />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/studio" element={<Studio />} />
          <Route path="/videos" element={<Videos />} />
        </Routes>
      </main>
    </div>
  )
}
