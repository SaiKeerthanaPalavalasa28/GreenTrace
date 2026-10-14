import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth'
import { Button, Card, ErrorBox, PageHeader, inputClass, linkButtonClass } from '../components/ui'
import { StatusBadge, TERMINAL, formatQty } from '../components/status'

const STATUSES = ['uploaded', 'processing', 'needs_review', 'approved', 'rejected', 'failed']

export default function BillsPage() {
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const [bills, setBills] = useState([])
  const [recalc, setRecalc] = useState(null)
  const [facilities, setFacilities] = useState([])
  const [filters, setFilters] = useState({ status: '', facility_id: '' })
  const [error, setError] = useState(null)

  useEffect(() => { api('/facilities').then(setFacilities).catch(setError) }, [])

  useEffect(() => {
    let timer
    const load = async () => {
      try {
        const data = await api('/bills', { params: filters })
        setBills(data)
        // Keep refreshing while anything is still being processed.
        if (data.some((b) => !TERMINAL.has(b.status))) timer = setTimeout(load, 3000)
      } catch (err) {
        setError(err)
      }
    }
    load()
    return () => clearTimeout(timer)
  }, [filters, recalc])

  const recalculate = async () => {
    setError(null)
    try {
      setRecalc(await api('/bills/recalculate', { method: 'POST' }))
    } catch (err) {
      setError(err)
    }
  }
  const calcErrors = bills.filter((b) => b.calculation_error).length

  return (
    <div className="space-y-6">
      <PageHeader title="Bills" subtitle="Every uploaded bill as a card. Open one to see where each number was read from.">
        {isAdmin && <Button variant="secondary" onClick={recalculate}>Recalculate approved bills</Button>}
        <Link to="/upload" className={linkButtonClass}>Upload bills</Link>
      </PageHeader>
      <ErrorBox error={error} />
      {recalc && (
        <p className="text-sm text-slate-600">
          Recalculated: {recalc.calculated} changed, {recalc.unchanged} unchanged, {recalc.error} could not be calculated.
        </p>
      )}
      {calcErrors > 0 && (
        <div role="alert" className="rounded-2xl border border-red-200 bg-red-50/80 px-4 py-3 text-sm text-red-800 backdrop-blur">
          {calcErrors} approved bill{calcErrors === 1 ? '' : 's'} could not be calculated and {calcErrors === 1 ? 'is' : 'are'} excluded from totals (usually a missing emission factor for the billing period).
        </div>
      )}
      <Card
        title={`${bills.length} bill${bills.length === 1 ? '' : 's'}`}
        actions={
          <div className="flex flex-wrap gap-2">
            <select className={inputClass + ' !w-auto'} value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
              <option value="">All statuses</option>
              {STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
            </select>
            <select className={inputClass + ' !w-auto'} value={filters.facility_id} onChange={(e) => setFilters({ ...filters, facility_id: e.target.value })}>
              <option value="">All facilities</option>
              {facilities.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
          </div>
        }
      >
        {bills.length === 0 ? (
          <p className="text-sm text-slate-500">No bills yet.</p>
        ) : (
          <div className="masonry">
            {bills.map((b, i) => (
              <article key={b.id} tabIndex={0} role="link"
                className="pin glass rise cursor-pointer rounded-3xl p-5 outline-none"
                style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}
                onClick={() => navigate(`/bills/${b.id}`)} onKeyDown={(e) => e.key === 'Enter' && navigate(`/bills/${b.id}`)}>
                <div className="flex items-start justify-between gap-2">
                  <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl text-lg ${b.utility_type === 'natural_gas' ? 'bg-orange-100' : 'bg-emerald-100'}`} aria-hidden="true">
                    {b.utility_type === 'natural_gas' ? '🔥' : b.utility_type === 'electricity' ? '⚡' : '📄'}
                  </span>
                  <StatusBadge status={b.status} />
                </div>
                <h3 className="mt-3 break-words text-sm font-bold text-slate-900">{b.original_filename}</h3>
                <p className="text-xs text-slate-500">{b.facility_name} · {b.utility_type?.replace('_', ' ') || 'unknown utility'}</p>
                <div className="mt-4 flex items-end justify-between gap-2 border-t border-slate-200/60 pt-3">
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-slate-500">Quantity</div>
                    <div className="text-sm font-semibold tabular-nums">{b.quantity != null ? `${formatQty(b.quantity)} ${b.unit}` : '—'}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-[11px] uppercase tracking-wide text-slate-500">tCO₂e</div>
                    <div className="text-lg font-extrabold tabular-nums text-emerald-800">
                      {b.tco2e != null ? b.tco2e : b.calculation_error ? <span className="text-sm text-red-700" title={b.calculation_error}>not calculated</span> : '—'}
                    </div>
                  </div>
                </div>
                <p className="mt-2 text-xs text-slate-500">{b.billing_period_start ? `${b.billing_period_start} → ${b.billing_period_end ?? '?'}` : 'Period unknown'}</p>
                {b.status === 'needs_review' && b.issue_count > 0 && <p className="mt-1 text-xs font-semibold text-amber-700">{b.issue_count} issue{b.issue_count === 1 ? '' : 's'} to review</p>}
              </article>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
