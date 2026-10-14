import { useEffect, useRef } from 'react'

export default function Drawer({ title, onClose, children }) {
  const panel = useRef(null)
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    panel.current?.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-label={title}>
      <div className="fade absolute inset-0 bg-emerald-950/30 backdrop-blur-sm" onClick={onClose} />
      <div ref={panel} tabIndex={-1}
        className="glass-strong slide-in relative m-2 flex h-[calc(100%-1rem)] w-full max-w-xl flex-col overflow-hidden rounded-3xl outline-none"
        style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}>
        <div className="flex items-center justify-between gap-3 border-b border-slate-200/60 px-5 py-4">
          <h2 className="truncate text-base font-bold">{title}</h2>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-full text-slate-500 transition-colors hover:bg-slate-900/10" aria-label="Close">✕</button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  )
}
