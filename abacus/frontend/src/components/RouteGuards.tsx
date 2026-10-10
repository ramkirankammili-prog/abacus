import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

function Splash() {
  return <main className="auth-skeleton" aria-label="Loading workspace">
    <div className="auth-skeleton__brand"><span className="skeleton-line skeleton-line--short"/><span className="skeleton-line"/></div>
    <div className="auth-skeleton__card"><span className="skeleton-line skeleton-line--short"/><span className="skeleton-line"/><span className="skeleton-line"/><span className="skeleton-line skeleton-line--button"/></div>
  </main>
}

/** Only signed-in users can see the app; everyone else is sent to /signin. */
export function ProtectedRoute() {
  const { session, loading } = useAuth()
  if (loading) return <Splash />
  return session ? <Outlet /> : <Navigate to="/signin" replace />
}

/** Sign In / Sign Up pages: signed-in users go straight to their role-specific workspace. */
export function PublicOnlyRoute() {
  const { session, loading } = useAuth()
  if (loading) return <Splash />
  return session ? <Navigate to="/" replace /> : <Outlet />
}
