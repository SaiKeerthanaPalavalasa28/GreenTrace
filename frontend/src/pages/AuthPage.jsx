import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { LeafArt } from '../components/kit'
import { Button, ErrorBox, Field, Logo, inputClass } from '../components/ui'

const FRAMEWORKS = [
  { value: 'BRSR', label: 'BRSR (India, SEBI)', region: 'IN', fyStart: 4 },
  { value: 'SECR', label: 'SECR (UK)', region: 'UK', fyStart: 1 },
  { value: 'CSRD', label: 'CSRD (EU)', region: 'UK', fyStart: 1 },
  { value: 'EPA', label: 'US EPA', region: 'US', fyStart: 1 },
  { value: 'OTHER', label: 'Other', region: 'IN', fyStart: 1 },
]

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

export default function AuthPage({ mode }) {
  const { login, registerOrg } = useAuth()
  const [sent, setSent] = useState(null)
  const navigate = useNavigate()
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    email: '', password: '', org_name: '',
    admin_email: '', manager_email: '', auditor_email: '',
    reporting_framework: 'BRSR', default_region: 'IN', fiscal_year_start_month: 4,
  })
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const onFramework = (e) => {
    const fw = FRAMEWORKS.find((f) => f.value === e.target.value)
    setForm({ ...form, reporting_framework: fw.value, default_region: fw.region, fiscal_year_start_month: fw.fyStart })
  }

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'login') await login(form.email, form.password)
      else {
        const { email, password, ...org } = form
        setSent(await registerOrg({ ...org, fiscal_year_start_month: Number(org.fiscal_year_start_month) }))
        return
      }
      navigate('/dashboard')
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  if (sent) {
    return (
      <div className="mx-auto flex min-h-screen max-w-lg items-center px-4 py-10">
        <div className="glass-strong w-full space-y-4 rounded-[2rem] p-8">
          <Logo />
          <h2 className="text-3xl text-emerald-950">Check your inboxes</h2>
          <p className="text-sm text-slate-600"><b>{sent.organization}</b> is registered. Each login was emailed separately:</p>
          <ul className="space-y-2 text-sm">
            {sent.delivery.map((d) => (
              <li key={d.role} className={d.sent ? 'text-emerald-800' : 'text-red-700'}>
                {d.sent ? '✔' : '✖'} <b>{d.role}</b> - {d.email} {d.sent ? '(sent)' : `- not sent: ${d.error}. The admin can resend it from the Team page.`}
              </li>
            ))}
          </ul>
          <p className="text-xs text-slate-500">Check spam folders too. Then sign in with the email and password you received.</p>
          <Link to="/login" className="inline-block rounded-full bg-emerald-700 px-5 py-2 text-sm font-semibold text-white">Go to sign in</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto grid min-h-screen max-w-6xl items-center gap-10 px-4 py-10 lg:grid-cols-[1.1fr_1fr]">
      <div className="hidden lg:block">
        <div className="flex items-center gap-3"><Logo className="h-12 w-12" /><span className="text-2xl font-semibold text-emerald-950" style={{ fontFamily: 'Fraunces, serif' }}>GreenTrace</span></div>
        <h1 className="mt-10 text-6xl leading-[1.04] text-emerald-950">
          Know your carbon.<br /><span className="bg-gradient-to-r from-emerald-600 to-teal-400 bg-clip-text italic text-transparent">Breathe easier.</span>
        </h1>
        <p className="mt-5 max-w-md text-lg text-slate-600">
          Track Scope 1, 2 and 3 emissions from your documents, catch suspicious entries, and always know how much of your carbon budget is left.
        </p>
        <div className="stagger mt-8 flex flex-wrap gap-2">
          {['Scope 1 · 2 · 3', 'Suspicious-entry checks', 'Green · orange · red status', 'Improvement report'].map((t) => (
            <span key={t} className="glass rounded-full px-4 py-2 text-sm font-semibold text-emerald-900">{t}</span>
          ))}
        </div>
        <LeafArt className="mt-10 h-40 w-40" />
      </div>
      <form onSubmit={submit} className="glass-strong rise w-full max-w-md space-y-4 justify-self-center rounded-[2.25rem] p-7 sm:p-9">
        <div>
          <div className="mb-4 flex items-center gap-2 lg:hidden"><Logo /><span className="text-lg font-semibold text-emerald-900" style={{ fontFamily: 'Fraunces, serif' }}>GreenTrace</span></div>
          <h2 className="text-3xl text-emerald-950">
            {mode === 'login' ? 'Welcome back' : 'Register your organization'}
          </h2>
          <p className="text-sm text-slate-600">
            {mode === 'login' ? 'Sign in to your organization' : 'Admin, manager and auditor logins are emailed to you'}
          </p>
        </div>
        <ErrorBox error={error} />
        {mode === 'register' && (
          <>
            <Field label="Organization name">
              <input className={inputClass} required value={form.org_name} onChange={set('org_name')} />
            </Field>
            <Field label="Reporting framework">
              <select className={inputClass} value={form.reporting_framework} onChange={onFramework}>
                {FRAMEWORKS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
              </select>
            </Field>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Default region" hint="Grid region code, e.g. IN, UK, US-CAMX">
                <input className={inputClass} required value={form.default_region} onChange={set('default_region')} />
              </Field>
              <Field label="Reporting year starts">
                <select className={inputClass} value={form.fiscal_year_start_month} onChange={set('fiscal_year_start_month')}>
                  {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
                </select>
              </Field>
            </div>
          </>
        )}
        {mode === 'login' ? (
          <>
            <Field label="Email">
              <input type="email" autoComplete="email" className={inputClass} required value={form.email} onChange={set('email')} />
            </Field>
            <Field label="Password" hint="Use the password we emailed to you">
              <input type="password" autoComplete="current-password" className={inputClass} required value={form.password} onChange={set('password')} />
            </Field>
          </>
        ) : (
          <>
            <p className="rounded-xl bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
              Enter three company email addresses. Each person receives their <b>own</b> login by email - there is no password to choose. Use real, reachable mailboxes.
            </p>
            <Field label="Admin email" hint="Can view and edit everything"><input type="email" className={inputClass} required value={form.admin_email} onChange={set('admin_email')} /></Field>
            <Field label="Manager email" hint="View only"><input type="email" className={inputClass} required value={form.manager_email} onChange={set('manager_email')} /></Field>
            <Field label="Auditor email" hint="View only"><input type="email" className={inputClass} required value={form.auditor_email} onChange={set('auditor_email')} /></Field>
          </>
        )}
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Register and email logins'}
        </Button>
        <p className="text-center text-sm text-slate-600">
          {mode === 'login' ? (
            <>New organization? <Link className="font-semibold text-emerald-700 hover:underline" to="/register">Register</Link></>
          ) : (
            <>Already registered? <Link className="font-semibold text-emerald-700 hover:underline" to="/login">Sign in</Link></>
          )}
        </p>
      </form>
    </div>
  )
}
