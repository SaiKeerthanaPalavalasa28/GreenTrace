import { useEffect, useRef, useState } from 'react'
import { ZONE_DURATION_MS, ZONE_STYLE, playZoneSound, unlockAudio } from '../alerts'

// Full-screen colour flash + sound for the overall zone. `trigger` changes -> plays again.
export default function ZoneOverlay({ zone, percent, trigger }) {
  const [visible, setVisible] = useState(false)
  const [muted, setMuted] = useState(false)
  const timer = useRef(null)

  useEffect(() => {
    if (!trigger || !zone || zone === 'unset') return
    setVisible(true)
    setMuted(!playZoneSound(zone))
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setVisible(false), ZONE_DURATION_MS[zone])
    return () => clearTimeout(timer.current)
  }, [trigger, zone])

  if (!visible) return null
  const st = ZONE_STYLE[zone]
  const enableSound = () => {
    unlockAudio()
    setMuted(!playZoneSound(zone))
  }
  return (
    <div
      role="alertdialog"
      aria-live="assertive"
      aria-label={`${st.label}: ${st.message}`}
      onClick={() => setVisible(false)}
      className="fixed inset-0 z-50 flex cursor-pointer items-center justify-center p-6"
    >
      <div className={`absolute inset-0 ${zone === 'danger' ? 'zone-pulse' : 'fade'}`} style={{ background: st.color, opacity: zone === 'danger' ? 0.85 : zone === 'moderate' ? 0.7 : 0.55 }} />
      <div className="relative max-w-md rounded-3xl bg-white px-8 py-7 text-center shadow-2xl">
        <div className="text-5xl font-extrabold" style={{ color: st.color }}>
          {zone === 'danger' ? '⚠' : zone === 'moderate' ? '!' : '✓'}
        </div>
        <h2 className="mt-2 text-2xl font-extrabold" style={{ color: st.color }}>{st.label}</h2>
        <p className="mt-1 text-slate-700">{st.message}</p>
        {percent != null && <p className="mt-2 text-sm font-semibold text-slate-600">{percent.toFixed(0)}% of the combined budget used</p>}
        {muted && (
          <button
            onClick={(e) => { e.stopPropagation(); enableSound() }}
            className="mt-4 rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white"
          >
            🔈 Tap to enable sound
          </button>
        )}
        <p className="mt-3 text-xs text-slate-500">Click anywhere to dismiss</p>
      </div>
    </div>
  )
}
