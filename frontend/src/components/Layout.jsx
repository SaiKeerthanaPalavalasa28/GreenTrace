import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth'
import { Logo } from './ui'

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
  const initial = (me.user.full_name || me.user.email || '?').trim()[0].toUpperCase()
  return (
    <div className="min-h-screen">
      {/* Floating frosted bar, Pinterest-style: logo, pill navigation, profile on the right. */}
      <header className="sticky top-0 z-30 px-3 pt-3">
        <div className="glass-strong mx-auto flex max-w-[88rem] items-center gap-3 rounded-full px-3 py-2 sm:px-4">
          <NavLink to="/dashboard" className="flex shrink-0 items-center gap-2 pr-1" aria-label="GreenTrace home">
            <Logo />
            <span className="hidden font-display text-lg font-extrabold tracking-tight text-emerald-900 sm:inline">GreenTrace</span>
          </NavLink>
          <nav className="flex min-w-0 flex-1 gap-1 overflow-x-auto [scrollbar-width:none]" aria-label="Main">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) =>
                  `flex shrink-0 items-center whitespace-nowrap rounded-full px-3.5 py-2 text-sm font-semibold transition-colors ${
                    isActive ? 'bg-emerald-900 text-white shadow' : 'text-slate-700 hover:bg-white/80'
                  }`
                }
              >
                {n.label}
                {n.badge && counts?.[n.badge] > 0 && (
                  <span className="ml-1.5 rounded-full bg-amber-400 px-1.5 py-0.5 text-[11px] font-bold leading-none text-slate-900">{counts[n.badge]}</span>
                )}
              </NavLink>
            ))}
          </nav>
          <div className="flex shrink-0 items-center gap-2">
            <div className="hidden min-w-0 text-right leading-tight lg:block">
              <div className="max-w-[12rem] truncate text-sm font-semibold text-slate-900">{me.organization.name}</div>
              <div className="max-w-[12rem] truncate text-xs text-slate-500">{me.user.email} · {me.user.role}</div>
            </div>
            <span
              title={`${me.user.email} (${me.user.role})`}
              className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-amber-300 to-ember text-sm font-bold text-white shadow"
            >
              {initial}
            </span>
            <button onClick={logout} className="rounded-full px-3 py-2 text-sm font-semibold text-slate-600 transition-colors hover:bg-white/80 hover:text-emerald-800">
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[88rem] px-4 pb-16 pt-8 sm:px-6">
        <Outlet />
      </main>
    </div>
  )
}
