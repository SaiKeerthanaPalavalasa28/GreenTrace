import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth'
import { Button, Card, ErrorBox, Field, inputClass } from '../components/ui'

const UNITS = ['kWh', 'MWh', 'GJ', 'TJ', 'MMBtu', 'therm', 'm3', 'scf', 'ccf', 'Mcf']
const GASES = ['CO2e', 'CO2', 'CH4', 'N2O']
const MASS = ['kg', 'g', 't', 'lb']

// Show stored Decimal strings without trailing zeros, never via float.
function trimDecimal(s) {
  if (s == null) return ''
  return s.includes('.') ? s.replace(/0+$/, '').replace(/\.$/, '') : s
}

function period(f) {
  return `${f.valid_from} → ${f.valid_to ?? 'open'}`
}

export default function FactorsPage() {
  const { isAdmin } = useAuth()
  const [factors, setFactors] = useState([])
  const [regions, setRegions] = useState([])
  const [filters, setFilters] = useState({ utility_type: '', region: '', include_superseded: false })
  const [selected, setSelected] = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [error, setError] = useState(null)

  const load = async () => {
    try {
      setFactors(await api('/factors', { params: filters }))
    } catch (err) {
      setError(err)
    }
  }
  useEffect(() => { load() }, [filters])
  useEffect(() => { api('/factors/regions').then(setRegions).catch(setError) }, [])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-extrabold sm:text-3xl">Emission factors</h1>
        {isAdmin && <Button onClick={() => setShowCreate((v) => !v)}>{showCreate ? 'Close' : 'Add org-specific factor'}</Button>}
      </div>
      <p className="max-w-3xl text-sm text-slate-600">
        Factors are versioned data with a cited source. Global factors come from the seed file
        (official publications); corrections create a new version and the old one is kept. kg CO₂e per unit
        is always derived from the values as published, never typed in.
      </p>
      <ErrorBox error={error} />
      {showCreate && <CreateFactor onCreated={(f) => { setShowCreate(false); load(); setSelected(f) }} />}

      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <Card
          title={`${factors.length} factors`}
          actions={
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <select className={inputClass + ' !w-auto'} value={filters.utility_type} onChange={(e) => setFilters({ ...filters, utility_type: e.target.value })}>
                <option value="">All utilities</option>
                <option value="electricity">Electricity</option>
                <option value="natural_gas">Natural gas</option>
              </select>
              <select className={inputClass + ' !w-auto'} value={filters.region} onChange={(e) => setFilters({ ...filters, region: e.target.value })}>
                <option value="">All regions</option>
                {regions.map((r) => <option key={r}>{r}</option>)}
              </select>
              <label className="flex items-center gap-1.5 text-slate-600">
                <input type="checkbox" checked={filters.include_superseded} onChange={(e) => setFilters({ ...filters, include_superseded: e.target.checked })} />
                Superseded
              </label>
            </div>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-slate-500">
                <tr>
                  <th className="py-2 pr-3 font-medium">Key</th>
                  <th className="py-2 pr-3 font-medium">Region</th>
                  <th className="py-2 pr-3 font-medium">Scope</th>
                  <th className="py-2 pr-3 text-right font-medium">kg per unit</th>
                  <th className="py-2 pr-3 font-medium">Valid</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {factors.map((f) => (
                  <tr
                    key={f.id}
                    onClick={() => setSelected(f)}
                    className={`cursor-pointer hover:bg-slate-50 ${selected?.id === f.id ? 'bg-emerald-50' : ''} ${f.superseded_by ? 'text-slate-400' : ''}`}
                  >
                    <td className="py-2 pr-3">
                      <div className="font-medium">{f.factor_key}</div>
                      <div className="text-xs text-slate-500">v{f.version}{f.org_id ? ' · org-specific' : ''}{f.superseded_by ? ' · superseded' : ''}</div>
                    </td>
                    <td className="py-2 pr-3"><code className="text-xs">{f.region}</code></td>
                    <td className="py-2 pr-3">{f.scope}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {trimDecimal(f.kgco2e_per_unit)} <span className="text-xs text-slate-500">{f.ghg_basis}/{f.unit}</span>
                    </td>
                    <td className="py-2 pr-3 whitespace-nowrap text-xs">{period(f)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <div className="lg:sticky lg:top-4 lg:self-start">
          {selected ? (
            <FactorDetail key={selected.id} factor={selected} isAdmin={isAdmin} onVersioned={(f) => { load(); setSelected(f) }} />
          ) : (
            <Card><p className="text-sm text-slate-500">Select a factor to see its source, derivation and version history.</p></Card>
          )}
        </div>
      </div>
    </div>
  )
}

function FactorDetail({ factor: f, isAdmin, onVersioned }) {
  const [history, setHistory] = useState([])
  const [showVersion, setShowVersion] = useState(false)
  useEffect(() => { api(`/factors/${f.id}/history`).then(setHistory).catch(() => {}) }, [f.id])

  return (
    <Card title={`${f.factor_key} v${f.version}`}>
      <dl className="space-y-3 text-sm">
        <Row label="Applies to">{f.utility_type.replace('_', ' ')} · region {f.region} · scope {f.scope}</Row>
        <Row label="Valid for billing dates">{period(f)}</Row>
        <Row label="Value used">{trimDecimal(f.kgco2e_per_unit)} kg {f.ghg_basis} per {f.unit}</Row>
        <Row label="As published">
          {f.published_json.values.map((v) => `${v.value} ${v.mass_unit} ${v.gas}`).join(' + ')} per {f.published_json.per_unit}
          {f.published_json.gwp_set && ` (GWP ${f.published_json.gwp_set})`}
        </Row>
        <Row label="Derivation"><span className="break-words font-mono text-xs">{f.derivation}</span></Row>
        <Row label="Source">
          {f.source_name}{' '}
          <a className="break-all text-emerald-700 hover:underline" href={f.source_url} target="_blank" rel="noreferrer">{f.source_url}</a>
          {' '}({f.publication_year})
        </Row>
        {f.notes && <Row label="Notes"><span className="whitespace-pre-line">{f.notes}</span></Row>}
        {history.length > 1 && (
          <Row label="Versions">
            <ul className="space-y-1">
              {history.map((h) => (
                <li key={h.id} className={h.id === f.id ? 'font-medium' : 'text-slate-500'}>
                  v{h.version}: {trimDecimal(h.kgco2e_per_unit)} kg/{h.unit} · {h.created_at.slice(0, 10)} by {h.created_by === 'seed' ? 'seed' : 'admin'}
                </li>
              ))}
            </ul>
          </Row>
        )}
      </dl>
      {isAdmin && f.org_id && !f.superseded_by && (
        <div className="mt-4 border-t border-slate-200 pt-4">
          {showVersion ? (
            <NewVersion factor={f} onDone={(nf) => { setShowVersion(false); onVersioned(nf) }} onCancel={() => setShowVersion(false)} />
          ) : (
            <Button variant="secondary" onClick={() => setShowVersion(true)}>Create corrected version</Button>
          )}
        </div>
      )}
      {f.org_id === null && (
        <p className="mt-4 border-t border-slate-200 pt-3 text-xs text-slate-500">
          Global factor from the seed file. To use a different value, add an org-specific factor.
        </p>
      )}
    </Card>
  )
}

function Row({ label, children }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  )
}

function PublishedEditor({ values, onChange }) {
  const update = (i, k, v) => onChange(values.map((row, j) => (j === i ? { ...row, [k]: v } : row)))
  return (
    <div className="space-y-2">
      {values.map((row, i) => (
        <div key={i} className="flex gap-2">
          <input className={inputClass} required inputMode="decimal" pattern="[0-9]*\.?[0-9]+" placeholder="value"
            value={row.value} onChange={(e) => update(i, 'value', e.target.value)} />
          <select className={inputClass + ' !w-20'} value={row.mass_unit} onChange={(e) => update(i, 'mass_unit', e.target.value)}>
            {MASS.map((m) => <option key={m}>{m}</option>)}
          </select>
          <select className={inputClass + ' !w-24'} value={row.gas} onChange={(e) => update(i, 'gas', e.target.value)}>
            {GASES.map((g) => <option key={g}>{g}</option>)}
          </select>
          {values.length > 1 && <button type="button" className="text-sm text-slate-500" onClick={() => onChange(values.filter((_, j) => j !== i))}>✕</button>}
        </div>
      ))}
      <button type="button" className="text-sm text-emerald-700 hover:underline" onClick={() => onChange([...values, { gas: 'CH4', value: '', mass_unit: 'g' }])}>
        + add gas
      </button>
    </div>
  )
}

function CreateFactor({ onCreated }) {
  const [error, setError] = useState(null)
  const [form, setForm] = useState({
    factor_key: '', utility_type: 'electricity', region: '', per_unit: 'kWh',
    published: [{ gas: 'CO2e', value: '', mass_unit: 'kg' }], gwp_set: '',
    source_name: '', source_url: '', publication_year: new Date().getFullYear(),
    valid_from: '', valid_to: '', notes: '',
  })
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const multiGas = form.published.length > 1

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    try {
      const body = {
        ...form,
        publication_year: Number(form.publication_year),
        gwp_set: multiGas ? form.gwp_set || 'AR5' : null,
        valid_to: form.valid_to || null,
      }
      onCreated(await api('/factors', { method: 'POST', body }))
    } catch (err) {
      setError(err)
    }
  }

  return (
    <Card title="Add org-specific factor">
      <form onSubmit={submit} className="space-y-4">
        <ErrorBox error={error} />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Field label="Factor key" hint="Letters, digits, - _ ."><input className={inputClass} required value={form.factor_key} onChange={set('factor_key')} /></Field>
          <Field label="Utility">
            <select className={inputClass} value={form.utility_type} onChange={set('utility_type')}>
              <option value="electricity">Electricity (Scope 2)</option>
              <option value="natural_gas">Natural gas (Scope 1)</option>
            </select>
          </Field>
          <Field label="Region"><input className={inputClass} required value={form.region} onChange={set('region')} /></Field>
          <Field label="Per unit">
            <select className={inputClass} value={form.per_unit} onChange={set('per_unit')}>{UNITS.map((u) => <option key={u}>{u}</option>)}</select>
          </Field>
          <Field label="Valid from"><input type="date" className={inputClass} required value={form.valid_from} onChange={set('valid_from')} /></Field>
          <Field label="Valid to" hint="Empty = open-ended"><input type="date" className={inputClass} value={form.valid_to} onChange={set('valid_to')} /></Field>
        </div>
        <Field label="Published value(s), exactly as printed by the source">
          <PublishedEditor values={form.published} onChange={(published) => setForm({ ...form, published })} />
        </Field>
        {multiGas && <p className="text-xs text-slate-500">Several gases: combined with AR5 100-year GWPs.</p>}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-[1fr_1fr_8rem]">
          <Field label="Source name"><input className={inputClass} required value={form.source_name} onChange={set('source_name')} /></Field>
          <Field label="Source URL"><input type="url" className={inputClass} required value={form.source_url} onChange={set('source_url')} /></Field>
          <Field label="Year"><input type="number" className={inputClass} required value={form.publication_year} onChange={set('publication_year')} /></Field>
        </div>
        <Field label="Notes"><textarea className={inputClass} rows={2} value={form.notes} onChange={set('notes')} /></Field>
        <Button type="submit">Create factor</Button>
      </form>
    </Card>
  )
}

function NewVersion({ factor, onDone, onCancel }) {
  const [error, setError] = useState(null)
  const [published, setPublished] = useState(factor.published_json.values.map((v) => ({ ...v })))
  const [reason, setReason] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    try {
      onDone(await api(`/factors/${factor.id}/versions`, { method: 'POST', body: { published, reason } }))
    } catch (err) {
      setError(err)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBox error={error} />
      <Field label="Corrected published value(s)"><PublishedEditor values={published} onChange={setPublished} /></Field>
      <Field label="Reason for change"><input className={inputClass} required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      <div className="flex gap-2">
        <Button type="submit">Save v{factor.version + 1}</Button>
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  )
}
