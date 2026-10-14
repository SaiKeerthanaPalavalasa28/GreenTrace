import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { Card, ErrorBox, PageHeader, inputClass } from '../components/ui'
import { StatusBadge, formatQty, formatT } from '../components/status'
import Drawer from '../components/Drawer'
import EmissionsTrace from '../components/EmissionsTrace'
import { AXIS, GRID, INK, OTHER, SCOPE_COLOR, SERIES, STATUS, SURFACE, compact, monthLabel } from '../components/viz'

function lastDayOfMonth(ym) {
  const [y, m] = ym.split('-').map(Number)
  return new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10)
}

export default function DashboardPage() {
  const [searchParams] = useSearchParams()
  const [periods, setPeriods] = useState(null)
  const [facilities, setFacilities] = useState([])
  const [filters, setFilters] = useState({ year: '', from: '', to: '', facility_id: '', utility_type: '' })
  const [data, setData] = useState(null)
  const [bills, setBills] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [traceBill, setTraceBill] = useState(null)
  const [showTable, setShowTable] = useState(false)

  useEffect(() => {
    Promise.all([api('/dashboard/periods'), api('/facilities')]).then(([p, f]) => {
      setPeriods(p)
      setFacilities(f)
      const wanted = searchParams.get('period')
      setFilters((cur) => ({ ...cur, year: p.years.some((y) => y.label === wanted) ? wanted : p.default }))
    }).catch(setError)
  }, [])

  const range = useMemo(() => {
    if (!periods) return null
    if (filters.year === 'custom') {
      if (!filters.from || !filters.to || filters.to < filters.from) return null
      return { period_start: `${filters.from}-01`, period_end: lastDayOfMonth(filters.to), label: `${filters.from} to ${filters.to}` }
    }
    const y = periods.years.find((x) => x.label === filters.year)
    return y ? { period_start: y.start, period_end: y.end, label: y.label } : null
  }, [periods, filters])

  useEffect(() => {
    if (!range) return
    const params = {
      period_start: range.period_start, period_end: range.period_end,
      facility_id: filters.facility_id, utility_type: filters.utility_type,
    }
    setLoading(true)
    Promise.all([api('/dashboard', { params }), api('/bills', { params })])
      .then(([d, b]) => { setData(d); setBills(b); setError(null) })
      .catch(setError)
      .finally(() => setLoading(false))
  }, [range, filters.facility_id, filters.utility_type])

  const set = (k) => (e) => setFilters({ ...filters, [k]: e.target.value })

  return (
    <div className="space-y-5">
      <PageHeader title="Emissions dashboard" subtitle="Every figure is calculated from approved bills and traces back to its source page." />

      {/* One filter row; it scopes every number below. */}
      <div className="glass flex flex-wrap items-end gap-3 rounded-3xl p-4">
        <label className="text-sm">
          <span className="mb-1 block text-xs font-medium text-slate-600">Reporting period</span>
          <select className={inputClass + ' !w-auto'} value={filters.year} onChange={set('year')}>
            {periods?.years.map((y) => <option key={y.label} value={y.label}>{y.label}{y.has_data ? '' : ' (no data)'}</option>)}
            <option value="custom">Custom months…</option>
          </select>
        </label>
        {filters.year === 'custom' && (
          <>
            <label className="text-sm"><span className="mb-1 block text-xs font-medium text-slate-600">From</span>
              <input type="month" className={inputClass + ' !w-auto'} value={filters.from} onChange={set('from')} /></label>
            <label className="text-sm"><span className="mb-1 block text-xs font-medium text-slate-600">To</span>
              <input type="month" className={inputClass + ' !w-auto'} value={filters.to} onChange={set('to')} /></label>
          </>
        )}
        <label className="text-sm">
          <span className="mb-1 block text-xs font-medium text-slate-600">Facility</span>
          <select className={inputClass + ' !w-auto'} value={filters.facility_id} onChange={set('facility_id')}>
            <option value="">All facilities</option>
            {facilities.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-xs font-medium text-slate-600">Utility</span>
          <select className={inputClass + ' !w-auto'} value={filters.utility_type} onChange={set('utility_type')}>
            <option value="">All utilities</option>
            <option value="electricity">Electricity</option>
            <option value="natural_gas">Natural gas</option>
          </select>
        </label>
      </div>

      <ErrorBox error={error} />
      {!data ? <p className="text-sm text-slate-500">Loading…</p> : (
        // Refetch keeps the frame: previous render stays, dimmed.
        <div className={`space-y-5 transition-opacity ${loading ? 'opacity-50' : ''}`}>
          <Completeness data={data} />
          <Headline data={data} label={range?.label} />
          <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <MonthlyTrend data={data} showTable={showTable} setShowTable={setShowTable} />
            <FacilityBreakdown data={data} />
          </div>
          <BillsTable bills={bills} onOpen={setTraceBill} />
        </div>
      )}

      {traceBill && (
        <Drawer title={traceBill.original_filename} onClose={() => setTraceBill(null)}>
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <StatusBadge status={traceBill.status} />
              <span>{traceBill.facility_name}</span>
              <Link className="ml-auto text-emerald-700 hover:underline" to={`/bills/${traceBill.id}`}>Open bill page →</Link>
            </div>
            {traceBill.status === 'approved'
              ? <EmissionsTrace billId={traceBill.id} />
              : <p className="text-sm text-slate-600">
                  Not included in totals: this bill is <b>{traceBill.status.replace('_', ' ')}</b>.
                  {traceBill.status === 'needs_review' && <> <Link className="text-emerald-700 hover:underline" to={`/review/${traceBill.id}`}>Review it</Link>.</>}
                </p>}
          </div>
        </Drawer>
      )}
    </div>
  )
}

function Completeness({ data }) {
  const { bills, completeness } = data
  if (!completeness.is_partial) {
    return (
      <p className="glass flex w-fit items-center gap-2 rounded-full px-4 py-2 text-sm text-slate-700">
        <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS.good }} />
        Complete for this selection: every bill in the period is approved and calculated.
      </p>
    )
  }
  const parts = [
    bills.pending_review && `${bills.pending_review} awaiting review`,
    bills.processing && `${bills.processing} still processing`,
    bills.failed && `${bills.failed} failed extraction`,
    bills.calculation_errors && `${bills.calculation_errors} approved but not calculated`,
  ].filter(Boolean)
  return (
    <div role="status" className="flex flex-wrap items-start gap-3 rounded-3xl border px-5 py-4 text-sm backdrop-blur"
      style={{ borderColor: STATUS.warning, background: 'rgb(255 251 235 / 0.8)' }}>
      <span aria-hidden="true" className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold text-slate-900" style={{ background: STATUS.warning }}>!</span>
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-slate-900">Partial total: {completeness.excluded_bills} bill{completeness.excluded_bills === 1 ? '' : 's'} not included</div>
        <div className="text-slate-700">{parts.join(' · ')}. Totals below count approved, calculated bills only.</div>
      </div>
      <div className="flex basis-full gap-3 pl-8 sm:basis-auto sm:pl-0">
        {bills.pending_review > 0 && <Link className="font-medium text-emerald-800 hover:underline" to="/review">Review queue →</Link>}
        {(bills.failed > 0 || bills.calculation_errors > 0) && <Link className="font-medium text-emerald-800 hover:underline" to="/bills">Bills →</Link>}
      </div>
    </div>
  )
}

