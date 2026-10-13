import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../auth'
import { api, fetchBlobUrl } from '../api/client'
import { Button, Card, ErrorBox } from '../components/ui'
import { StatusBadge, TERMINAL, formatQty } from '../components/status'
import EmissionsTrace from '../components/EmissionsTrace'

// Read-only view of a bill and its extraction. Editing and approval arrive with the review queue (milestone 4).
export default function BillDetailPage() {
  const { id } = useParams()
  const { isAdmin } = useAuth()
  const [reopenReason, setReopenReason] = useState('')
  const [data, setData] = useState(null)
  const [pdfUrl, setPdfUrl] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let timer
    const load = async () => {
      try {
        const d = await api(`/bills/${id}`)
        setData(d)
        if (!TERMINAL.has(d.bill.status)) timer = setTimeout(load, 2000)
      } catch (err) {
        setError(err)
      }
    }
    load()
    return () => clearTimeout(timer)
  }, [id])

  useEffect(() => {
    let url
    fetchBlobUrl(`/bills/${id}/file`).then((u) => { url = u; setPdfUrl(u) }).catch(setError)
    return () => url && URL.revokeObjectURL(url)
  }, [id])

  const reprocess = async () => {
    setError(null)
    try {
      await api(`/bills/${id}/reprocess`, { method: 'POST' })
      setData(await api(`/bills/${id}`))
    } catch (err) {
      setError(err)
    }
  }

  const reopen = async () => {
    setError(null)
    try {
      setData(await api(`/bills/${id}/reopen`, { method: 'POST', body: { reason: reopenReason } }))
      setReopenReason('')
    } catch (err) {
      setError(err)
    }
  }

  if (!data) return <div className="space-y-4"><ErrorBox error={error} /><p className="text-sm text-slate-500">Loading…</p></div>
  const { bill, extraction: e, facility_name } = data
  const issues = e?.validation_issues_json || []
  const page = e?.page_number ? `#page=${e.page_number}` : ''

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/bills" className="text-sm text-emerald-700 hover:underline">← Bills</Link>
        <h1 className="truncate text-xl font-semibold">{bill.original_filename}</h1>
        <StatusBadge status={bill.status} />
      </div>
      <ErrorBox error={error} />

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-2">
        <div className="h-[70vh] min-h-96 overflow-hidden rounded-lg border border-slate-200 bg-white">
          {pdfUrl ? <iframe title="Bill PDF" src={pdfUrl + page} className="h-full w-full" /> : <p className="p-4 text-sm text-slate-500">Loading PDF…</p>}
        </div>

        <div className="space-y-4">
          {bill.status === 'failed' && (
            <Card title="Processing failed">
              <p className="text-sm text-red-800">{bill.failure_reason}</p>
              <Button className="mt-3" onClick={reprocess}>Reprocess</Button>
            </Card>
          )}

          <EmissionsTrace billId={id} refreshKey={`${bill.status}-${bill.updated_at}`} />

          {issues.length > 0 && (
            <Card title={`${issues.length} issue${issues.length === 1 ? '' : 's'} to review`}>
              <ul className="space-y-2 text-sm">
                {issues.map((i, n) => (
                  <li key={n} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">
                    <span className="font-mono text-xs text-amber-700">{i.code}</span>
                    <div>{i.message}</div>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card title="Extracted data">
            {!e ? (
              <p className="text-sm text-slate-500">{TERMINAL.has(bill.status) ? 'No extraction.' : 'Extraction in progress…'}</p>
            ) : (
              <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                <Item label="Facility">{facility_name}</Item>
                <Item label="Utility">{bill.utility_type?.replace('_', ' ') || 'unknown'}</Item>
                <Item label="Provider">{e.provider_name}</Item>
                <Item label="Account number">{e.account_number}</Item>
                <Item label="Billing period">{e.billing_period_start} → {e.billing_period_end}</Item>
                <Item label="Quantity (as printed)">{e.quantity != null ? `${formatQty(e.quantity)} ${e.unit}` : `not printed (${e.unit || 'no unit'})`}</Item>
                <Item label="Meter readings">
                  {e.meter_previous != null || e.meter_current != null
                    ? `${formatQty(e.meter_previous) || '?'} → ${formatQty(e.meter_current) || '?'} × ${formatQty(e.meter_multiplier) || '(no multiplier)'}`
                    : null}
                </Item>
                <Item label="Read type">{e.read_type}</Item>
                <Item label="Confidence">{e.confidence != null ? e.confidence.toFixed(2) : null}</Item>
                <Item label="Source">page {e.page_number} · {e.text_method} · {e.model_used}</Item>
                <div className="sm:col-span-2">
                  <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Source snippet</dt>
                  <dd className="mt-1 whitespace-pre-wrap rounded bg-slate-50 px-2 py-1.5 font-mono text-xs">{e.raw_text_snippet}</dd>
                </div>
                {e.notes && <div className="sm:col-span-2"><Item label="Model notes">{e.notes}</Item></div>}
              </dl>
            )}
            {bill.status === 'needs_review' && (
              <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-slate-200 pt-3">
                <Link to={`/review/${bill.id}`} className="rounded-md bg-emerald-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-800">Review this bill</Link>
                <Button variant="secondary" onClick={reprocess}>Re-run extraction</Button>
                <span className="text-xs text-slate-500">Re-running replaces the extraction (and any corrections) with a fresh one.</span>
              </div>
            )}
            {isAdmin && ['approved', 'rejected'].includes(bill.status) && (
              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-200 pt-3">
                <input className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm" placeholder="Reason to reopen (e.g. supplier issued a revised bill)"
                  value={reopenReason} onChange={(ev) => setReopenReason(ev.target.value)} />
                <Button variant="secondary" onClick={reopen} disabled={reopenReason.trim().length < 3}>Reopen for review</Button>
                {bill.status === 'approved' && <span className="w-full text-xs text-slate-500">Its emissions leave the totals until it is approved again.</span>}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

function Item({ label, children }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-0.5 break-words">{children ?? <span className="text-slate-400">—</span>}</dd>
    </div>
  )
}
