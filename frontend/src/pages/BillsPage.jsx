import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth'
import { Button, Card, ErrorBox, inputClass } from '../components/ui'
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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Bills</h1>
        <div className="flex gap-2">
          {isAdmin && <Button variant="secondary" onClick={recalculate}>Recalculate approved bills</Button>}
          <Link to="/upload" className="rounded-md bg-emerald-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-800">Upload bills</Link>
        </div>
      </div>
      <ErrorBox error={error} />
      {recalc && (
        <p className="text-sm text-slate-600">
          Recalculated: {recalc.calculated} changed, {recalc.unchanged} unchanged, {recalc.error} could not be calculated.
        </p>
      )}
      {calcErrors > 0 && (
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
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
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-slate-500">
                <tr>
                  <th className="py-2 pr-4 font-medium">File</th>
                  <th className="py-2 pr-4 font-medium">Facility</th>
                  <th className="py-2 pr-4 font-medium">Utility</th>
                  <th className="py-2 pr-4 font-medium">Period</th>
                  <th className="py-2 pr-4 text-right font-medium">Quantity</th>
                  <th className="py-2 pr-4 text-right font-medium">tCO₂e</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {bills.map((b) => (
                  <tr key={b.id} className="cursor-pointer hover:bg-slate-50" onClick={() => navigate(`/bills/${b.id}`)}>
                    <td className="max-w-xs truncate py-2 pr-4 font-medium">{b.original_filename}</td>
                    <td className="py-2 pr-4">{b.facility_name}</td>
                    <td className="py-2 pr-4">{b.utility_type?.replace('_', ' ') || '—'}</td>
                    <td className="whitespace-nowrap py-2 pr-4 text-xs">{b.billing_period_start ? `${b.billing_period_start} → ${b.billing_period_end ?? '?'}` : '—'}</td>
                    <td className="whitespace-nowrap py-2 pr-4 text-right tabular-nums">{b.quantity != null ? `${formatQty(b.quantity)} ${b.unit}` : '—'}</td>
                    <td className="whitespace-nowrap py-2 pr-4 text-right tabular-nums">
                      {b.tco2e != null ? b.tco2e : b.calculation_error ? <span className="text-red-700" title={b.calculation_error}>not calculated</span> : '—'}
                    </td>
                    <td className="py-2 pr-4">
                      <StatusBadge status={b.status} />
                      {b.status === 'needs_review' && b.issue_count > 0 && <span className="ml-2 text-xs text-amber-700">{b.issue_count} issue{b.issue_count === 1 ? '' : 's'}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