function Headline({ data, label }) {
  const t = data.totals
  const hasData = t.kgco2e !== '0'
  return (
    <Card className="!bg-gradient-to-br from-white/80 via-emerald-50/70 to-amber-50/60">
      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 md:grid-cols-[minmax(0,1.2fr)_minmax(0,2fr)]">
        <div>
          <div className="text-sm text-slate-600">Total emissions{label ? `, ${label}` : ''}</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="font-display text-6xl font-extrabold tracking-tight text-slate-900">{formatT(t.tco2e)}</span>
            <span className="text-lg text-slate-600">tCO₂e</span>
          </div>
          {Number(data.ghg_basis.co2_only_tco2e) > 0 && (
            <p className="mt-2 text-xs text-slate-500">
              Includes {formatT(data.ghg_basis.co2_only_tco2e)} t from grid factors that cover CO₂ only (CEA, India).
            </p>
          )}
        </div>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Scope 1" sub="Natural gas combustion" value={formatT(t.scope1_tco2e)} unit="t" swatch={SCOPE_COLOR[1]} share={t.scope1_share_pct} />
          <Stat label="Scope 2" sub="Electricity, location-based" value={formatT(t.scope2_tco2e)} unit="t" swatch={SCOPE_COLOR[2]} share={t.scope2_share_pct} />
          <Stat label="Bills included" sub="Approved & calculated" value={data.bills.included} />
          <Stat label="Pending review" sub="Not in totals" value={data.bills.pending_review}
            status={data.bills.pending_review > 0 ? 'warning' : null} />
        </div>
      </div>
      {hasData && <ScopeSplit totals={t} />}
      {t.parts_sum_differs && (
        <p className="mt-2 text-xs text-slate-500">Each figure is rounded to 0.001 t from exact values, so Scope 1 + Scope 2 may differ from the total by 0.001 t.</p>
      )}
    </Card>
  )
}

