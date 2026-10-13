import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth'
import { Button, Card, ErrorBox, Field, inputClass } from '../components/ui'

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
      <h1 className="text-xl font-semibold">Facilities</h1>
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
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-slate-500">
                <tr><th className="py-2 pr-4 font-medium">Name</th><th className="py-2 pr-4 font-medium">Address</th><th className="py-2 pr-4 font-medium">Region</th><th /></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {facilities.map((f) => (
                  <tr key={f.id}>
                    <td className="py-2 pr-4 font-medium">{f.name}</td>
                    <td className="py-2 pr-4 text-slate-600">{f.address}</td>
                    <td className="py-2 pr-4"><code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{f.region}</code></td>
                    <td className="py-2 text-right">
                      {isAdmin && <button className="text-emerald-700 hover:underline" onClick={() => edit(f)}>Edit</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
