import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { useAuth } from '../auth'
import { ZONE_STYLE } from '../alerts'
import ZoneOverlay from '../components/ZoneOverlay'
import { CountUp, EmptyState, Icon, Ring } from '../components/kit'
import { useUi } from '../components/kit'
import { Button, Card, ErrorBox, Field, inputClass, linkButtonClass } from '../components/ui'

const t = (v, d = 2) => (v == null ? '-' : v.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }))
const REMAINING = '#d6eadd'
const SCOPE_ICON = { 1: 'flame', 2: 'bolt', 3: 'globe' }
const SCOPE_SHORT = { 1: 'Direct emissions', 2: 'Purchased energy', 3: 'Value chain' }

export function ZoneBadge({ zone }) {
  const st = ZONE_STYLE[zone]
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold" style={{ background: st.soft, color: st.color }}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: st.color }} aria-hidden="true" />
      {st.label}
    </span>
  )
}

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

function BudgetEditor({ summary, onSaved, onDone }) {
  const { toast } = useUi()
  const [vals, setVals] = useState(() => Object.fromEntries(summary.scopes.map((s) => [s.scope, s.budget_t ?? ''])))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const save = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const body = {}
      for (const s of [1, 2, 3]) body[`scope${s}_budget_t`] = vals[s] === '' ? null : Number(vals[s])
      onSaved(await api('/scopes/budgets', { method: 'PUT', body }))
      toast('Budgets saved')
      onDone?.()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }
  return (
    <form onSubmit={save} className="space-y-4">
      <p className="text-sm text-slate-600">How many tonnes of CO₂e may each scope emit this year? Your status colour is worked out from these.</p>
      <ErrorBox error={error} />
      <div className="grid gap-4 sm:grid-cols-3">
        {[1, 2, 3].map((s) => (
          <Field key={s} label={`Scope ${s} · ${SCOPE_SHORT[s]}`} hint="tonnes CO₂e per year">
            <input type="number" min="0" step="any" className={inputClass} value={vals[s]} onChange={(e) => setVals({ ...vals, [s]: e.target.value })} placeholder="e.g. 500" />
          </Field>
        ))}
      </div>
      <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save budgets'}</Button>
    </form>
  )
}

