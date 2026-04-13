import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const roleOptions = [
  { label: 'Employee', value: 'candidate' },
  { label: 'Employer', value: 'employer' },
]

export default function AuthPage() {
  const { signin, signup } = useAuth()
  const navigate = useNavigate()

  const [mode, setMode] = useState('signin')
  const [form, setForm] = useState({
    name: '',
    email: '',
    password: '',
    confirmPassword: '',
    role: 'candidate',
  })
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const isSignin = mode === 'signin'

  const subtitle = useMemo(
    () => (isSignin ? 'Sign in to continue your hiring workflow.' : 'Create your account to get started.'),
    [isSignin],
  )

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setStatus('')

    if (!isSignin && form.password !== form.confirmPassword) {
      setError('Passwords must match.')
      return
    }

    setLoading(true)
    try {
      if (isSignin) {
        const response = await signin({ email: form.email.trim(), password: form.password })
        setStatus('Welcome back! Redirecting...')
        const destination = response?.user?.role === 'employer' ? '/employer' : '/employee'
        navigate(destination)
      } else {
        const response = await signup({
          name: form.name.trim(),
          email: form.email.trim(),
          password: form.password,
          role: form.role,
        })
        setStatus('Account created. Redirecting...')
        const destination = response?.user?.role === 'employer' ? '/employer' : '/employee'
        navigate(destination)
      }
    } catch (err) {
      setError(err.message || 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="panel panel--auth fade-in">
      <p className="label">Resume Shortlisting</p>
      <h1>{isSignin ? 'Welcome Back' : 'Create your account'}</h1>
      <p className="subtitle">{subtitle}</p>

      <form className="form-stack" onSubmit={submit}>
        <div className="toggle-group">
          <button
            type="button"
            className={`pill ${isSignin ? 'pill--active' : ''}`}
            onClick={() => setMode('signin')}
          >
            Sign In
          </button>
          <button
            type="button"
            className={`pill ${!isSignin ? 'pill--active' : ''}`}
            onClick={() => setMode('signup')}
          >
            Sign Up
          </button>
        </div>

        {!isSignin && (
          <input
            className="input"
            required
            placeholder="Full name"
            value={form.name}
            onChange={(event) => setForm((previous) => ({ ...previous, name: event.target.value }))}
          />
        )}

        <input
          className="input"
          required
          type="email"
          placeholder="Email address"
          value={form.email}
          onChange={(event) => setForm((previous) => ({ ...previous, email: event.target.value }))}
        />

        <input
          className="input"
          required
          type="password"
          placeholder="Password"
          value={form.password}
          onChange={(event) => setForm((previous) => ({ ...previous, password: event.target.value }))}
        />

        {!isSignin && (
          <input
            className="input"
            required
            type="password"
            placeholder="Confirm password"
            value={form.confirmPassword}
            onChange={(event) => setForm((previous) => ({ ...previous, confirmPassword: event.target.value }))}
          />
        )}

        {!isSignin && (
          <div className="role-chip-row">
            {roleOptions.map((option) => (
              <label key={option.value} className={`role-chip ${form.role === option.value ? 'role-chip--active' : ''}`}>
                <input
                  className="sr-only"
                  type="radio"
                  name="role"
                  value={option.value}
                  checked={form.role === option.value}
                  onChange={(event) =>
                    setForm((previous) => ({ ...previous, role: event.target.value }))
                  }
                />
                {option.label}
              </label>
            ))}
          </div>
        )}

        {error && <p className="error-text">{error}</p>}
        {status && <p className="success-text">{status}</p>}

        <button className="action-btn" disabled={loading} type="submit">
          {loading ? 'Please wait...' : isSignin ? 'Sign In' : 'Create account'}
        </button>
      </form>
    </section>
  )
}
