import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth'
import { Button, Card, ErrorBox, Field, PageHeader, inputClass } from '../components/ui'

const EMPTY = { name: '', address: '', region: '' }

export default function FacilitiesPage() {
  const { me, isAdmin } = useAuth()
  const [facilities, setFacilities] = useState([])
  const [regions, setRegions] = useState([])
  const [form, setForm] = useState({ ...EMPTY, region: me.organization.default_region })
  const [editingId, setEditingId] = useState(null)
  const [error, setError] = useState(null)

  const load = async () => {
    try {
      const [f, r] = await Promise.all([api('/facilities'), api('/factors/regions')])
      setFacilities(f)
      setRegions(r)
    } catch (err) {
      setError(err)
    }
  }
  useEffect(() => { load() }, [])

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    try {
      if (editingId) await api(`/facilities/${editingId}`, { method: 'PATCH', body: form })
      else await api('/facilities', { method: 'POST', body: form })
      setForm({ ...EMPTY, region: me.organization.default_region })
      setEditingId(null)
      load()
    } catch (err) {
      setError(err)
    }
  }

  const edit = (f) => {
    setEditingId(f.id)
    setForm({ name: f.name, address: f.address, region: f.region })
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Facilities" subtitle="The sites your bills belong to. Each one maps to a grid region for emission factors." />
      <ErrorBox error={error} />

      {isAdmin && (
        <Card title={editingId ? 'Edit facility' : 'Add facility'}>
          <form onSubmit={submit} className="grid grid-cols-1 gap-4 md:grid-cols-[1fr_1.5fr_10rem_auto] md:items-end">
            <Field label="Name">
              <input className={inputClass} required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field label="Address">
              <input className={inputClass} value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
            </Field>
            <Field label="Grid region">
              <select className={inputClass} value={form.region} onChange={(e) => setForm({ ...form, region: e.target.value })}>
                {!regions.includes(form.region) && <option value={form.region}>{form.region || '—'}</option>}
                {regions.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </Field>
            <div className="flex gap-2">
              <Button type="submit">{editingId ? 'Save' : 'Add'}</Button>
              {editingId && (
                <Button type="button" variant="secondary" onClick={() => { setEditingId(null); setForm({ ...EMPTY, region: me.organization.default_region }) }}>
                  Cancel
                </Button>
              )}
            </div>
          </form>
        </Card>
      )}

      <Card title={`${facilities.length} facilit${facilities.length === 1 ? 'y' : 'ies'}`}>
        {facilities.length === 0 ? (
          <p className="text-sm text-slate-500">No facilities yet. Bills are uploaded against a facility, so add one first.</p>
        ) : (
          <div className="masonry">
            {facilities.map((f, i) => (
              <article key={f.id} className="pin glass rise rounded-3xl p-5" style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}>
                <div className="flex h-20 items-end rounded-2xl bg-gradient-to-br from-emerald-200 via-emerald-100 to-amber-100 p-3" aria-hidden="true">
                  <span className="text-3xl">🏭</span>
                </div>
                <h3 className="mt-3 text-base font-bold">{f.name}</h3>
                <p className="min-h-5 text-sm text-slate-600">{f.address || 'No address'}</p>
                <div className="mt-3 flex items-center justify-between">
                  <code className="rounded-full bg-emerald-900/10 px-2.5 py-0.5 text-xs font-semibold text-emerald-900">{f.region}</code>
                  {isAdmin && <button className="rounded-full px-3 py-1 text-sm font-semibold text-emerald-700 hover:bg-white/80" onClick={() => edit(f)}>Edit</button>}
                </div>
              </article>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
