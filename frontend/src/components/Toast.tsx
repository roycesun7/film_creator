import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
  type ReactNode,
} from 'react'
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react'

type ToastType = 'success' | 'error' | 'info'

interface Toast {
  id: number
  message: string
  type: ToastType
  exiting: boolean
}

interface ToastContextValue {
  toast: (message: string, type: ToastType) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

let nextId = 0

const icons = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
}

const styles = {
  success: 'border-emerald-500/30 bg-emerald-950/80 text-emerald-200',
  error: 'border-red-500/30 bg-red-950/80 text-red-200',
  info: 'border-zinc-500/30 bg-zinc-800/80 text-zinc-200',
}

const iconStyles = {
  success: 'text-emerald-400',
  error: 'text-red-400',
  info: 'text-zinc-400',
}

function ToastItem({
  toast,
  onClose,
}: {
  toast: Toast
  onClose: (id: number) => void
}) {
  const Icon = icons[toast.type]
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    // Trigger enter animation on next frame
    requestAnimationFrame(() => setVisible(true))
  }, [])

  const className = [
    'flex items-center gap-3 px-4 py-3 rounded-lg border shadow-lg backdrop-blur-sm',
    'transition-all duration-300 ease-in-out pointer-events-auto min-w-[300px] max-w-[420px]',
    styles[toast.type],
    visible && !toast.exiting
      ? 'opacity-100 translate-x-0'
      : 'opacity-0 translate-x-8',
  ].join(' ')

  return (
    <div ref={ref} className={className}>
      <Icon className={`w-5 h-5 shrink-0 ${iconStyles[toast.type]}`} />
      <span className="text-sm flex-1">{toast.message}</span>
      <button
        onClick={() => onClose(toast.id)}
        className="shrink-0 p-0.5 rounded hover:bg-white/10 transition-colors"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const removeToast = useCallback((id: number) => {
    // Mark as exiting to trigger exit animation
    setToasts((prev) =>
      prev.map((t) => (t.id === id ? { ...t, exiting: true } : t))
    )
    // Remove after animation completes
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 300)
  }, [])

  const toast = useCallback(
    (message: string, type: ToastType) => {
      const id = nextId++
      setToasts((prev) => [...prev, { id, message, type, exiting: false }])
      setTimeout(() => removeToast(id), 4000)
    },
    [removeToast]
  )

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col-reverse gap-2 pointer-events-none">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onClose={removeToast} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): (message: string, type: ToastType) => void {
  const ctx = useContext(ToastContext)
  if (!ctx) {
    throw new Error('useToast must be used within a ToastProvider')
  }
  return ctx.toast
}
