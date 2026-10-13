export function Button({ variant = 'primary', className = '', ...props }) {
  const styles = {
    primary: 'bg-emerald-700 text-white hover:bg-emerald-800 disabled:bg-emerald-300',
    secondary: 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 disabled:text-slate-400',
  }
  return (
    <button
      className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${styles[variant]} ${className}`}
      {...props}
    />
  )
}

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  )
}

export const inputClass =
  'w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm focus:border-emerald-600 focus:outline-none focus:ring-1 focus:ring-emerald-600'

export function ErrorBox({ error }) {
  if (!error) return null
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      {error.message || String(error)}
    </div>
  )
}

export function Card({ title, actions, children }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
          <h2 className="text-base font-semibold">{title}</h2>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}
