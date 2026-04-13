import { Navigate, Route, Routes } from 'react-router-dom'
import EmployeePage from './pages/EmployeePage'
import EmployerPage from './pages/EmployerPage'
import AuthPage from './pages/AuthPage'
import ProtectedRoute from './components/ProtectedRoute'
import { useAuth } from './context/AuthContext'

function HomeRedirect() {
  const { user } = useAuth()

  if (!user) {
    return <Navigate to="/auth" replace />
  }

  if (user.role === 'candidate') {
    return <Navigate to="/employee" replace />
  }

  return <Navigate to="/employer" replace />
}

export default function App() {
  const { user, logout } = useAuth()

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar__brand">Resume Shortlisting</div>
        {user && (
          <button className="ghost-btn" onClick={logout}>
            Sign out
          </button>
        )}
      </header>
      <main className="content">
        <Routes>
          <Route path="/auth" element={<AuthPage />} />
          <Route
            path="/employee"
            element={
              <ProtectedRoute roles={['candidate']}>
                <EmployeePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/employer"
            element={
              <ProtectedRoute roles={['employer']}>
                <EmployerPage />
              </ProtectedRoute>
            }
          />
          <Route path="/" element={<HomeRedirect />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
