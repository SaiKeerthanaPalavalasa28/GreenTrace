import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth'
import { Icon } from './kit'
import { Logo } from './ui'

const NAV = [
  { to: '/dashboard', label: 'Dashboard', icon: 'dashboard' },
  { to: '/scope/1', label: 'Scope 1', hint: 'Direct', icon: 'flame' },
  { to: '/scope/2', label: 'Scope 2', hint: 'Energy', icon: 'bolt' },
  { to: '/scope/3', label: 'Scope 3', hint: 'Value chain', icon: 'globe' },
  { to: '/report', label: 'Report', icon: 'report' },
  { to: '/team', label: 'Team', icon: 'team' },
]

const ROLE_COPY = { admin: 'Full access', manager: 'View only', auditor: 'View only' }

export default function Layout() {
  const { me, logout, canEdit } = useAuth()
  const name = (me.user.full_name || me.user.email.split('@')[0]).trim()
  const initial = name[0].toUpperCase()

  return (
    <div className="min-h-screen lg:pl-72">
      {/* Desktop sidebar */}
      <aside className="glass-strong fixed inset-y-3 left-3 z-30 hidden w-64 flex-col rounded-[2rem] p-4 lg:flex">
        <NavLink to="/dashboard" className="flex items-center gap-3 px-2 pb-5 pt-2" aria-label="GreenTrace home">
          <Logo className="h-10 w-10" />
          <div className="leading-tight">
            <div className="font-display text-xl font-semibold tracking-tight text-emerald-950" style={{ fontFamily: 'Fraunces, serif' }}>GreenTrace</div>
            <div className="text-[11px] font-medium uppercase tracking-widest text-emerald-700/70">Carbon, calmly</div>
          </div>
        </NavLink>

        <nav className="flex flex-1 flex-col gap-1" aria-label="Main">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <Icon name={n.icon} />
              <span className="flex-1">{n.label}</span>
              {n.hint && <span className="text-[11px] font-medium opacity-60">{n.hint}</span>}
            </NavLink>
          ))}
        </nav>

        <div className="rounded-2xl bg-emerald-50/80 p-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-emerald-800/70">{me.organization.name}</div>
          <div className="mt-2 flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-400 to-emerald-700 text-sm font-bold text-white shadow">{initial}</span>
            <div className="min-w-0 leading-tight">
              <div className="truncate text-sm font-semibold">{name}</div>
              <div className="flex items-center gap-1 text-xs text-slate-600"><Icon name={canEdit ? 'edit' : 'eye'} className="h-3 w-3" />{me.user.role} · {ROLE_COPY[me.user.role] || 'Full access'}</div>
            </div>
          </div>
          <button onClick={logout} className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl py-2 text-sm font-semibold text-slate-600 transition hover:bg-white hover:text-emerald-800">
            <Icon name="logout" className="h-4 w-4" />Sign out
          </button>
        </div>
      </aside>

      {/* Mobile top bar */}
      <header className="glass-strong sticky top-0 z-30 flex items-center gap-3 px-4 py-3 lg:hidden">
        <Logo className="h-9 w-9" />
        <div className="min-w-0 flex-1 leading-tight">
          <div className="text-lg font-semibold" style={{ fontFamily: 'Fraunces, serif' }}>GreenTrace</div>
          <div className="truncate text-xs text-slate-600">{me.organization.name} · {me.user.role}</div>
        </div>
        <button onClick={logout} aria-label="Sign out" className="rounded-full p-2 text-slate-600 hover:bg-white"><Icon name="logout" /></button>
      </header>

      <main className="mx-auto max-w-6xl px-4 pb-16 pt-6 sm:px-8 lg:pt-10">
        {!canEdit && (
          <div className="rise mb-6 flex items-center gap-2 rounded-2xl bg-white/70 px-4 py-2.5 text-sm text-slate-700">
            <Icon name="lock" className="h-4 w-4 text-emerald-700" />
            You're signed in as <b>{me.user.role}</b> - you can view everything, only the admin can make changes.
          </div>
        )}
        <Outlet />
      </main>

      {/* Mobile bottom navigation */}
      <nav className="glass-strong fixed inset-x-3 bottom-3 z-30 flex justify-around rounded-full px-2 py-1.5 lg:hidden" aria-label="Main">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} className={({ isActive }) => `flex flex-col items-center gap-0.5 rounded-full px-2.5 py-1.5 text-[10px] font-semibold transition ${isActive ? 'bg-emerald-800 text-white' : 'text-slate-600'}`}>
            <Icon name={n.icon} className="h-5 w-5" />{n.label.replace('Scope ', 'S')}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
