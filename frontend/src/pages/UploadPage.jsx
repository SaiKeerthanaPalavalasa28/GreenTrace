import { useEffect, useRef, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Button, Card, ErrorBox, Field, inputClass } from '../components/ui'
import { StatusBadge, TERMINAL } from '../components/status'

const MAX_MB = 20
const POLL_MS = 2000

export default function UploadPage() {
  const [facilities, setFacilities] = useState(null)
  const [facilityId, setFacilityId] = useState('')
  const [files, setFiles] = useState([])
  const [rejected, setRejected] = useState([])
  const [rows, setRows] = useState([]) // one per uploaded file: {filename, outcome, bill_id, reason, status, failure_reason}
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const pollRef = useRef(null)

  useEffect(() => {
    api('/facilities').then((f) => {
      setFacilities(f)
      if (f.length === 1) setFacilityId(f[0].id)
    }).catch(setError)
    return () => clearTimeout(pollRef.current)
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'application/pdf': ['.pdf'] },
    maxSize: MAX_MB * 1024 * 1024,
    multiple: true,
    onDrop: (accepted, rejections) => {
      setFiles((prev) => {
        const names = new Set(prev.map((f) => f.name + f.size))
        return [...prev, ...accepted.filter((f) => !names.has(f.name + f.size))]
      })
      setRejected(rejections.map((r) => ({
        name: r.file.name,
        reason: r.errors[0]?.code === 'file-too-large' ? `Larger than ${MAX_MB} MB` : 'Not a PDF',
      })))
    },
  })

  const poll = async (current) => {
    const pending = current.filter((r) => r.bill_id && r.outcome === 'queued' && !TERMINAL.has(r.status))
    if (pending.length === 0) return
    try {
      const statuses = await api('/bills/status', { params: { ids: pending.map((r) => r.bill_id).join(',') } })
      const byId = Object.fromEntries(statuses.map((s) => [s.id, s]))
      const next = current.map((r) => (byId[r.bill_id] && r.outcome === 'queued'
        ? { ...r, status: byId[r.bill_id].status, failure_reason: byId[r.bill_id].failure_reason }
        : r))
      setRows(next)
      pollRef.current = setTimeout(() => poll(next), POLL_MS)
    } catch (err) {
      setError(err)
    }
  }

  const upload = async () => {
    setBusy(true)
    setError(null)
    clearTimeout(pollRef.current)
    try {
      const form = new FormData()
      form.append('facility_id', facilityId)
      files.forEach((f) => form.append('files', f))
      const { results } = await api('/bills/upload', { method: 'POST', body: form })
      const next = results.map((r) => ({ ...r, status: r.outcome === 'queued' ? 'uploaded' : r.outcome }))
      setRows(next)
      setFiles([])
      setRejected([])
      poll(next)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  if (facilities && facilities.length === 0) {
    return (
      <Card title="Upload bills">
        <p className="text-sm text-slate-600">
          Bills are uploaded against a facility. <Link className="text-emerald-700 hover:underline" to="/facilities">Add a facility</Link> first.
        </p>
      </Card>
    )
  }

  const counts = rows.reduce((acc, r) => ({ ...acc, [r.status]: (acc[r.status] || 0) + 1 }), {})
  const inProgress = rows.some((r) => r.outcome === 'queued' && !TERMINAL.has(r.status))

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Upload bills</h1>
      <ErrorBox error={error} />

      <Card>
        <div className="space-y-4">
          <Field label="Facility" hint="All files in this upload belong to this facility. Bills whose account number belongs to another facility are flagged for review.">
            <select className={inputClass + ' sm:max-w-sm'} value={facilityId} onChange={(e) => setFacilityId(e.target.value)}>
              <option value="">Select a facility…</option>
              {(facilities || []).map((f) => <option key={f.id} value={f.id}>{f.name} ({f.region})</option>)}
            </select>
          </Field>

          <div
            {...getRootProps()}
            className={`cursor-pointer rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors ${isDragActive ? 'border-emerald-600 bg-emerald-50' : 'border-slate-300 hover:border-slate-400'}`}
          >
            <input {...getInputProps()} />
            <p className="text-sm font-medium text-slate-700">Drop electricity or gas bill PDFs here, or click to choose</p>
            <p className="mt-1 text-xs text-slate-500">PDF only, up to {MAX_MB} MB each. Scanned bills are OCR'd.</p>
          </div>

          {rejected.length > 0 && (
            <ul className="text-sm text-red-700">
              {rejected.map((r) => <li key={r.name}>{r.name}: {r.reason}</li>)}
            </ul>
          )}

          {files.length > 0 && (
            <div className="space-y-3">
              <ul className="divide-y divide-slate-100 rounded-md border border-slate-200 text-sm">
                {files.map((f) => (
                  <li key={f.name + f.size} className="flex items-center justify-between gap-2 px-3 py-1.5">
                    <span className="truncate">{f.name}</span>
                    <span className="flex shrink-0 items-center gap-3 text-slate-500">
                      {(f.size / 1024).toFixed(0)} KB
                      <button className="text-slate-400 hover:text-red-600" onClick={() => setFiles(files.filter((x) => x !== f))} aria-label={`Remove ${f.name}`}>✕</button>
                    </span>
                  </li>
                ))}
              </ul>
              <Button onClick={upload} disabled={busy || !facilityId}>
                {busy ? 'Uploading…' : `Upload ${files.length} file${files.length === 1 ? '' : 's'}`}
              </Button>
              {!facilityId && <span className="ml-3 text-sm text-slate-500">Select a facility first</span>}
            </div>
          )}
        </div>
      </Card>

      {rows.length > 0 && (
        <Card
          title={inProgress ? 'Processing…' : 'Upload results'}
          actions={
            <div className="flex flex-wrap gap-3 text-xs text-slate-600">
              {Object.entries(counts).map(([s, n]) => <span key={s} className="flex items-center gap-1"><StatusBadge status={s} /> {n}</span>)}
            </div>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-slate-500">
                <tr><th className="py-2 pr-4 font-medium">File</th><th className="py-2 pr-4 font-medium">Status</th><th className="py-2 font-medium">Details</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((r, i) => (
                  <tr key={r.bill_id ? r.bill_id + i : r.filename + i}>
                    <td className="py-2 pr-4">
                      {r.bill_id && r.outcome === 'queued'
                        ? <Link className="text-emerald-700 hover:underline" to={`/bills/${r.bill_id}`}>{r.filename}</Link>
                        : r.filename}
                    </td>
                    <td className="py-2 pr-4"><StatusBadge status={r.status} /></td>
                    <td className="py-2 text-slate-600">{r.failure_reason || r.reason || ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
