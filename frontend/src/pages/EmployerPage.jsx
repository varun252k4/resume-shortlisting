import { useEffect, useMemo, useState } from 'react'
import { apiRequest } from '../services/api'

function normalizeItems(data) {
  if (Array.isArray(data)) {
    return data
  }

  if (!data || !Array.isArray(data.resumes)) {
    return []
  }

  return data.resumes
}

function normalizeJobs(data) {
  if (Array.isArray(data)) {
    return data
  }

  if (!data || !Array.isArray(data.jobs)) {
    return []
  }

  return data.jobs
}

function normalizeRankings(payload) {
  if (!payload) {
    return []
  }

  if (Array.isArray(payload)) {
    return payload
  }

  if (Array.isArray(payload.results)) {
    return payload.results
  }

  return []
}

export default function EmployerPage() {
  const [jobs, setJobs] = useState([])
  const [resumes, setResumes] = useState([])

  const [jobForm, setJobForm] = useState({ title: '', jdText: '' })
  const [selectedJobId, setSelectedJobId] = useState('')
  const [selectedResumeIds, setSelectedResumeIds] = useState([])
  const [rankings, setRankings] = useState([])
  const [rankErrors, setRankErrors] = useState([])

  const [jobError, setJobError] = useState('')
  const [jobStatus, setJobStatus] = useState('')
  const [rankStatus, setRankStatus] = useState('')
  const [loadingJobs, setLoadingJobs] = useState(false)
  const [loadingResumes, setLoadingResumes] = useState(false)
  const [loadingRank, setLoadingRank] = useState(false)

  const selectedJob = useMemo(() => jobs.find((job) => job.id === selectedJobId) || null, [jobs, selectedJobId])

  const loadJobs = async () => {
    setLoadingJobs(true)
    setJobError('')
    try {
      const response = await apiRequest('/employer/jobs', 'GET')
      const list = normalizeJobs(response)
      setJobs(list)
      setSelectedJobId((current) => current || list[0]?.id || '')
    } catch (err) {
      setJobError(err.message || 'Failed to load jobs')
      setJobs([])
    } finally {
      setLoadingJobs(false)
    }
  }

  const loadResumes = async () => {
    setLoadingResumes(true)
    try {
      const response = await apiRequest('/candidate/resumes', 'GET')
      setResumes(normalizeItems(response))
    } catch (err) {
      setJobError(err.message || 'Failed to load resumes')
    } finally {
      setLoadingResumes(false)
    }
  }

  const loadRankings = async () => {
    if (!selectedJobId) {
      setRankErrors(['Choose a job first.'])
      return
    }

    setLoadingRank(true)
    setRankErrors([])
    setRankStatus('')
    try {
      const response = await apiRequest(`/employer/jobs/${selectedJobId}/rankings`, 'GET')
      if (!response.success && response.results?.length === 0) {
        setRankErrors(['No ranking available for this job yet.'])
      }
      setRankings(normalizeRankings(response))
      setJobStatus(response.job_id ? `Loaded saved ranking for ${response.job_id}` : '')
    } catch (err) {
      setRankErrors([err.message || 'Could not load rankings'])
      setRankings([])
    } finally {
      setLoadingRank(false)
    }
  }

  const createJob = async (event) => {
    event.preventDefault()
    setJobError('')
    setJobStatus('')

    const title = jobForm.title.trim()
    const jdText = jobForm.jdText.trim()
    if (!title || !jdText) {
      setJobError('Job title and JD text are required.')
      return
    }

    try {
      const response = await apiRequest('/employer/jobs', 'POST', {
        title,
        jd_text: jdText,
      })
      setJobStatus(response?.message || 'Job posted successfully.')
      setJobForm({ title: '', jdText: '' })
      await loadJobs()
      setSelectedJobId(response?.job?.id || '')
    } catch (err) {
      setJobError(err.message || 'Could not create job')
    }
  }

  const toggleResume = (resumeId) => {
    setSelectedResumeIds((previous) =>
      previous.includes(resumeId)
        ? previous.filter((value) => value !== resumeId)
        : [...previous, resumeId],
    )
  }

  const rankCandidates = async () => {
    if (!selectedJobId) {
      setJobError('Choose a job first.')
      return
    }

    setLoadingRank(true)
    setJobError('')
    setRankErrors([])
    setRankStatus('')
    try {
      const response = await apiRequest(`/employer/jobs/${selectedJobId}/rank`, 'POST', {
        resume_ids: selectedResumeIds,
      })

      const ranked = normalizeRankings(response)
      setRankings(ranked)
      setRankErrors(response.errors || [])
      setRankStatus(response.success ? `Generated ${ranked.length} ranking result(s)` : 'No ranking available')
    } catch (err) {
      setRankErrors([err.message || 'Unable to run ranking'])
    } finally {
      setLoadingRank(false)
    }
  }

  useEffect(() => {
    loadJobs()
    loadResumes()
  }, [])

  useEffect(() => {
    if (selectedJobId) {
      loadRankings()
    }
  }, [selectedJobId])

  return (
    <section className="panel fade-in">
      <header className="stack-head">
        <div>
          <p className="label">Employer dashboard</p>
          <h1>Post JDs and rank candidates</h1>
        </div>
      </header>

      <div className="split-grid">
        <form className="card" onSubmit={createJob}>
          <h2>Create a job</h2>
          <input
            className="input"
            placeholder="Job title"
            value={jobForm.title}
            onChange={(event) => setJobForm((previous) => ({ ...previous, title: event.target.value }))}
          />
          <textarea
            className="input textarea"
            rows="6"
            placeholder="Paste JD text"
            value={jobForm.jdText}
            onChange={(event) => setJobForm((previous) => ({ ...previous, jdText: event.target.value }))}
          />
          <button className="action-btn" type="submit">
            Create Job
          </button>
          {jobStatus && <p className="success-text">{jobStatus}</p>}
          {jobError && <p className="error-text">{jobError}</p>}
        </form>

        <div className="card">
          <h2>Active jobs</h2>
          {loadingJobs ? (
            <p className="muted">Loading jobs...</p>
          ) : jobs.length === 0 ? (
            <p className="muted">No jobs posted yet.</p>
          ) : (
            <ul className="job-list">
              {jobs.map((job) => (
                <li
                  key={job.id}
                  className={`job-item ${selectedJobId === job.id ? 'job-item--active' : ''}`}
                  onClick={() => setSelectedJobId(job.id)}
                >
                  <strong>{job.title}</strong>
                  <span>{job.id}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="split-grid card-row-gap">
        <section className="card">
          <div className="stack-head">
            <h2>Candidate resumes</h2>
            <button className="ghost-btn" onClick={() => loadResumes()}>
              {loadingResumes ? 'Loading...' : 'Refresh'}
            </button>
          </div>
          {resumes.length === 0 ? (
            <p className="muted">No resumes found. Ask candidates to upload resumes.</p>
          ) : (
            <div className="resume-checklist">
              {resumes.map((resume) => {
                const id = resume.id || resume.resume_id
                const name = resume.file_name || 'resume'
                return (
                  <label key={id} className="resume-row">
                    <input
                      type="checkbox"
                      checked={selectedResumeIds.includes(id)}
                      onChange={() => toggleResume(id)}
                    />
                    <span>{name}</span>
                    <em className="muted">{resume.candidate_name || resume.user_id}</em>
                  </label>
                )
              })}
            </div>
          )}

          <div className="stack-head">
            <h2>Run ranking</h2>
            <button className="action-btn" onClick={rankCandidates} disabled={loadingRank}>
              {loadingRank ? 'Scoring...' : 'Run ranking against selected'}
            </button>
          </div>
          {rankStatus && <p className="success-text">{rankStatus}</p>}
          {rankErrors.length > 0 && (
            <ul className="error-list">
              {rankErrors.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          )}
        </section>

        <section className="card">
          <div className="stack-head">
            <h2>Ranked candidates</h2>
            <button className="ghost-btn" onClick={loadRankings}>
              {loadingRank ? 'Loading...' : 'Refresh latest'}
            </button>
          </div>

          <div className="score-grid">
            {rankings.map((item, index) => (
              <article key={`${item.resume_id || index}`} className="rank-card">
                <p className="rank-label">
                  #{item.rank || index + 1} · {item.candidate_name || item.resume_name || 'Candidate'}
                </p>
                <p>
                  Total score:{' '}
                  {Number.isFinite(Number(item.total_score)) ? Number(item.total_score).toFixed(2) : '-'}
                </p>
                <p>Flag: {item.flag}</p>
                <p>Shortlisted: {item.is_shortlisted ? 'Yes' : 'No'}</p>
                <p className="summary">{item.summary || 'No summary available'}</p>
              </article>
            ))}
          </div>
          {rankings.length === 0 && !rankErrors.length && !loadingRank ? (
            <p className="muted">Run ranking to see AI scores.</p>
          ) : null}

          {selectedJob && (
            <p className="muted">Current JD: {selectedJob.jd_text ? selectedJob.jd_text.slice(0, 120) + '...' : selectedJob.title}</p>
          )}
        </section>
      </div>
    </section>
  )
}
