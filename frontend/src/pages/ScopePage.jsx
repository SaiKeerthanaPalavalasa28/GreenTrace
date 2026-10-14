import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useDropzone } from 'react-dropzone'
import { api, fetchBlobUrl } from '../api/client'
import { useAuth } from '../auth'
import { EmptyState, Icon, Modal, useUi } from '../components/kit'
import { Button, ErrorBox, Field, inputClass } from '../components/ui'
import { ZoneBadge } from './ScopeDashboardPage'

const TITLES = {
  1: ['Scope 1', 'Direct emissions', 'Fuel burned on site or in vehicles you own, plus refrigerant leaks. Upload fuel logs, gas bills and maintenance records.', 'flame'],
  2: ['Scope 2', 'Purchased energy', 'Electricity, steam, heating and cooling you buy. Upload your electricity bills.', 'bolt'],
  3: ['Scope 3', 'Value chain', 'Business travel, commuting, waste, freight, water and purchased materials. Upload travel, waste and supplier records.', 'globe'],
}
const SEV = { high: 'bg-red-100 text-red-800', medium: 'bg-amber-100 text-amber-800', low: 'bg-slate-100 text-slate-700' }
const num = (v, d = 2) => v.toLocaleString(undefined, { maximumFractionDigits: d })

function Flags({ flags }) {
  if (!flags.length) return <p className="inline-flex items-center gap-1.5 text-sm font-semibold text-emerald-700"><Icon name="check" className="h-4 w-4" strokeWidth={2.6} />Nothing suspicious found</p>
  return (
    <ul className="space-y-2">
      {flags.map((f, i) => (
        <li key={i} className="flex gap-2.5 rounded-2xl bg-white/70 p-3 text-sm">
          <span className={`mt-0.5 h-fit shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${SEV[f.severity]}`}>{f.severity}</span>
          <span className="min-w-0">{f.message}{f.line && <code className="mt-1 block truncate rounded-lg bg-slate-100 px-2 py-1 text-xs text-slate-600">{f.line}</code>}</span>
        </li>
      ))}
    </ul>
  )
}

function EditQuantity({ item, onSave, onClose }) {
  const [v, setV] = useState(String(item.quantity))
  const valid = Number(v) > 0
  return (
    <Modal title="Edit quantity" onClose={onClose} footer={
      <>
        <button onClick={onClose} className="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100">Cancel</button>
        <Button disabled={!valid} onClick={() => onSave(Number(v))}>Save</Button>
      </>
    }>
      <form onSubmit={(e) => { e.preventDefault(); valid && onSave(Number(v)) }}>
        <Field label={`${item.label} (${item.unit})`} hint="The total and your status update straight away.">
          <input type="number" step="any" min="0" className={inputClass} value={v} onChange={(e) => setV(e.target.value)} />
        </Field>
      </form>
    </Modal>
  )
}

