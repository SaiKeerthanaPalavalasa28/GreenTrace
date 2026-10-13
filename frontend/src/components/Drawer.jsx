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
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} />
      <div ref={panel} tabIndex={-1}
        className="relative flex h-full w-full max-w-xl flex-col bg-slate-50 shadow-xl outline-none"
        style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}>
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3">
          <h2 className="truncate text-base font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100" aria-label="Close">✕</button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  )
}
