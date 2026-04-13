import { useEffect, useState } from 'react'
import { apiRequest } from '../services/api'

function normalizeResumeList(data) {
  if (!data) {
    return []
  }

  if (Array.isArray(data)) {
    return data
  }

  if (Array.isArray(data.resumes)) {
    return data.resumes
  }

  return []
}

export default function EmployeePage() {
  const [resumes, setResumes] = useState([])
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const loadResumes = async () => {
    setError('')
    try {
      const response = await apiRequest('/candidate/resumes', 'GET')
      setResumes(normalizeResumeList(response))
    } catch (err) {
      setError(err.message || 'Failed to load resumes')
    }
  }

  useEffect(() => {
    loadResumes()
  }, [])

  const onUpload = async (event) => {
    event.preventDefault()
    if (!file) {
      setError('Please choose a file first.')
      return
    }

    const payload = new FormData()
    payload.append('files', file)

    setLoading(true)
    setStatus('')
    setError('')
    try {
      const response = await apiRequest('/candidate/resumes', 'POST', payload)
      setStatus(response?.message || 'Resume uploaded successfully.')
      setFile(null)
      await loadResumes()
    } catch (err) {
      setError(err.message || 'Upload failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="panel fade-in">
      <header className="stack-head">
        <div>
          <p className="label">Employee dashboard</p>
          <h1>Upload your resume</h1>
        </div>
      </header>

      <form className="upload-box" onSubmit={onUpload}>
        <input
          type="file"
          accept=".pdf,.docx,.doc,.txt"
          onChange={(event) => setFile(event.target.files?.[0] || null)}
        />
        <button className="action-btn" disabled={loading} type="submit">
          {loading ? 'Uploading...' : 'Upload Resume'}
        </button>
      </form>

      {status && <p className="success-text">{status}</p>}
      {error && <p className="error-text">{error}</p>}

      <h2>Your uploaded resumes</h2>
      <div className="card-grid">
        {resumes.map((resume) => {
          const title = resume.file_name || resume.filename || resume.name || `Resume ${resume.id || resume.resume_id}`
          const id = resume.resume_id || resume.id || resume._id
          const parsedAt = resume.parsed_at || resume.uploaded_at

          return (
            <article className="card" key={id || title}>
              <p className="card-title">{title}</p>
              {parsedAt && <p className="muted">Uploaded {new Date(parsedAt).toLocaleString()}</p>}
            </article>
          )
        })}
      </div>
    </section>
  )
}