function Stat({ label, sub, value, unit, swatch, share, status }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-sm text-slate-600">
        {swatch && <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: swatch }} />}
        {status === 'warning' && <span aria-hidden="true" className="flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold text-slate-900" style={{ background: STATUS.warning }}>!</span>}
        {label}
      </div>
      <div className="mt-0.5 font-display text-2xl font-extrabold text-slate-900">{value}{unit && <span className="ml-1 text-sm font-normal text-slate-500">{unit}</span>}</div>
      <div className="text-xs text-slate-500">{share != null ? `${share}% · ` : ''}{sub}</div>
    </div>
  )
}

// Part-to-whole for two parts: a thin 100% bar reads better than a two-slice donut.
function ScopeSplit({ totals }) {
  const s1 = Number(totals.scope1_share_pct || 0)
  const s2 = Number(totals.scope2_share_pct || 0)
  return (
    <div className="mt-6" aria-label={`Scope 1 ${totals.scope1_share_pct}%, Scope 2 ${totals.scope2_share_pct}%`}>
      <div className="flex h-3 w-full gap-[3px] overflow-hidden rounded-full">
        {s1 > 0 && <div style={{ width: `${s1}%`, background: SCOPE_COLOR[1] }} title={`Scope 1: ${totals.scope1_tco2e} t (${totals.scope1_share_pct}%)`} />}
        {s2 > 0 && <div style={{ width: `${s2}%`, background: SCOPE_COLOR[2] }} title={`Scope 2: ${totals.scope2_tco2e} t (${totals.scope2_share_pct}%)`} />}
      </div>
    </div>
  )
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  return (
    <div className="glass-strong rounded-2xl px-3 py-2 text-xs">
      <div className="mb-1 font-medium text-slate-600">{monthLabel(label)}</div>
      {[2, 1].map((s) => (
        <div key={s} className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-0.5 w-3" style={{ background: SCOPE_COLOR[s] }} />
          <span className="font-semibold tabular-nums text-slate-900">{formatT(row[`scope${s}_tco2e`])} t</span>
          <span className="text-slate-500">Scope {s}</span>
        </div>
      ))}
      <div className="mt-1 border-t border-slate-100 pt-1 text-slate-600">Total <span className="font-semibold tabular-nums text-slate-900">{formatT(row.total_tco2e)} t</span></div>
    </div>
  )
}

