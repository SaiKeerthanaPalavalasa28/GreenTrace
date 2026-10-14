import { useEffect, useState } from 'react'
import { api, fetchBlobUrl } from '../api/client'
import { Button, Card, ErrorBox, inputClass } from '../components/ui'
import { formatT } from '../components/status'

function lastDayOfMonth(ym) {
  const [y, m] = ym.split('-').map(Number)
  return new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10)
}

async function download(path, filename) {
  const url = await fetchBlobUrl(path)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10000)
}

export default function ReportsPage() {
  const [periods, setPeriods] = useState(null)
  const [form, setForm] = useState({ year: '', from: '', to: '', label: '' })
  const [reports, setReports] = useState([])
  const [latest, setLatest] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [verified, setVerified] = useState({})

  const load = () => api('/reports').then(setReports).catch(setError)
  useEffect(() => {
    api('/dashboard/periods').then((p) => { setPeriods(p); setForm((f) => ({ ...f, year: p.default })) }).catch(setError)
    load()
  }, [])

  const range = () => {
    if (form.year === 'custom') {
      if (!form.from || !form.to || form.to < form.from) return null
      return { period_start: `${form.from}-01`, period_end: lastDayOfMonth(form.to) }
    }
    const y = periods?.years.find((x) => x.label === form.year)
    return y ? { period_start: y.start, period_end: y.end } : null
  }

  const generate = async () => {
    const r = range()
    if (!r) return
    setBusy(true); setError(null)
    try {
      const rep = await api('/reports', { method: 'POST', body: { ...r, label: form.label || null } })
      setLatest(rep)
      load()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const verify = async (id) => {
    try {
      setVerified((v) => ({ ...v, [id]: null }))
      const res = await api(`/reports/${id}/verify`, { method: 'POST' })
      setVerified((v) => ({ ...v, [id]: res }))
    } catch (err) {
      setError(err)
    }
  }

  const fileBase = (r) => `GHG-report-${r.reporting_period_label.replace(/[^A-Za-z0-9]+/g, '-')}-${r.id.slice(0, 8)}${r.is_draft ? '-DRAFT' : ''}`
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-extrabold sm:text-3xl">Reports</h1>
      <p className="max-w-3xl text-sm text-slate-600">
        A report freezes the approved data for a period into a snapshot and renders an inspector-ready PDF from it:
        cover, executive summary, breakdowns by month and facility, methodology with every emission factor and its
        source, and appendices listing every bill, every manual correction and every bill left out. The stored
        snapshot reproduces the PDF exactly, even after the data changes.
      </p>
      <ErrorBox error={error} />

      <Card title="Generate a report">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium text-slate-600">Reporting period</span>
            <select className={inputClass + ' !w-auto'} value={form.year} onChange={set('year')}>
              {periods?.years.map((y) => <option key={y.label} value={y.label}>{y.label}{y.has_data ? '' : ' (no data)'}</option>)}
              <option value="custom">Custom months…</option>
            </select>
          </label>
          {form.year === 'custom' && (
            <>
              <label className="text-sm"><span className="mb-1 block text-xs font-medium text-slate-600">From</span>
                <input type="month" className={inputClass + ' !w-auto'} value={form.from} onChange={set('from')} /></label>
              <label className="text-sm"><span className="mb-1 block text-xs font-medium text-slate-600">To</span>
                <input type="month" className={inputClass + ' !w-auto'} value={form.to} onChange={set('to')} /></label>
            </>
          )}
          <label className="text-sm">
            <span className="mb-1 block text-xs font-medium text-slate-600">Label (optional)</span>
            <input className={inputClass + ' !w-48'} placeholder="e.g. BRSR FY2023-24" value={form.label} onChange={set('label')} />
          </label>
          <Button onClick={generate} disabled={busy || !range()}>{busy ? 'Generating…' : 'Generate report'}</Button>
        </div>

        {latest && (
          <div className={`mt-4 rounded-2xl border px-4 py-3 text-sm ${latest.is_draft ? 'border-amber-300 bg-amber-50' : 'border-emerald-200 bg-emerald-50'}`}>
            <div className="font-semibold text-slate-900">
              {latest.is_draft ? 'Draft generated: totals are incomplete' : 'Complete report generated'} ({latest.reporting_period_label})
            </div>
            <div className="mt-1 text-slate-700">
              Total {formatT(latest.summary.total_t)} tCO₂e · Scope 1 {formatT(latest.summary.scope1_t)} t · Scope 2 {formatT(latest.summary.scope2_t)} t
              · {latest.summary.bills_included} bills
              {latest.is_draft && <> · <b>{latest.summary.bills_excluded} bill(s) not included</b>: listed in Appendix C. Resolve them and regenerate before submitting.</>}
            </div>
            <div className="mt-2 flex gap-2">
              <Button onClick={() => download(`/reports/${latest.id}/download`, `${fileBase(latest)}.pdf`).catch(setError)}>Download PDF</Button>
            </div>
          </div>
        )}
      </Card>

      <Card title={`${reports.length} report${reports.length === 1 ? '' : 's'}`}>
        {reports.length === 0 ? <p className="text-sm text-slate-500">No reports yet.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-slate-500">
                <tr>
                  <th className="py-2 pr-4 font-medium">Period</th>
                  <th className="py-2 pr-4 font-medium">Generated (UTC)</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Files</th>
                  <th className="py-2 font-medium">Integrity</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 align-top">
                {reports.map((r) => {
                  const v = verified[r.id]
                  const allOk = v && v.pdf_matches_recorded_hash && v.snapshot_matches_recorded_hash && v.rerender_matches
                  return (
                    <tr key={r.id}>
                      <td className="py-2 pr-4">
                        <div className="font-medium">{r.reporting_period_label}</div>
                        <div className="text-xs text-slate-500">{r.period_start} → {r.period_end}</div>
                      </td>
                      <td className="whitespace-nowrap py-2 pr-4 text-xs">{r.generated_at?.slice(0, 19).replace('T', ' ')}</td>
                      <td className="py-2 pr-4">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${r.is_draft ? 'bg-amber-50 text-amber-800' : 'bg-emerald-50 text-emerald-800'}`}>
                          {r.is_draft ? 'Draft' : 'Complete'}
                        </span>
                      </td>
                      <td className="whitespace-nowrap py-2 pr-4">
                        <button className="text-emerald-700 hover:underline" onClick={() => download(`/reports/${r.id}/download`, `${fileBase(r)}.pdf`).catch(setError)}>PDF</button>
                        <span className="mx-2 text-slate-300">|</span>
                        <button className="text-emerald-700 hover:underline" onClick={() => download(`/reports/${r.id}/snapshot`, `${fileBase(r)}.json`).catch(setError)}>Snapshot JSON</button>
                      </td>
                      <td className="py-2 text-xs">
                        {v === undefined && <button className="text-emerald-700 hover:underline" onClick={() => verify(r.id)}>Verify</button>}
                        {v === null && <span className="text-slate-500">Checking…</span>}
                        {v && (
                          <div className={allOk ? 'text-emerald-800' : 'text-red-700'}>
                            <div className="font-medium">{allOk ? '✓ Verified: PDF and snapshot intact; re-render identical' : '✗ Verification failed'}</div>
                            {!allOk && (
                              <ul className="list-inside list-disc">
                                {!v.pdf_matches_recorded_hash && <li>Stored PDF does not match its recorded hash</li>}
                                {!v.snapshot_matches_recorded_hash && <li>Snapshot does not match its recorded hash</li>}
                                {!v.rerender_matches && <li>Re-rendering the snapshot gives a different PDF (renderer versions may have changed)</li>}
                              </ul>
                            )}
                            <div className="mt-0.5 font-mono text-[10px] text-slate-500">PDF sha256 {v.pdf_sha256.slice(0, 16)}…</div>
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
