import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Card } from './ui'
import { formatQty } from './status'

// Bill -> extraction -> factor -> formula -> result, for every pro-rated segment.
export default function EmissionsTrace({ billId, refreshKey }) {
  const [trace, setTrace] = useState(null)
  const [open, setOpen] = useState(null)
  const [showHistory, setShowHistory] = useState(false)

  useEffect(() => { api(`/bills/${billId}/trace`).then(setTrace).catch(() => setTrace(null)) }, [billId, refreshKey])
  if (!trace) return null
  const { bill, records, total_tco2e, total_kgco2e, superseded_records } = trace

  if (bill.status !== 'approved' && records.length === 0) return null

  return (
    <Card title="Emissions">
      {bill.calculation_error && (
        <div role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          <div className="font-medium">Not calculated: excluded from totals</div>
          <div>{bill.calculation_error}</div>
        </div>
      )}
      {records.length > 0 && (
        <>
          <p className="text-2xl font-semibold tabular-nums">
            {total_tco2e} <span className="text-base font-normal text-slate-600">tCO₂e</span>
          </p>
          <p className="mb-3 text-xs text-slate-500">
            {formatQty(total_kgco2e)} kg · Scope {records[0].scope} · {records.length > 1 ? `pro-rated over ${records.length} months` : 'one month'}
          </p>
          <ul className="space-y-2">
            {records.map((r) => {
              const t = r.calculation_trace_json
              const isOpen = open === r.id
              return (
                <li key={r.id} className="rounded-md border border-slate-200">
                  <button className="flex w-full flex-wrap items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-slate-50"
                    onClick={() => setOpen(isOpen ? null : r.id)} aria-expanded={isOpen}>
                    <span>{r.allocation_start} → {r.allocation_end} <span className="text-slate-500">({t.allocation.fraction} days · {t.allocation.reporting_year})</span></span>
                    <span className="tabular-nums font-medium">{formatQty(r.kgco2e)} kg {t.factor.ghg_basis}</span>
                  </button>
                  {isOpen && <TraceDetail t={t} />}
                </li>
              )
            })}
          </ul>
        </>
      )}
      {superseded_records.length > 0 && (
        <div className="mt-3 text-sm">
          <button className="text-emerald-700 hover:underline" onClick={() => setShowHistory((v) => !v)}>
            {showHistory ? 'Hide' : 'Show'} {superseded_records.length} earlier calculation{superseded_records.length === 1 ? '' : 's'}
          </button>
          {showHistory && (
            <ul className="mt-2 space-y-1 text-xs text-slate-500">
              {superseded_records.map((r) => (
                <li key={r.id}>
                  {r.calculated_at.slice(0, 19).replace('T', ' ')}: {r.allocation_start} → {r.allocation_end},{' '}
                  {formatQty(r.kgco2e)} kg with {r.calculation_trace_json.factor.key} v{r.calculation_trace_json.factor.version}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  )
}

function Step({ n, title, children }) {
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-xs font-medium text-emerald-800">{n}</span>
      <div className="min-w-0 flex-1">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{title}</div>
        <div className="mt-0.5 break-words text-sm">{children}</div>
      </div>
    </div>
  )
}

function TraceDetail({ t }) {
  return (
    <div className="space-y-3 border-t border-slate-200 bg-slate-50 px-3 py-3">
      <Step n={1} title="Bill">
        {t.bill.file_name} · page {t.extraction.page_number} · {t.bill.facility} ({t.bill.facility_region})
        <div className="font-mono text-xs text-slate-500">sha256 {t.bill.file_sha256.slice(0, 16)}…</div>
      </Step>
      <Step n={2} title="Extracted quantity">
        {formatQty(t.quantity.value)} {t.quantity.unit}
        {t.quantity.unit_as_extracted !== t.quantity.unit && <span className="text-slate-500"> (printed as “{t.quantity.unit_as_extracted}”)</span>}
        {t.quantity.source === 'meter_readings' && <div className="text-xs text-slate-600">From meter readings: {t.quantity.derivation}</div>}
        <div className="mt-1 whitespace-pre-wrap rounded bg-white px-2 py-1 font-mono text-xs">{t.extraction.source_snippet}</div>
        <div className="text-xs text-slate-500">
          Approval: {t.extraction.approval}
          {t.extraction.corrections && Object.keys(t.extraction.corrections).length > 0 && ' · corrected by reviewer'}
        </div>
      </Step>
      <Step n={3} title="Allocation">
        {t.allocation.fraction} days of {t.allocation.billing_period[0]} → {t.allocation.billing_period[1]}
        {' '}= {formatQty(t.allocation.segment_quantity_rounded)} {t.quantity.unit}
        <div className="text-xs text-slate-500">{t.allocation.method}{t.allocation.crosses_reporting_year && ' The bill crosses a reporting-year boundary.'}</div>
      </Step>
      <Step n={4} title="Unit normalization">
        {t.normalization.from_unit === t.normalization.to_unit
          ? 'None needed'
          : <>× {t.normalization.multiply_by} {t.normalization.to_unit}/{t.normalization.from_unit} <span className="text-xs text-slate-500">({t.normalization.definition})</span></>}
      </Step>
      <Step n={5} title="Emission factor">
        {formatQty(t.factor.kgco2e_per_unit)} kg {t.factor.ghg_basis}/{t.factor.unit} · {t.factor.key} v{t.factor.version}
        {t.factor.region_match === 'parent' && <span className="text-amber-700"> · national factor (no factor for the facility's subregion)</span>}
        {t.factor.owner === 'organization' && <span className="text-slate-600"> · organization-specific</span>}
        <div className="text-xs text-slate-600">{t.factor.source_name} ({t.factor.publication_year})</div>
        <a className="break-all text-xs text-emerald-700 hover:underline" href={t.factor.source_url} target="_blank" rel="noreferrer">{t.factor.source_url}</a>
      </Step>
      <Step n={6} title="Formula">
        <code className="block rounded bg-white px-2 py-1 text-xs">{t.formula}</code>
        <div className="text-xs text-slate-500">{t.result.scope_basis}. Rounded to {t.result.rounding}.</div>
      </Step>
    </div>
  )
}
