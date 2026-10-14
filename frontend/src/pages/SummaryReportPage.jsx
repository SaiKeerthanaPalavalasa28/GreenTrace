import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, fetchBlobUrl } from '../api/client'
import { ZONE_STYLE } from '../alerts'
import { Button, Card, ErrorBox, PageHeader } from '../components/ui'
import { ZoneBadge } from './ScopeDashboardPage'

const f = (v) => (v == null ? '-' : v.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 }))
const PRI = { high: 'bg-red-100 text-red-800', medium: 'bg-amber-100 text-amber-800', low: 'bg-emerald-100 text-emerald-800' }

export default function SummaryReportPage() {
  const [rep, setRep] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => { api('/scopes/report').then(setRep).catch(setError) }, [])

  const download = async () => {
    try {
      const a = document.createElement('a')
      a.href = await fetchBlobUrl('/scopes/report.pdf')
      a.download = 'greentrace-report.pdf'
      a.click()
    } catch (e) { setError(e) }
  }
  if (error) return <ErrorBox error={error} />
  if (!rep) return <p className="text-sm text-slate-500">Loading…</p>
  const { summary: sm } = rep
  const chart = sm.scopes.map((s) => ({ name: `Scope ${s.scope}`, used: s.used_t, zone: s.zone }))
  return (
    <div className="space-y-6">
      <PageHeader title="Final report" subtitle={`${sm.organization} · generated ${new Date(sm.generated_at).toLocaleString()}`}>
        <Button onClick={download}>Download PDF</Button>
      </PageHeader>
      <section className="rise rounded-3xl border-2 bg-white p-6" style={{ borderColor: ZONE_STYLE[sm.total.zone].color }}>
        <div className="mb-2"><ZoneBadge zone={sm.total.zone} /></div>
        <p className="text-lg font-bold">{rep.headline}</p>
      </section>

      <Card title="Scope summary">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] text-left text-sm">
            <thead><tr className="text-slate-500"><th className="py-1">Scope</th><th>Docs</th><th>Used (t)</th><th>Budget (t)</th><th>Left (t)</th><th>% used</th><th>Status</th></tr></thead>
            <tbody>
              {[...sm.scopes, { ...sm.total, scope: 'Total' }].map((s) => (
                <tr key={s.scope} className={`border-t border-slate-200/70 ${s.scope === 'Total' ? 'font-bold' : ''}`}>
                  <td className="py-1.5">{s.scope === 'Total' ? 'Total' : <Link className="text-emerald-700 hover:underline" to={`/scope/${s.scope}`}>Scope {s.scope}</Link>}</td>
                  <td>{s.documents}</td><td>{f(s.used_t)}</td><td>{f(s.budget_t)}</td><td>{f(s.remaining_t)}</td>
                  <td>{s.percent_used == null ? '-' : `${s.percent_used.toFixed(0)}%`}</td><td><ZoneBadge zone={s.zone} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-4" style={{ height: 220 }}>
          <ResponsiveContainer>
            <BarChart data={chart}>
              <CartesianGrid vertical={false} stroke="#e3ece6" />
              <XAxis dataKey="name" tickLine={false} axisLine={false} />
              <YAxis tickLine={false} axisLine={false} width={56} />
              <Tooltip formatter={(v) => [`${f(v)} t`, 'Used']} cursor={{ fill: 'rgba(31,117,73,.06)' }} />
              <Bar dataKey="used" radius={[4, 4, 0, 0]}>{chart.map((c) => <Cell key={c.name} fill={ZONE_STYLE[c.zone === 'unset' ? 'green' : c.zone].color} />)}</Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title="Suggestions to improve">
        <ul className="space-y-3">
          {rep.suggestions.map((s, i) => (
            <li key={i} className="flex gap-3">
              <span className={`mt-0.5 h-fit shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold uppercase ${PRI[s.priority]}`}>{s.priority}</span>
              <div><div className="font-semibold">{s.title}</div><p className="text-sm text-slate-600">{s.detail}</p></div>
            </li>
          ))}
        </ul>
      </Card>

      <Card title={`Flagged documents (${rep.flagged.length})`}>
        {rep.flagged.length === 0 ? <p className="text-sm text-slate-600">No documents were flagged.</p> : (
          <ul className="space-y-4">
            {rep.flagged.map((d) => (
              <li key={d.id}>
                <Link to={`/scope/${d.scope}`} className="font-semibold text-emerald-800 hover:underline">Scope {d.scope} · {d.filename}</Link>
                <ul className="mt-1 list-disc pl-5 text-sm text-slate-600">{d.flags.map((fl, i) => <li key={i}><b>{fl.severity}</b>: {fl.message}</li>)}</ul>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
