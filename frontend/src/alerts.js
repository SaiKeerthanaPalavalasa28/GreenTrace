// Sound alerts made with the Web Audio API (no audio files).
// danger   -> harsh beeping for 5 seconds
// moderate -> a two-note chime, repeated
// green    -> a single bright "ting"
// Browsers keep audio locked until the user has interacted with the page (signing in counts).

let ctx = null

function audio() {
  const AC = window.AudioContext || window.webkitAudioContext
  if (!AC) return null
  if (!ctx) ctx = new AC()
  if (ctx.state === 'suspended') ctx.resume().catch(() => {})
  return ctx
}

function tone(c, { freq, start, dur, type = 'sine', gain = 0.25, attack = 0.01 }) {
  const osc = c.createOscillator()
  const g = c.createGain()
  osc.type = type
  osc.frequency.setValueAtTime(freq, start)
  g.gain.setValueAtTime(0.0001, start)
  g.gain.exponentialRampToValueAtTime(gain, start + attack)
  g.gain.exponentialRampToValueAtTime(0.0001, start + dur)
  osc.connect(g).connect(c.destination)
  osc.start(start)
  osc.stop(start + dur + 0.02)
}

export const ZONE_DURATION_MS = { danger: 5000, moderate: 2500, green: 2000 }

// Returns false when the browser blocked audio (the caller shows a "tap to enable sound" hint).
export function playZoneSound(zone) {
  const c = audio()
  if (!c || c.state !== 'running') return false
  const t0 = c.currentTime + 0.05
  if (zone === 'danger') {
    for (let i = 0; i < 10; i++) tone(c, { freq: 880, start: t0 + i * 0.5, dur: 0.3, type: 'square', gain: 0.22, attack: 0.005 })
  } else if (zone === 'moderate') {
    for (let i = 0; i < 2; i++) {
      tone(c, { freq: 523, start: t0 + i * 0.9, dur: 0.35, type: 'triangle' })
      tone(c, { freq: 659, start: t0 + i * 0.9 + 0.3, dur: 0.5, type: 'triangle' })
    }
  } else if (zone === 'green') {
    tone(c, { freq: 1568, start: t0, dur: 1.2, gain: 0.3 })
    tone(c, { freq: 2349, start: t0, dur: 0.7, gain: 0.12 })
  }
  return true
}

export function unlockAudio() {
  const c = audio()
  return Boolean(c && c.state === 'running')
}

export const ZONE_STYLE = {
  green: { color: '#1f7549', soft: '#e3f4ea', label: 'On track', message: 'Emissions are within budget.' },
  moderate: { color: '#d97a00', soft: '#fff1dc', label: 'Moderate', message: 'Emissions are getting close to the budget.' },
  danger: { color: '#c62828', soft: '#fde6e6', label: 'Danger zone', message: 'Emissions are at or over the budget!' },
  unset: { color: '#6b7c72', soft: '#eff5f1', label: 'No budget set', message: 'Set a budget to see your status.' },
}