function Items({ doc, categories, canEdit, onChange }) {
  const { toast, ask } = useUi()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(null)
  const act = async (fn, okMsg) => {
    setBusy(true)
    setError(null)
    try { onChange(await fn()); okMsg && toast(okMsg) } catch (e) { setError(e); toast(e.message, 'error') } finally { setBusy(false) }
  }
  const patch = (i, body) => act(() => api(`/scopes/documents/${doc.id}/items/${i}`, { method: 'PATCH', body }), 'Updated')
  const remove = async (i, it) => {
    if (await ask({ title: 'Remove this line?', body: `“${it.label}” (${num(it.quantity)} ${it.unit}) will no longer count towards the total.`, confirmLabel: 'Remove', danger: true }))
      act(() => api(`/scopes/documents/${doc.id}/items/${i}`, { method: 'DELETE' }), 'Line removed')
  }
  if (!doc.items.length) return <p className="text-sm text-slate-500">No activity data was counted from this document.</p>
  return (
    <div className="overflow-x-auto">
      <ErrorBox error={error} />
      {editing && <EditQuantity item={doc.items[editing.i]} onClose={() => setEditing(null)} onSave={(q) => { patch(editing.i, { quantity: q }); setEditing(null) }} />}
      <table className="w-full min-w-[34rem] text-left text-sm">
        <thead><tr className="text-xs uppercase tracking-wider text-slate-500"><th className="py-1.5 font-semibold">Source</th><th className="font-semibold">Quantity</th><th className="font-semibold">Factor</th><th className="text-right font-semibold">kg CO₂e</th>{canEdit && <th />}</tr></thead>
        <tbody>
          {doc.items.map((it, i) => (
            <tr key={i} className="border-t border-emerald-900/10 align-top">
              <td className="py-2 pr-2">
                {canEdit ? (
                  <select disabled={busy} className={`${inputClass} !py-1.5`} value={it.category} onChange={(e) => patch(i, { category: e.target.value })}>
                    {categories.filter((c) => c.families.includes(it.family)).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                  </select>
                ) : <span className="font-medium">{it.label}</span>}
                <div className="mt-1 max-w-xs truncate text-xs text-slate-500" title={it.line}>p.{it.page} · {it.line}</div>
              </td>
              <td className="whitespace-nowrap py-2">{num(it.quantity)} {it.unit}{it.edited && <span className="ml-1 rounded-full bg-amber-100 px-1.5 text-[10px] font-bold text-amber-800">edited</span>}</td>
              <td className="whitespace-nowrap py-2 text-slate-600" title={it.factor_source}>{it.factor}/{it.family}</td>
              <td className="py-2 text-right font-semibold tabular-nums">{num(it.kg_co2e)}</td>
              {canEdit && (
                <td className="whitespace-nowrap py-2 pl-3 text-right">
                  <button disabled={busy} onClick={() => setEditing({ i })} aria-label="Edit quantity" className="rounded-full p-2 text-emerald-700 hover:bg-emerald-50"><Icon name="edit" className="h-4 w-4" /></button>
                  <button disabled={busy} onClick={() => remove(i, it)} aria-label="Remove line" className="rounded-full p-2 text-red-600 hover:bg-red-50"><Icon name="trash" className="h-4 w-4" /></button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DocCard({ doc, categories, canEdit, onChange, onDelete }) {
  const { toast, ask } = useUi()
  const [open, setOpen] = useState(doc.risk === 'high' || doc.risk === 'medium')
  const view = async () => {
    try { window.open(await fetchBlobUrl(`/scopes/documents/${doc.id}/file`), '_blank') } catch (e) { toast(e.message, 'error') }
  }
  const remove = async () => {
    if (!(await ask({ title: 'Delete this document?', body: `“${doc.filename}” and its emissions will be removed from your totals.`, confirmLabel: 'Delete', danger: true }))) return
    try { await api(`/scopes/documents/${doc.id}`, { method: 'DELETE' }); onDelete(doc.id); toast('Document deleted') } catch (e) { toast(e.message, 'error') }
  }
  const risk = {
    clear: ['All clear', 'bg-emerald-100 text-emerald-800'], low: ['Low risk', SEV.low],
    medium: ['Medium risk', SEV.medium], high: ['High risk', SEV.high],
  }[doc.risk]
  return (
    <div className="glass rise rounded-[1.75rem]">
      <div className="flex flex-wrap items-center gap-3 px-5 py-4">
        <button onClick={() => setOpen(!open)} className="flex min-w-0 flex-1 items-center gap-3 text-left" aria-expanded={open}>
          <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl transition-transform ${open ? 'rotate-90' : ''} bg-emerald-50 text-emerald-700`}>›</span>
          <span className="min-w-0">
            <span className="block truncate font-semibold">{doc.filename}</span>
            <span className="text-xs text-slate-500">{doc.page_count} page(s) · uploaded {new Date(doc.uploaded_at).toLocaleDateString()}</span>
          </span>
        </button>
        <span className={`rounded-full px-3 py-1 text-xs font-bold ${risk[1]}`}>{risk[0]}</span>
        <span className="text-xl font-semibold tabular-nums" style={{ fontFamily: 'Fraunces, serif' }}>{num(doc.total_kg_co2e / 1000)} t</span>
        <Button variant="secondary" onClick={view}>View PDF</Button>
        {canEdit && <button onClick={remove} aria-label="Delete document" className="rounded-full p-2.5 text-red-600 hover:bg-red-50"><Icon name="trash" /></button>}
      </div>
      {open && (
        <div className="space-y-5 border-t border-emerald-900/10 px-5 py-5">
          <div><h4 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">Checks</h4><Flags flags={doc.flags} /></div>
          <div><h4 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">What was counted</h4><Items doc={doc} categories={categories} canEdit={canEdit} onChange={onChange} /></div>
        </div>
      )}
    </div>
  )
}

export default function ScopePage() {
  const n = Number(useParams().n)
  const { canEdit } = useAuth()
  const { toast } = useUi()
  const [docs, setDocs] = useState(null)
  const [summary, setSummary] = useState(null)
  const [cats, setCats] = useState({})
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(() => {
    api(`/scopes/${n}/documents`).then(setDocs).catch(setError)
    api('/scopes/summary').then(setSummary).catch(() => {})
  }, [n])
  useEffect(() => { setDocs(null); refresh() }, [refresh])
  useEffect(() => { api('/scopes/categories').then(setCats).catch(() => {}) }, [])

  const upload = useCallback(async (files) => {
    if (!files.length) return
    setBusy(true); setError(null)
    try {
      const fd = new FormData()
      files.forEach((f) => fd.append('files', f))
      const res = await api(`/scopes/${n}/documents`, { method: 'POST', body: fd })
      setSummary(res.summary)
      setDocs(await api(`/scopes/${n}/documents`))
      res.results.forEach((r) => {
        if (r.outcome !== 'ok') toast(`${r.filename}: ${r.reason}`, 'error')
        else if (r.document.flags.length) toast(`${r.filename}: ${r.document.flags.length} thing(s) to check`, 'error')
        else toast(`${r.filename} added - all clear`)
      })
    } catch (e) { setError(e) } finally { setBusy(false) }
  }, [n, toast])
  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop: upload, accept: { 'application/pdf': ['.pdf'] }, disabled: !canEdit || busy })

  const replace = (d) => { setDocs((ds) => ds.map((x) => (x.id === d.id ? d : x))); api('/scopes/summary').then(setSummary) }
  const sc = summary?.scopes[n - 1]
  const [name, short, blurb, icon] = TITLES[n]

  return (
    <div className="space-y-6">
      <nav className="glass rise flex gap-1 rounded-full p-1.5" aria-label="Scopes">
        {[1, 2, 3].map((s) => (
          <Link key={s} to={`/scope/${s}`} className={`flex flex-1 items-center justify-center gap-2 rounded-full px-4 py-2.5 text-sm font-bold transition-all duration-300 ${s === n ? 'bg-gradient-to-br from-emerald-700 to-emerald-900 text-white shadow-lg shadow-emerald-900/25' : 'text-slate-600 hover:bg-emerald-50'}`}>
            <Icon name={TITLES[s][3]} className="h-4 w-4" />Scope {s}
          </Link>
        ))}
      </nav>

      <header className="rise flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <p className="text-sm font-medium text-emerald-800/80">{short}</p>
          <h1 className="text-3xl text-emerald-950 sm:text-4xl">{name}</h1>
          <p className="mt-2 text-sm text-slate-600">{blurb}</p>
        </div>
        {sc && <div className="text-right"><ZoneBadge zone={sc.zone} />
          <div className="mt-2 text-3xl font-semibold tabular-nums" style={{ fontFamily: 'Fraunces, serif' }}>{num(sc.used_t)} <span className="text-base text-slate-500">t</span></div>
          <div className="text-xs text-slate-500">{sc.budget_t != null ? `${num(sc.remaining_t)} t left of ${num(sc.budget_t)} t` : 'no budget set'}</div></div>}
      </header>

      <ErrorBox error={error} />

      {canEdit && (
        <div {...getRootProps()} className={`dropzone cursor-pointer rounded-[1.75rem] border-2 border-dashed p-9 text-center ${isDragActive ? 'border-emerald-600 bg-emerald-50' : 'border-emerald-300/80 bg-white/60 hover:border-emerald-500 hover:bg-white/80'} ${busy ? 'pointer-events-none opacity-80' : ''}`}>
          <input {...getInputProps()} />
          <span className={`mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 ${busy ? 'animate-pulse' : ''}`}><Icon name="upload" className="h-7 w-7" /></span>
          <p className="mt-3 text-lg font-semibold text-emerald-950" style={{ fontFamily: 'Fraunces, serif' }}>{busy ? 'Reading and checking your PDF…' : isDragActive ? 'Drop to upload' : 'Drop your PDFs here'}</p>
          <p className="mt-1 text-sm text-slate-500">{busy ? 'This takes a few seconds' : 'or click to browse · text-based PDFs · every file is checked for suspicious values'}</p>
        </div>
      )}

      {docs === null ? <div className="glass h-32 animate-pulse rounded-[1.75rem]" /> : docs.length === 0 ? (
        <EmptyState title={`No Scope ${n} documents yet`}>{canEdit ? 'Drop a PDF above and it will be read, checked and added to your totals.' : 'The admin has not uploaded anything for this scope yet.'}</EmptyState>
      ) : (
        <div className="stagger space-y-3">
          {docs.map((d) => <DocCard key={d.id} doc={d} categories={cats[n] || []} canEdit={canEdit} onChange={replace}
            onDelete={(id) => { setDocs((ds) => ds.filter((x) => x.id !== id)); api('/scopes/summary').then(setSummary) }} />)}
        </div>
      )}
    </div>
  )
}