function Checklist({ summary, canEdit, onEditBudgets }) {
  const hasBudget = summary.scopes.some((s) => s.budget_t != null)
  const hasDocs = summary.total.documents > 0
  const allScopes = summary.scopes.every((s) => s.documents > 0)
  if (hasBudget && hasDocs && allScopes) return null
  const steps = [
    { done: hasBudget, title: 'Set your emission budgets', body: 'Gives you the “how much is left” number and the green / orange / red status.', action: canEdit && !hasBudget && <Button onClick={onEditBudgets}>Set budgets</Button> },
    { done: hasDocs, title: 'Upload your first document', body: 'Drop a PDF on a scope tab. We read it and flag anything suspicious.', action: canEdit && !hasDocs && <Link to="/scope/2" className={linkButtonClass}>Open Scope 2</Link> },
    { done: allScopes, title: 'Cover all three scopes', body: 'The final report is complete once each scope has evidence.', action: null },
  ]
  return (
    <Card title="Getting started" className="stagger">
      <ol className="space-y-3">
        {steps.map((s, i) => (
          <li key={i} className="flex items-center gap-4">
            <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold ${s.done ? 'bg-emerald-600 text-white' : 'bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200'}`}>
              {s.done ? <Icon name="check" className="h-5 w-5" strokeWidth={2.6} /> : i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className={`font-semibold ${s.done ? 'text-slate-400 line-through' : ''}`}>{s.title}</div>
              <div className="text-sm text-slate-600">{s.body}</div>
            </div>
            {s.action}
          </li>
        ))}
      </ol>
      {!canEdit && <p className="mt-3 text-xs text-slate-500">These steps are done by the admin.</p>}
    </Card>
  )
}

export default function ScopeDashboardPage() {
  const { canEdit, me } = useAuth()
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState(null)
  const [alertKey, setAlertKey] = useState(0)
  const [editing, setEditing] = useState(false)
  const played = useRef(false)

  const load = () => api('/scopes/summary').then(setSummary).catch(setError)
  useEffect(() => { load() }, [])
  useEffect(() => {
    if (summary && !played.current && summary.total.zone !== 'unset') {
      played.current = true
      setAlertKey((k) => k + 1)
    }
  }, [summary])

  if (error) return <ErrorBox error={error} />
  if (!summary) return <div className="glass h-64 animate-pulse rounded-[2rem]" aria-label="Loading" />
  const { total, scopes } = summary
  const st = ZONE_STYLE[total.zone]
  const chart = scopes.map((s) => ({
    name: `Scope ${s.scope}`, used: s.used_t, zone: s.zone,
    remaining: s.budget_t == null ? 0 : Math.max(s.budget_t - s.used_t, 0),
  }))
  const first = (me.user.full_name || me.user.email.split('@')[0]).split(/[\s._]/)[0]

  return (
    <div className="space-y-6">
      <ZoneOverlay zone={total.zone} percent={total.percent_used} trigger={alertKey} />

      <header className="rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-emerald-800/80">{greeting()}, {first}</p>
          <h1 className="text-3xl text-emerald-950 sm:text-4xl">{summary.organization}</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          {total.zone !== 'unset' && <Button variant="secondary" onClick={() => setAlertKey((k) => k + 1)}><span className="inline-flex items-center gap-1.5"><Icon name="bell" className="h-4 w-4" />Replay alert</span></Button>}
          <Link to="/report" className={linkButtonClass}>Final report</Link>
        </div>
      </header>

      {/* Hero: the one number that matters */}
      <section className="rise relative overflow-hidden rounded-[2rem] p-6 sm:p-8" style={{ background: `linear-gradient(135deg, #fff 0%, ${st.soft} 140%)`, boxShadow: `0 20px 60px -24px ${st.color}55, 0 0 0 1px ${st.color}22` }}>
        <div className="flex flex-col items-center gap-8 md:flex-row">
          <Ring percent={total.percent_used} zone={total.zone} size={208} stroke={16}>
            {total.percent_used == null ? (
              <><Icon name="sparkle" className="h-7 w-7 text-emerald-600" /><span className="mt-1 px-6 text-xs font-semibold text-slate-500">Set a budget to begin</span></>
            ) : (
              <><span className="text-5xl font-semibold tabular-nums" style={{ fontFamily: 'Fraunces, serif', color: st.color }}><CountUp value={total.percent_used} decimals={0} />%</span>
                <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">of budget used</span></>
            )}
          </Ring>
          <div className="w-full flex-1">
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <h2 className="text-xl">Combined emissions</h2>
              <span className="rounded-full px-3 py-1 text-xs font-bold" style={{ background: st.color, color: '#fff' }}>{st.label}</span>
            </div>
            <div className="grid grid-cols-3 gap-4">
              {[['Used', total.used_t, st.color], ['Left', total.remaining_t, '#12261c'], ['Budget', total.budget_t, '#12261c']].map(([label, v, color]) => (
                <div key={label}>
                  <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</div>
                  <div className="text-2xl font-semibold tabular-nums sm:text-3xl" style={{ fontFamily: 'Fraunces, serif', color }}>
                    {v == null ? <span className="text-slate-400">—</span> : <CountUp value={v} />}
                  </div>
                  <div className="text-xs text-slate-500">t CO₂e</div>
                </div>
              ))}
            </div>
            <p className="mt-5 text-sm text-slate-700">
              {total.zone === 'unset' ? (canEdit ? 'Add budgets below to see your status.' : 'Your admin has not set budgets yet.') : st.message}
              {total.zone !== 'unset' && <span className="text-slate-500"> Orange from {summary.thresholds.moderate_from}%, red from {summary.thresholds.danger_from}%.</span>}
            </p>
            {total.flagged_documents > 0 && (
              <p className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-sm font-semibold text-amber-800">
                <Icon name="alert" className="h-4 w-4" />{total.flagged_documents} document(s) flagged - worth a look
              </p>
            )}
          </div>
        </div>
      </section>

      <Checklist summary={summary} canEdit={canEdit} onEditBudgets={() => { setEditing(true); setTimeout(() => document.getElementById('budgets')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50) }} />

      <div className="stagger grid gap-4 md:grid-cols-3">
        {scopes.map((s) => {
          const z = ZONE_STYLE[s.zone]
          return (
            <Link key={s.scope} to={`/scope/${s.scope}`} className="glass pin block rounded-[1.75rem] p-5">
              <div className="flex items-start justify-between">
                <span className="flex h-11 w-11 items-center justify-center rounded-2xl" style={{ background: z.soft, color: z.color }}><Icon name={SCOPE_ICON[s.scope]} className="h-6 w-6" /></span>
                <Ring percent={s.percent_used} zone={s.zone} size={64} stroke={7}>
                  <span className="text-[11px] font-bold tabular-nums" style={{ color: z.color }}>{s.percent_used == null ? '–' : `${Math.round(s.percent_used)}%`}</span>
                </Ring>
              </div>
              <h3 className="mt-3 text-lg">Scope {s.scope}</h3>
              <p className="text-xs text-slate-500">{SCOPE_SHORT[s.scope]}</p>
              <div className="mt-3 text-2xl font-semibold tabular-nums" style={{ fontFamily: 'Fraunces, serif' }}>{t(s.used_t)} <span className="text-sm font-medium text-slate-500">t</span></div>
              <div className="text-sm text-slate-600">{s.budget_t == null ? 'No budget set' : `${t(s.remaining_t)} t left of ${t(s.budget_t)} t`}</div>
              <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                <span>{s.documents} document(s){s.flagged_documents > 0 && <b className="text-amber-700"> · {s.flagged_documents} flagged</b>}</span>
                <span className="font-semibold text-emerald-700">Open →</span>
              </div>
            </Link>
          )
        })}
      </div>

      {total.documents === 0 ? (
        <EmptyState title="Nothing to chart yet" action={canEdit && <Link to="/scope/2" className={linkButtonClass}>Upload a document</Link>}>
          {canEdit ? 'Upload a PDF on any scope tab and your chart appears here.' : 'The admin has not uploaded any documents yet.'}
        </EmptyState>
      ) : (
        <Card title="Emissions across scopes">
          <div className="mb-3 flex flex-wrap gap-4 text-xs text-slate-600">
            <span className="flex items-center gap-1.5"><i className="inline-block h-3 w-3 rounded-full" style={{ background: ZONE_STYLE.green.color }} />Used (colour shows status)</span>
            <span className="flex items-center gap-1.5"><i className="inline-block h-3 w-3 rounded-full" style={{ background: REMAINING }} />Left of budget</span>
          </div>
          <div style={{ height: 280 }}>
            <ResponsiveContainer>
              <BarChart data={chart} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="34%">
                <CartesianGrid vertical={false} stroke="#e4eee8" strokeDasharray="3 6" />
                <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: '#4a5f54', fontSize: 13 }} />
                <YAxis tickLine={false} axisLine={false} width={52} tick={{ fill: '#4a5f54', fontSize: 12 }} />
                <Tooltip cursor={{ fill: 'rgba(31,117,73,.06)' }} contentStyle={{ borderRadius: 16, border: 'none', boxShadow: '0 12px 30px -8px rgba(18,61,43,.3)' }}
                  formatter={(v, name) => [`${t(v)} t`, name === 'used' ? 'Used' : 'Left of budget']} />
                <Bar dataKey="used" stackId="a" name="used" radius={[0, 0, 6, 6]} animationDuration={1200}>
                  {chart.map((c) => <Cell key={c.name} fill={ZONE_STYLE[c.zone === 'unset' ? 'green' : c.zone].color} />)}
                </Bar>
                <Bar dataKey="remaining" stackId="a" name="remaining" fill={REMAINING} radius={[6, 6, 0, 0]} animationDuration={1200} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {summary.breakdown.length > 0 && (
        <Card title="Where it comes from">
          <ul className="space-y-3">
            {summary.breakdown.slice(0, 8).map((b) => (
              <li key={`${b.scope}-${b.category}`} className="grid grid-cols-[4.5rem_1fr_5rem] items-center gap-3 text-sm sm:grid-cols-[4.5rem_13rem_1fr_6rem]">
                <span className="text-slate-500">Scope {b.scope}</span>
                <span className="truncate font-medium sm:block">{b.label}</span>
                <div className="hidden h-2.5 rounded-full bg-emerald-50 sm:block"><div className="h-2.5 rounded-full bg-gradient-to-r from-emerald-400 to-emerald-700" style={{ width: `${(b.t / summary.breakdown[0].t) * 100}%` }} /></div>
                <span className="text-right font-semibold tabular-nums">{t(b.t)} t</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {canEdit && (
        <div id="budgets"><Card title="Emission budgets" actions={!editing && <Button variant="secondary" onClick={() => setEditing(true)}><span className="inline-flex items-center gap-1.5"><Icon name="edit" className="h-4 w-4" />Edit</span></Button>}>
          {editing ? <BudgetEditor summary={summary} onSaved={setSummary} onDone={() => setEditing(false)} /> : (
            <div className="grid gap-3 text-sm sm:grid-cols-3">
              {scopes.map((s) => <div key={s.scope} className="rounded-2xl bg-emerald-50/70 px-4 py-3"><div className="text-xs text-slate-500">Scope {s.scope}</div><div className="font-semibold">{s.budget_t == null ? 'Not set' : `${t(s.budget_t)} t CO₂e`}</div></div>)}
            </div>
          )}
        </Card></div>
      )}
    </div>
  )
}
