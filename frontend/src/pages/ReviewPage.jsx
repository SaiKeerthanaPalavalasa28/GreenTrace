import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, fetchBlobUrl, fetchPage } from '../api/client'
import { Button, Card, ErrorBox, inputClass } from '../components/ui'
import { StatusBadge } from '../components/status'
import { issueLabel } from '../components/issues'

const UNITS = ['kWh', 'MWh', 'therm', 'm3', 'scf', 'ccf', 'Mcf', 'MMBtu', 'GJ']

// Decimal strings from the API ("12500.000000") shown without trailing zeros; never via float.
function trim(v) {
  if (v == null) return ''
  const s = String(v)
  return s.includes('.') ? s.replace(/0+$/, '').replace(/\.$/, '') : s
}

function initialForm(bill, e) {
  return {
    facility_id: bill.facility_id,
    utility_type: bill.utility_type || '',
    provider_name: e.provider_name || '',
    account_number: e.account_number || '',
    billing_period_start: e.billing_period_start || '',
    billing_period_end: e.billing_period_end || '',
    quantity: trim(e.quantity),
    unit: e.unit || '',
    meter_previous: trim(e.meter_previous),
    meter_current: trim(e.meter_current),
    meter_multiplier: trim(e.meter_multiplier),
    read_type: e.read_type || 'unknown',
  }
}

