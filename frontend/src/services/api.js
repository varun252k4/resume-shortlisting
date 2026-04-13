const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

function resolveErrorBody(payload) {
  if (!payload) {
    return 'Request failed. Please try again.'
  }

  if (typeof payload.error === 'string') {
    return payload.error
  }

  if (typeof payload.detail === 'string') {
    return payload.detail
  }

  if (typeof payload.message === 'string') {
    return payload.message
  }

  return JSON.stringify(payload)
}

export async function apiRequest(path, method = 'GET', body = null) {
  const token = localStorage.getItem('token')
  const isFormData = body instanceof FormData
  const headers = {}

  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  if (body && !isFormData && method !== 'GET') {
    headers['Content-Type'] = 'application/json'
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? (isFormData ? body : JSON.stringify(body)) : null,
  })

  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(resolveErrorBody(payload))
  }

  return payload
}