function MonthlyTrend({ data, showTable, setShowTable }) {
  // Geometry needs numbers; every value shown as text uses the server's exact strings.
  const rows = data.monthly.map((m) => ({ ...m, s1: Number(m.scope1_tco2e), s2: Number(m.scope2_tco2e) }))
  return (
    <Card title="Monthly emissions (tCO₂e)" actions={
      <button className="text-sm text-emerald-700 hover:underline" onClick={() => setShowTable(!showTable)}>{showTable ? 'Show chart' : 'Show table'}</button>
    }>
      {showTable ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500"><tr><th className="py-1.5 pr-4 font-medium">Month</th><th className="py-1.5 pr-4 text-right font-medium">Scope 1</th><th className="py-1.5 pr-4 text-right font-medium">Scope 2</th><th className="py-1.5 text-right font-medium">Total</th></tr></thead>
            <tbody className="divide-y divide-slate-200/60 tabular-nums">
              {data.monthly.map((m) => (
                <tr key={m.month}><td className="py-1.5 pr-4">{monthLabel(m.month)}</td><td className="py-1.5 pr-4 text-right">{formatT(m.scope1_tco2e)}</td><td className="py-1.5 pr-4 text-right">{formatT(m.scope2_tco2e)}</td><td className="py-1.5 text-right font-medium">{formatT(m.total_tco2e)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} margin={{ top: 16, right: 8, bottom: 0, left: 0 }} barCategoryGap="20%">
              <CartesianGrid vertical={false} stroke={GRID} />
              <XAxis dataKey="month" tickFormatter={monthLabel} tick={{ fill: INK.muted, fontSize: 12 }} axisLine={{ stroke: AXIS }} tickLine={false} interval="preserveStartEnd" />
              <YAxis tickFormatter={compact} tick={{ fill: INK.muted, fontSize: 12 }} axisLine={false} tickLine={false} width={44} />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: 'rgba(11,11,11,0.04)' }} />
              <Legend verticalAlign="top" align="left" height={36} iconType="square" iconSize={10}
                formatter={(v) => <span style={{ color: INK.secondary, fontSize: 12 }}>{v}</span>} />
              {/* Surface-colored stroke = the 2px gap between stacked segments. */}
              <Bar dataKey="s1" name="Scope 1" stackId="s" fill={SCOPE_COLOR[1]} stroke={SURFACE} strokeWidth={2} maxBarSize={24} isAnimationActive={false} />
              <Bar dataKey="s2" name="Scope 2" stackId="s" fill={SCOPE_COLOR[2]} stroke={SURFACE} strokeWidth={2} maxBarSize={24} radius={[4, 4, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  )
}

function FacilityBreakdown({ data }) {
  const slices = data.facility_donut.map((s, i) => ({ ...s, value: Number(s.tco2e), color: s.key === 'other' ? OTHER : SERIES[i] }))
  return (
    <Card title="By facility">
      {slices.length === 0 ? <p className="text-sm text-slate-500">No approved emissions in this period.</p> : (
        <>
          {/* A one-slice donut says nothing; with a single facility the list alone carries it. */}
          {slices.length > 1 && <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={slices} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="95%" stroke={SURFACE} strokeWidth={2} isAnimationActive={false}>
                  {slices.map((s) => <Cell key={s.key} fill={s.color} />)}
                </Pie>
                <Tooltip formatter={(_, name, item) => [`${formatT(item.payload.tco2e)} t (${item.payload.share_pct}%)`, name]} />
              </PieChart>
            </ResponsiveContainer>
          </div>}
          {/* Every facility with its value: the legend doubles as the table view. */}
          <ul className="mt-3 space-y-1.5 text-sm">
            {data.by_facility.map((f, i) => {
              const color = i < slices.length && slices[i].key !== 'other' ? slices[i].color : OTHER
              return (
                <li key={f.facility_id} className="flex items-center gap-2">
                  <span aria-hidden="true" className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: color }} />
                  <span className="min-w-0 flex-1 truncate text-slate-700">{f.name}</span>
                  <span className="font-medium tabular-nums text-slate-900">{formatT(f.tco2e)} t</span>
                  <span className="w-12 text-right tabular-nums text-slate-500">{f.share_pct}%</span>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </Card>
  )
}

function BillsTable({ bills, onOpen }) {
  return (
    <Card title={`Bills in this period (${bills.length})`}>
      {bills.length === 0 ? <p className="text-sm text-slate-500">No bills overlap this period.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-slate-500">
              <tr>
                <th className="py-2 pr-4 font-medium">File</th>
                <th className="py-2 pr-4 font-medium">Facility</th>
                <th className="py-2 pr-4 font-medium">Utility</th>
                <th className="py-2 pr-4 font-medium">Billing period</th>
                <th className="py-2 pr-4 text-right font-medium">Quantity</th>
                <th className="py-2 pr-4 text-right font-medium">tCO₂e (whole bill)</th>
                <th className="py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200/60">
              {bills.map((b) => (
                <tr key={b.id} tabIndex={0} className="cursor-pointer transition-colors hover:bg-white/60 focus:bg-white/60 focus:outline-none"
                  onClick={() => onOpen(b)} onKeyDown={(e) => e.key === 'Enter' && onOpen(b)}>
                  <td className="max-w-xs truncate py-2 pr-4 font-medium">{b.original_filename}</td>
                  <td className="py-2 pr-4">{b.facility_name}</td>
                  <td className="py-2 pr-4">{b.utility_type?.replace('_', ' ') || '—'}</td>
                  <td className="whitespace-nowrap py-2 pr-4 text-xs">{b.billing_period_start} → {b.billing_period_end}</td>
                  <td className="whitespace-nowrap py-2 pr-4 text-right tabular-nums">{b.quantity != null ? `${formatQty(b.quantity)} ${b.unit}` : '—'}</td>
                  <td className="whitespace-nowrap py-2 pr-4 text-right tabular-nums">
                    {b.tco2e != null ? formatT(b.tco2e) : b.calculation_error ? <span className="text-red-700">not calculated</span> : '—'}
                  </td>
                  <td className="py-2"><StatusBadge status={b.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-slate-500">
            tCO₂e is for the whole bill; a bill crossing the period boundary contributes only its pro-rated months to the totals above.
            Click a row for its full calculation trace.
          </p>
        </div>
      )}
    </Card>
  )
}