export default function ReviewPage() {
  const { billId } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [facilities, setFacilities] = useState([])
  const [form, setForm] = useState(null)
  const [reason, setReason] = useState('')
  const [rejecting, setRejecting] = useState(false)
  const [rejectReason, setRejectReason] = useState('')
  const [accountConflict, setAccountConflict] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)

  const load = useCallback(async () => {
    try {
      const d = await api(`/bills/${billId}`)
      setData(d)
      if (d.extraction) setForm(initialForm(d.bill, d.extraction))
    } catch (err) {
      setError(err)
    }
  }, [billId])

  useEffect(() => {
    setError(null); setAccountConflict(null); setRejecting(false); setReason(''); setSaved(false)
    load()
  }, [load])
  useEffect(() => { api('/facilities').then(setFacilities).catch(setError) }, [])

  const original = useMemo(() => (data?.extraction ? initialForm(data.bill, data.extraction) : null), [data])
  const changes = useMemo(() => {
    if (!form || !original) return {}
    return Object.fromEntries(Object.entries(form).filter(([k, v]) => v !== original[k]))
  }, [form, original])
  const dirty = Object.keys(changes).length > 0

  if (!data) return <div className="space-y-4"><ErrorBox error={error} /><p className="text-sm text-slate-500">Loading…</p></div>
  const { bill, extraction: e } = data

  if (bill.status !== 'needs_review' || !e) {
    return (
      <Card title={bill.original_filename}>
        <p className="text-sm text-slate-600">This bill is <StatusBadge status={bill.status} /> and not in the review queue.</p>
        <div className="mt-3 flex gap-3 text-sm">
          <Link className="text-emerald-700 hover:underline" to={`/bills/${bill.id}`}>View bill</Link>
          <Link className="text-emerald-700 hover:underline" to="/review">Back to queue</Link>
        </div>
      </Card>
    )
  }

  const issues = e.validation_issues_json || []
  const blocking = new Set(e.blocking_codes)
  const corrections = e.corrections_json || {}
  const issuesByField = issues.reduce((acc, i) => ({ ...acc, [i.field]: [...(acc[i.field] || []), i] }), {})

  const goNext = async () => {
    const queue = await api('/review').catch(() => [])
    const next = queue.find((q) => q.bill_id !== bill.id)
    navigate(next ? `/review/${next.bill_id}` : '/review')
  }

  const run = async (fn) => {
    setBusy(true); setError(null); setSaved(false)
    try {
      await fn()
    } catch (err) {
      if (err.status === 409 && err.detail?.issues?.[0]?.code === 'account_other_facility') setAccountConflict(err.detail.issues[0])
      else setError(err)
    } finally {
      setBusy(false)
    }
  }

  const save = () => run(async () => {
    const d = await api(`/extractions/${e.id}/correct`, {
      method: 'POST', body: { changes, reason: reason || null, expected_updated_at: bill.updated_at },
    })
    setData(d); setForm(initialForm(d.bill, d.extraction)); setReason(''); setSaved(true)
  })

  const approve = (extra = {}) => run(async () => {
    await api(`/extractions/${e.id}/approve`, {
      method: 'POST', body: { changes, reason: reason || null, expected_updated_at: bill.updated_at, ...extra },
    })
    await goNext()
  })

  const moveToFacility = () => {
    setForm({ ...form, facility_id: accountConflict.facility_id })
    setAccountConflict(null)
  }

  const reject = () => run(async () => {
    await api(`/extractions/${e.id}/reject`, { method: 'POST', body: { reason: rejectReason, expected_updated_at: bill.updated_at } })
    await goNext()
  })

  const set = (k) => (ev) => setForm({ ...form, [k]: ev.target.value })
  const field = (k, label, input) => (
    <FieldRow key={k} label={label} issues={issuesByField[k === 'billing_period_end' ? 'billing_period_end' : k]}
      blocking={blocking} changed={k in changes} modelValue={corrections[k]?.before}>
      {input}
    </FieldRow>
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/review" className="text-sm text-emerald-700 hover:underline">← Queue</Link>
        <h1 className="truncate text-2xl font-extrabold sm:text-3xl">{bill.original_filename}</h1>
        <StatusBadge status={bill.status} />
        <span className="text-xs text-slate-500">read by {e.model_used} via {e.text_method} · confidence {e.confidence?.toFixed(2)}</span>
      </div>
      <ErrorBox error={error} />

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <PageViewer billId={bill.id} initialPage={e.page_number || 1} snippet={e.raw_text_snippet} />

        <div className="space-y-4">
          {issues.length > 0 && (
            <Card title="Why this bill needs review">
              <ul className="space-y-1.5 text-sm">
                {issues.map((i, n) => (
                  <li key={n} className={`rounded-xl border px-3 py-1.5 ${blocking.has(i.code) ? 'border-red-200 bg-red-50 text-red-900' : 'border-amber-200 bg-amber-50 text-amber-900'}`}>
                    <span className="font-medium">{issueLabel(i.code)}{blocking.has(i.code) && ' (must fix)'}:</span> {i.message}
                  </li>
                ))}
              </ul>
              {e.blocking_codes.length === 0 && (
                <p className="mt-2 text-xs text-slate-500">Approving confirms you have checked these warnings against the bill.</p>
              )}
            </Card>
          )}

          <Card title="Extracted data">
            <div className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2">
              {field('facility_id', 'Facility',
                <select className={inputClass} value={form.facility_id} onChange={set('facility_id')}>
                  {facilities.map((f) => <option key={f.id} value={f.id}>{f.name} ({f.region})</option>)}
                </select>)}
              {field('utility_type', 'Utility',
                <select className={inputClass} value={form.utility_type} onChange={set('utility_type')}>
                  <option value="">Unknown</option>
                  <option value="electricity">Electricity (Scope 2)</option>
                  <option value="natural_gas">Natural gas (Scope 1)</option>
                </select>)}
              {field('provider_name', 'Provider', <input className={inputClass} value={form.provider_name} onChange={set('provider_name')} />)}
              {field('account_number', 'Account number', <input className={inputClass} value={form.account_number} onChange={set('account_number')} />)}
              {field('billing_period_start', 'Period start', <input type="date" className={inputClass} value={form.billing_period_start} onChange={set('billing_period_start')} />)}
              {field('billing_period_end', 'Period end (inclusive)', <input type="date" className={inputClass} value={form.billing_period_end} onChange={set('billing_period_end')} />)}
              {field('quantity', 'Consumption (as printed)',
                <input className={inputClass + ' tabular-nums'} inputMode="decimal" placeholder="blank = use meter readings"
                  value={form.quantity} onChange={set('quantity')} />)}
              {field('unit', 'Unit',
                <>
                  <input className={inputClass} list="unit-options" value={form.unit} onChange={set('unit')} />
                  <datalist id="unit-options">{UNITS.map((u) => <option key={u} value={u} />)}</datalist>
                </>)}
              {field('meter_previous', 'Previous reading', <input className={inputClass + ' tabular-nums'} inputMode="decimal" value={form.meter_previous} onChange={set('meter_previous')} />)}
              {field('meter_current', 'Current reading', <input className={inputClass + ' tabular-nums'} inputMode="decimal" value={form.meter_current} onChange={set('meter_current')} />)}
              {field('meter_multiplier', 'Multiplier', <input className={inputClass + ' tabular-nums'} inputMode="decimal" value={form.meter_multiplier} onChange={set('meter_multiplier')} />)}
              {field('read_type', 'Read type',
                <select className={inputClass} value={form.read_type} onChange={set('read_type')}>
                  <option value="actual">Actual</option>
                  <option value="estimated">Estimated</option>
                  <option value="unknown">Unknown</option>
                </select>)}
            </div>

            <div className="mt-3">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Source snippet (page {e.page_number})</div>
              <div className="mt-1 whitespace-pre-wrap rounded bg-slate-50 px-2 py-1.5 font-mono text-xs">{e.raw_text_snippet}</div>
              {e.notes && <p className="mt-2 text-sm text-amber-800">Model note: {e.notes}</p>}
            </div>

            {dirty && (
              <div className="mt-4">
                <input className={inputClass} placeholder="Reason for correction (recorded in the audit log)" value={reason} onChange={(ev) => setReason(ev.target.value)} />
              </div>
            )}

            {accountConflict && (
              <div role="alert" className="mt-4 rounded-2xl border border-amber-300 bg-amber-50/80 p-3 text-sm text-amber-900">
                <p>Account {form.account_number} is assigned to <b>{accountConflict.facility_name}</b>.</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button variant="secondary" onClick={moveToFacility}>This bill is {accountConflict.facility_name}'s</Button>
                  <Button variant="secondary" onClick={() => { setAccountConflict(null); approve({ remap_account: true }) }}>
                    The account has moved to this facility
                  </Button>
                </div>
              </div>
            )}

            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-200 pt-4">
              <Button onClick={() => approve()} disabled={busy}>{dirty ? 'Save & approve' : 'Approve'}</Button>
              <Button variant="secondary" onClick={save} disabled={busy || !dirty}>Save corrections</Button>
              <Button variant="secondary" onClick={() => setRejecting((v) => !v)} disabled={busy}>Reject…</Button>
              {dirty && <Button variant="secondary" onClick={() => setForm(original)} disabled={busy}>Undo changes</Button>}
              {saved && <span className="text-sm text-emerald-700">Saved. Checks re-run.</span>}
            </div>
            {rejecting && (
              <div className="mt-3 flex flex-wrap gap-2">
                <input className={inputClass + ' flex-1'} placeholder="Why is this bill excluded? (required)" value={rejectReason} onChange={(ev) => setRejectReason(ev.target.value)} />
                <Button onClick={reject} disabled={busy || rejectReason.trim().length < 3}>Confirm reject</Button>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

function FieldRow({ label, issues, blocking, changed, modelValue, children }) {
  const hasBlocking = issues?.some((i) => blocking.has(i.code))
  const ring = hasBlocking ? 'ring-2 ring-red-300' : issues?.length ? 'ring-2 ring-amber-200' : changed ? 'ring-2 ring-blue-200' : ''
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      <div className={`rounded-xl ${ring}`}>{children}</div>
      {modelValue !== undefined && <span className="mt-0.5 block text-xs text-slate-500">Model read: {modelValue ?? '(empty)'}</span>}
    </label>
  )
}

function PageViewer({ billId, initialPage, snippet }) {
  const [page, setPage] = useState(initialPage)
  const [img, setImg] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => setPage(initialPage), [billId, initialPage])
  useEffect(() => {
    let url
    setError(null)
    fetchPage(billId, page).then((p) => { url = p.url; setImg(p) }).catch(setError)
    return () => url && URL.revokeObjectURL(url)
  }, [billId, page])

  const openPdf = async () => {
    try {
      window.open(await fetchBlobUrl(`/bills/${billId}/file`), '_blank', 'noopener')
    } catch (err) {
      setError(err)
    }
  }

  const note = {
    found: 'Source snippet highlighted.',
    not_found: 'The source snippet could not be located on this page. Check the value carefully.',
    no_text_layer: 'Scanned page: the snippet cannot be highlighted. Compare by eye.',
  }[img?.highlight]

  return (
    <div className="glass flex flex-col rounded-3xl lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)]">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-2 text-sm">
        <button className="rounded px-2 py-0.5 hover:bg-slate-100 disabled:text-slate-300" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page">‹</button>
        <span>Page {page}{img ? ` of ${img.pageCount}` : ''}</span>
        <button className="rounded px-2 py-0.5 hover:bg-slate-100 disabled:text-slate-300" disabled={!img || page >= img.pageCount} onClick={() => setPage(page + 1)} aria-label="Next page">›</button>
        <button className="ml-auto text-emerald-700 hover:underline" onClick={openPdf}>Open PDF</button>
      </div>
      {page === initialPage && snippet && note && (
        <p className={`px-3 py-1.5 text-xs ${img?.highlight === 'found' ? 'text-slate-500' : 'bg-amber-50 text-amber-800'}`}>{note}</p>
      )}
      <ErrorBox error={error} />
      <div className="min-h-96 overflow-auto bg-slate-100 p-2">
        {img ? <img src={img.url} alt={`Bill page ${page}`} className="mx-auto max-w-full bg-white shadow" /> : <p className="p-4 text-sm text-slate-500">Rendering page…</p>}
      </div>
    </div>
  )
}
