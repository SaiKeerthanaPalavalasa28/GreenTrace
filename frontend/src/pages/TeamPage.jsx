import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth'
import { useUi } from '../components/kit'
import { Button, Card, ErrorBox, Field, PageHeader, inputClass } from '../components/ui'

const ACCESS = { admin: 'Can edit everything', manager: 'View only', auditor: 'View only' }

function ChangePassword() {
  const { toast } = useUi()
  const [cur, setCur] = useState('')
  const [next, setNext] = useState('')
  const [msg, setMsg] = useState(null)
  const [error, setError] = useState(null)
  const submit = async (e) => {
    e.preventDefault()
    setError(null); setMsg(null)
    try {
      await api('/auth/change-password', { method: 'POST', body: { current_password: cur, new_password: next } })
      setMsg('Password changed.'); toast('Password changed'); setCur(''); setNext('')
    } catch (err) { setError(err) }
  }
  return (
    <form onSubmit={submit} className="max-w-sm space-y-3">
      <ErrorBox error={error} />
      {msg && <p className="text-sm font-semibold text-emerald-700">{msg}</p>}
      <Field label="Current password (from your email)"><input type="password" required className={inputClass} value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" /></Field>
      <Field label="New password" hint="At least 10 characters"><input type="password" required minLength={10} className={inputClass} value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" /></Field>
      <Button type="submit">Change password</Button>
    </form>
  )
}

export default function TeamPage() {
  const { me, canEdit } = useAuth()
  const { toast, ask } = useUi()
  const [users, setUsers] = useState(null)
  const [status, setStatus] = useState({})
  const [error, setError] = useState(null)
  useEffect(() => { if (canEdit) api('/users').then(setUsers).catch(setError) }, [canEdit])

  const resend = async (u) => {
    if (!(await ask({ title: 'Send a new password?', body: `${u.email} will get a new password by email. Their old one stops working.`, confirmLabel: 'Send' }))) return
    setStatus((s) => ({ ...s, [u.id]: 'Sending…' }))
    try {
      await api(`/users/${u.id}/resend-credentials`, { method: 'POST' })
      setStatus((s) => ({ ...s, [u.id]: 'Sent ✔' })); toast(`New credentials sent to ${u.email}`)
    } catch (e) { setStatus((s) => ({ ...s, [u.id]: `Failed: ${e.message}` })); toast(e.message, 'error') }
  }
  return (
    <div className="space-y-6">
      <PageHeader title="Team" subtitle={`${me.organization.name} · signed in as ${me.user.email} (${me.user.role})`} />
      <ErrorBox error={error} />
      {canEdit && users && (
        <Card title="People with access">
          <ul className="divide-y divide-slate-200/70">
            {users.map((u) => (
              <li key={u.id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm">
                <div className="min-w-0 flex-1"><div className="truncate font-semibold">{u.email}</div><div className="text-xs text-slate-500">{u.role} · {ACCESS[u.role] || 'Can edit'}</div></div>
                {u.id !== me.user.id && <Button variant="secondary" onClick={() => resend(u)}>Resend credentials</Button>}
                {status[u.id] && <span className="text-xs text-slate-600">{status[u.id]}</span>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card title="Change my password"><ChangePassword /></Card>
    </div>
  )
}
