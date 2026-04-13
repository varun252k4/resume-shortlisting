import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { apiRequest } from '../services/api'

const AuthContext = createContext(null)

function decodeJwtPayload(token) {
  if (!token || typeof token !== 'string') {
    return null
  }

  const parts = token.split('.')
  if (parts.length !== 3) {
    return null
  }

  try {
    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4)
    const decoded = atob(padded)
    return JSON.parse(decoded)
  } catch {
    return null
  }
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(null)
  const [user, setUser] = useState(null)

  useEffect(() => {
    const storedToken = localStorage.getItem('token')
    if (!storedToken) {
      return
    }

    const payload = decodeJwtPayload(storedToken)
    if (!payload) {
      localStorage.removeItem('token')
      return
    }

    setToken(storedToken)
    setUser({
      id: payload.sub,
      name: payload.name,
      email: payload.email,
      role: payload.role,
    })
  }, [])

  const setSession = (sessionToken, sessionUser) => {
    const payload = decodeJwtPayload(sessionToken)
    localStorage.setItem('token', sessionToken)
    setToken(sessionToken)
    if (sessionUser) {
      setUser(sessionUser)
      return
    }

    setUser(payload)
  }

  const signin = async (payload) => {
    const response = await apiRequest('/auth/login', 'POST', payload)
    setSession(response.token, response.user)
    return response
  }

  const signup = async ({ role, ...payload }) => {
    const response = await apiRequest('/auth/signup', 'POST', {
      ...payload,
      role,
    })
    setSession(response.token, response.user)
    return response
  }

  const logout = () => {
    localStorage.removeItem('token')
    setToken(null)
    setUser(null)
  }

  const value = useMemo(
    () => ({
      token,
      user,
      signin,
      signup,
      logout,
    }),
    [token, user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return ctx
}
