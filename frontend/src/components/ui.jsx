export function Button({ variant = 'primary', className = '', ...props }) {
  const styles = {
    primary: 'btn-primary text-white disabled:opacity-50 disabled:shadow-none',
    secondary: 'glass text-emerald-950 hover:bg-white disabled:text-slate-400',
    danger: 'bg-red-600 text-white hover:bg-red-700 disabled:opacity-50',
  }
  return (
    <button
      className={`rounded-full px-5 py-2.5 text-sm font-semibold transition-all duration-300 active:scale-[0.97] disabled:cursor-not-allowed ${styles[variant]} ${className}`}
      {...props}
    />
  )
}

// Same look as <Button>, for router <Link>s.
export const linkButtonClass =
  'btn-primary inline-block rounded-full px-5 py-2.5 text-sm font-semibold text-white transition-all duration-300 active:scale-[0.97]'

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  )
}

export const inputClass =
  'w-full rounded-2xl border border-emerald-900/10 bg-white/80 px-4 py-2.5 text-sm shadow-sm transition placeholder:text-slate-400 hover:border-emerald-700/30 focus:border-emerald-600 focus:bg-white focus:outline-none focus:ring-4 focus:ring-emerald-500/15'

export function ErrorBox({ error }) {
  if (!error) return null
  return (
    <div role="alert" className="rounded-2xl border border-red-200/80 bg-red-50/80 px-4 py-3 text-sm text-red-800 backdrop-blur">
      {error.message || String(error)}
    </div>
  )
}

export function Card({ title, actions, children, className = '' }) {
  return (
    <section className={`glass rise rounded-[1.75rem] ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200/60 px-5 py-4">
          <h2 className="text-lg">{title}</h2>
          {actions}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  )
}

export function PageHeader({ title, subtitle, children }) {
  return (
    <div className="rise flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-3xl text-emerald-950 sm:text-4xl">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-slate-600">{subtitle}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  )
}

export function Logo({ className = 'h-9 w-9' }) {
  return (
    <span className={`inline-flex items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-emerald-800 shadow-md shadow-emerald-900/30 ${className}`}>
      <svg viewBox="0 0 32 32" className="h-3/5 w-3/5" fill="none" stroke="white" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true">
        <path d="M7 24c0-9 6-14 18-14 0 10-5 16-14 16m0 0c1-5 5-9 10-11" />
      </svg>
    </span>
  )
}
