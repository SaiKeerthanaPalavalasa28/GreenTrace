import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
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
  const { login, register } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    email: '', password: '', org_name: '', full_name: '',
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
      else await register({ ...form, fiscal_year_start_month: Number(form.fiscal_year_start_month) })
      navigate('/dashboard')
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto grid min-h-screen max-w-6xl items-center gap-10 px-4 py-10 lg:grid-cols-[1.1fr_1fr]">
      <div className="hidden lg:block">
        <Logo className="h-14 w-14" />
        <h1 className="mt-6 text-5xl font-extrabold leading-[1.05] text-emerald-950">
          Carbon numbers an auditor can <span className="bg-gradient-to-r from-emerald-600 to-emerald-400 bg-clip-text text-transparent">trace</span>.
        </h1>
        <p className="mt-4 max-w-md text-lg text-slate-600">
          Turn utility bills into an auditable emissions report. The AI reads, the code calculates, a person approves.
        </p>
        <div className="mt-8 flex flex-wrap gap-2">
          {['Bill → page → text', 'Sourced emission factors', 'Human review', 'PDF audit report'].map((t, i) => (
            <span key={t} className="glass rise rounded-full px-4 py-2 text-sm font-semibold text-emerald-900" style={{ animationDelay: `${i * 80}ms` }}>{t}</span>
          ))}
        </div>
      </div>
      <form onSubmit={submit} className="glass-strong rise w-full max-w-md space-y-4 justify-self-center rounded-[2rem] p-7 sm:p-8">
        <div>
          <div className="mb-4 flex items-center gap-2 lg:hidden"><Logo /><span className="font-display text-lg font-extrabold text-emerald-900">GreenTrace</span></div>
          <h2 className="text-2xl font-extrabold text-slate-900">
            {mode === 'login' ? 'Welcome back' : 'Create your account'}
          </h2>
          <p className="text-sm text-slate-600">
            {mode === 'login' ? 'Sign in to your organization' : 'Set up an organization account'}
          </p>
        </div>
        <ErrorBox error={error} />
        {mode === 'register' && (
          <>
            <Field label="Organization name">
              <input className={inputClass} required value={form.org_name} onChange={set('org_name')} />
            </Field>
            <Field label="Your name">
              <input className={inputClass} value={form.full_name} onChange={set('full_name')} />
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
        <Field label="Email">
          <input type="email" autoComplete="email" className={inputClass} required value={form.email} onChange={set('email')} />
        </Field>
        <Field label="Password" hint={mode === 'register' ? 'At least 10 characters' : undefined}>
          <input
            type="password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            minLength={mode === 'register' ? 10 : undefined}
            className={inputClass}
            required
            value={form.password}
            onChange={set('password')}
          />
        </Field>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
        </Button>
        <p className="text-center text-sm text-slate-600">
          {mode === 'login' ? (
            <>No account? <Link className="font-semibold text-emerald-700 hover:underline" to="/register">Create one</Link></>
          ) : (
            <>Already registered? <Link className="font-semibold text-emerald-700 hover:underline" to="/login">Sign in</Link></>
          )}
        </p>
      </form>
    </div>
  )
}
