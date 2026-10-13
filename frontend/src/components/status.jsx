export const TERMINAL = new Set(['needs_review', 'approved', 'rejected', 'failed'])

const STYLES = {
  uploaded: ['Queued', 'bg-slate-100 text-slate-700'],
  processing: ['Processing…', 'bg-blue-50 text-blue-800'],
  needs_review: ['Needs review', 'bg-amber-50 text-amber-800'],
  approved: ['Approved', 'bg-emerald-50 text-emerald-800'],
  rejected: ['Rejected', 'bg-slate-100 text-slate-500'],
  failed: ['Failed', 'bg-red-50 text-red-800'],
  duplicate: ['Duplicate', 'bg-slate-100 text-slate-600'],
}

export function StatusBadge({ status }) {
  const [label, cls] = STYLES[status] || [status, 'bg-slate-100 text-slate-700']
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status === 'processing' && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-600" />}
      {label}
    </span>
  )
}

export function formatQty(q) {
  if (q == null) return ''
  const [int, frac = ''] = q.split('.')
  const f = frac.replace(/0+$/, '')
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (f ? `.${f}` : '')
}


// Tonnes from the server are already rounded to 3 dp: add thousands separators, keep every decimal
// so a column of figures has consistent precision (28.060, not 28.06).
export function formatT(t) {
  if (t == null) return ''
  const [int, frac] = t.split('.')
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (frac ? `.${frac}` : '')
}
