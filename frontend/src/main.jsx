import { StrictMode, Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './index.css'
import { AuthProvider, useAuth } from './auth'
import { UiProvider } from './components/kit'
import Layout from './components/Layout'
import AuthPage from './pages/AuthPage'
import FacilitiesPage from './pages/FacilitiesPage'
import FactorsPage from './pages/FactorsPage'
import UploadPage from './pages/UploadPage'
import BillsPage from './pages/BillsPage'
import BillDetailPage from './pages/BillDetailPage'
import ReviewQueuePage from './pages/ReviewQueuePage'
import ReviewPage from './pages/ReviewPage'
import ReportsPage from './pages/ReportsPage'
import ScopePage from './pages/ScopePage'
import SummaryReportPage from './pages/SummaryReportPage'
import TeamPage from './pages/TeamPage'
// Charts (Recharts) load only when the dashboard is opened.
const ScopeDashboardPage = lazy(() => import('./pages/ScopeDashboardPage'))
const DashboardPage = lazy(() => import('./pages/DashboardPage'))

function RequireAuth({ children }) {
  const { me, loading } = useAuth()
  if (loading) return <p className="p-6 text-sm text-slate-500">Loading…</p>
  return me ? children : <Navigate to="/login" replace />
}

function App() {
  const { me } = useAuth()
  return (
    <Routes>
      <Route path="/login" element={me ? <Navigate to="/dashboard" replace /> : <AuthPage mode="login" />} />
      <Route path="/register" element={me ? <Navigate to="/dashboard" replace /> : <AuthPage mode="register" />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route path="/dashboard" element={<Suspense fallback={<p className="text-sm text-slate-500">Loading…</p>}><ScopeDashboardPage /></Suspense>} />
        <Route path="/scope/:n" element={<ScopePage />} />
        <Route path="/report" element={<SummaryReportPage />} />
        <Route path="/team" element={<TeamPage />} />
        {/* Earlier utility-bill pipeline (kept, not in the menu) */}
        <Route path="/bills-dashboard" element={<Suspense fallback={null}><DashboardPage /></Suspense>} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/facilities" element={<FacilitiesPage />} />
        <Route path="/factors" element={<FactorsPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/bills" element={<BillsPage />} />
        <Route path="/bills/:id" element={<BillDetailPage />} />
        <Route path="/review" element={<ReviewQueuePage />} />
        <Route path="/review/:billId" element={<ReviewPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <UiProvider>
          <App />
        </UiProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
