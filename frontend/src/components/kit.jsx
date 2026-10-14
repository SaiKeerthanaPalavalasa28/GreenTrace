import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { ZONE_STYLE } from '../alerts'

/* ------------------------------------------------------------------ icons (stroke, 24px grid) */
const PATHS = {
  dashboard: 'M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm10 0h6V11h-6v9Zm0-16v5h6V4h-6Z',
  flame: 'M12 3c1 3 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-6 1-9Z',
  bolt: 'M13 2 4 14h7l-1 8 9-12h-7l1-8Z',
  globe: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-9-9h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18',
  report: 'M7 3h7l5 5v13H7V3Zm7 0v5h5M10 13h6M10 17h6',
  team: 'M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm-6 9a6 6 0 0 1 12 0M17 11a2.5 2.5 0 1 0 0-5M21 19a5 5 0 0 0-4-4.9',
  upload: 'M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3',
  logout: 'M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 8l-4 4 4 4M6 12h10',
  check: 'm5 12 5 5 9-10',
  alert: 'M12 4 2.5 20h19L12 4Zm0 6v5m0 3v.01',
  bell: 'M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6Zm4 9a2 2 0 0 0 4 0',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z',
  edit: 'M4 20h4L19 9l-4-4L4 16v4ZM14 6l4 4',
  trash: 'M5 7h14M10 7V4h4v3m-8 0 1 13h10l1-13M10 11v6M14 11v6',
  sparkle: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z',
  lock: 'M6 11h12v9H6v-9Zm3 0V8a3 3 0 0 1 6 0v3',
}

export function Icon({ name, className = 'h-5 w-5', strokeWidth = 1.8 }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  )
}

/* ------------------------------------------------------------------ animated number */
export function CountUp({ value, decimals = 2, duration = 1100 }) {
  const [shown, setShown] = useState(0)
  useEffect(() => {
    if (value == null) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce) { setShown(value); return }
    let raf
    const start = performance.now()
    const tick = (now) => {
      const p = Math.min((now - start) / duration, 1)
      setShown(value * (1 - Math.pow(1 - p, 4)))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, duration])
  if (value == null) return '-'
  return shown.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

/* ------------------------------------------------------------------ progress ring */
export function Ring({ percent, zone, size = 200, stroke = 14, children }) {
  const st = ZONE_STYLE[zone] || ZONE_STYLE.unset
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const [p, setP] = useState(0)
  useEffect(() => {
    const id = requestAnimationFrame(() => setP(Math.min(percent ?? 0, 100)))
    return () => cancelAnimationFrame(id)
  }, [percent])
  return (
    <div className="relative shrink-0" style={{ width: size, height: size, '--glow': `${st.color}66` }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="ring-glow -rotate-90" role="img" aria-label={percent == null ? 'No budget set' : `${Math.round(percent)} percent of budget used`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={st.soft} strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={st.color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c - (p / 100) * c} className="ring-arc" />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div>
    </div>
  )
}

/* ------------------------------------------------------------------ leaf illustration */
export function LeafArt({ className = 'h-28 w-28' }) {
  return (
    <svg viewBox="0 0 120 120" className={`float-slow ${className}`} fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="lg1" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#8fd3ae" /><stop offset="1" stopColor="#1f7549" /></linearGradient>
        <linearGradient id="lg2" x1="1" y1="0" x2="0" y2="1"><stop stopColor="#c9ecd8" /><stop offset="1" stopColor="#4ea877" /></linearGradient>
      </defs>
      <circle cx="60" cy="60" r="52" fill="#eaf5ee" />
      <path d="M60 98c-2-26 4-48 30-62-2 28-12 50-30 62Z" fill="url(#lg1)" />
      <path d="M60 98C48 80 38 66 20 58c2 22 14 36 40 40Z" fill="url(#lg2)" />
      <path d="M60 98c0-22 4-38 14-52" stroke="#fff" strokeOpacity=".7" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="glass rise flex flex-col items-center rounded-[1.75rem] px-6 py-10 text-center">
      <LeafArt />
      <h3 className="mt-3 text-lg">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-slate-600">{children}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

/* ------------------------------------------------------------------ modal */
export function Modal({ title, onClose, children, footer }) {
  const ref = useRef(null)
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    ref.current?.querySelector('input,select,button')?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-[60] flex items-end justify-center p-4 sm:items-center" role="dialog" aria-modal="true" aria-label={title}>
      <div className="fade absolute inset-0 bg-emerald-950/30 backdrop-blur-sm" onClick={onClose} />
      <div ref={ref} className="pop glass-strong relative w-full max-w-md rounded-[1.75rem] p-6">
        <h3 className="text-xl">{title}</h3>
        <div className="mt-3 text-sm text-slate-700">{children}</div>
        {footer && <div className="mt-5 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ toasts + confirm */
const UiContext = createContext(null)
export const useUi = () => useContext(UiContext)

export function UiProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const [confirm, setConfirm] = useState(null)
  const toast = useCallback((message, kind = 'success') => {
    const id = Math.random().toString(36).slice(2)
    setToasts((t) => [...t, { id, message, kind }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200)
  }, [])
  // ask({title, body, confirmLabel, danger}) -> Promise<boolean>
  const ask = useCallback((opts) => new Promise((resolve) => setConfirm({ ...opts, resolve })), [])
  const close = (v) => { confirm.resolve(v); setConfirm(null) }
  return (
    <UiContext.Provider value={{ toast, ask }}>
      {children}
      <div className="pointer-events-none fixed bottom-24 left-1/2 z-[70] flex -translate-x-1/2 flex-col items-center gap-2 lg:bottom-6" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast-in pointer-events-auto flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-semibold text-white shadow-xl ${t.kind === 'error' ? 'bg-red-700' : 'bg-emerald-900'}`}>
            <Icon name={t.kind === 'error' ? 'alert' : 'check'} className="h-4 w-4" strokeWidth={2.4} />{t.message}
          </div>
        ))}
      </div>
      {confirm && (
        <Modal title={confirm.title} onClose={() => close(false)} footer={
          <>
            <button onClick={() => close(false)} className="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100">Cancel</button>
            <button onClick={() => close(true)} className={`rounded-full px-5 py-2 text-sm font-semibold text-white ${confirm.danger ? 'bg-red-600 hover:bg-red-700' : 'btn-primary'}`}>{confirm.confirmLabel || 'Confirm'}</button>
          </>
        }>{confirm.body}</Modal>
      )}
    </UiContext.Provider>
  )
}
