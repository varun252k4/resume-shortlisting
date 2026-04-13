import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function ProtectedRoute({ children, roles }) {
  const { user } = useAuth()

  if (!user) {
    return <Navigate to="/auth" replace />
  }

  if (roles.length && !roles.includes(user.role)) {
    if (user.role === 'candidate') {
      return <Navigate to="/employee" replace />
    }
    return <Navigate to="/employer" replace />
  }

  return children
}
