// Chart tokens. Categorical slots come from the validated reference palette (dataviz skill,
// references/palette.md) in fixed order; validated with scripts/validate_palette.js
// (light mode, adjacent pairs). Colors follow the ENTITY: Scope 1 is always slot 1 and
// Scope 2 always slot 2, in every chart, regardless of which has the larger value.
// Brand-matched: Scope 1 (gas combustion) = ember, Scope 2 (grid electricity) = forest green,
// third slot = deep lake blue. Hue AND lightness differ so they stay apart for colour-blind viewers.
export const SERIES = ['#d9622b', '#1f7549', '#2f6f95']
export const OTHER = '#c3c2b7' // neutral for the folded "Other" slice - not a categorical hue
export const SCOPE_COLOR = { 1: SERIES[0], 2: SERIES[1] }

export const SURFACE = '#fbfcf8' // card surface; used for the 2px gap between touching marks
export const INK = { primary: '#1c1b18', secondary: '#5c5a51', muted: '#79776c' }
export const GRID = '#e1dfd6'
export const AXIS = '#c3c2b7'
export const STATUS = { warning: '#fab219', critical: '#d03b3b', good: '#0ca30c' }

// Compact axis ticks: 0 / 950 / 1.2K / 12K
export function compact(n) {
  const abs = Math.abs(n)
  if (abs >= 1e6) return `${+(n / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${+(n / 1e3).toFixed(1)}K`
  return `${+n.toFixed(abs < 10 ? 2 : 0)}`
}

// "2024-03" -> "Mar 24"
export function monthLabel(m) {
  const [y, mo] = m.split('-').map(Number)
  return `${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][mo - 1]} ${String(y).slice(2)}`
}
