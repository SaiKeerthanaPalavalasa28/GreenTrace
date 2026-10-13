import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth'

const NAV = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/upload', label: 'Upload' },
  { to: '/review', label: 'Review', badge: 'needs_review' },
  { to: '/bills', label: 'Bills' },
  { to: '/reports', label: 'Reports' },
  { to: '/facilities', label: 'Facilities' },
  { to: '/factors', label: 'Emission factors' },
]

export default function Layout() {
  const { me, logout } = useAuth()
  const location = useLocation()
  const [counts, setCounts] = useState(null)
  // Refresh on navigation and every 30 s so the pending count is never stale for long.
  useEffect(() => {
    const load = () => api('/review/counts').then(setCounts).catch(() => {})
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [location.pathname])
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <span className="text-lg font-semibold text-emerald-800">GreenTrace</span>
          <nav className="flex flex-wrap gap-1">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm ${isActive ? 'bg-emerald-50 font-medium text-emerald-800' : 'text-slate-600 hover:bg-slate-100'}`
                }
              >
                {n.label}
                {n.badge && counts?.[n.badge] > 0 && (
                  <span className="ml-1.5 rounded-full bg-amber-500 px-1.5 py-0.5 text-xs font-semibold text-white">{counts[n.badge]}</span>
                )}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex min-w-0 max-w-full items-center gap-3 text-sm text-slate-600">
            <span className="min-w-0 truncate">
              {me.organization.name} · {me.user.email} ({me.user.role})
            </span>
            <button onClick={logout} className="whitespace-nowrap text-emerald-700 hover:underline">
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
