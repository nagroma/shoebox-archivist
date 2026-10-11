import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type IngestState } from '../api'
import { useApp } from '../state'

/** Top-bar button + dialog: upload photos or rescan the library folder, with live progress. */
export function AddPhotosButton() {
  const { refresh, stats, toast } = useApp()
  const [open, setOpen] = useState(false)
  const [job, setJob] = useState<IngestState>({ running: false })
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const wasRunning = useRef(false)

  const poll = useCallback(async () => {
    const s = await api.ingestStatus()
    setJob(s)
    if (wasRunning.current && !s.running) {
      if (s.error) toast(`Import failed: ${s.error}`, 'error')
      else if (s.result) toast(`Imported ${s.result.added} new photo(s), ${s.result.faces} faces found`)
      refresh()
      window.dispatchEvent(new Event('library-changed'))
    }
    wasRunning.current = s.running
  }, [refresh, toast])

  // Poll fast while a job runs, and pick up jobs started elsewhere (e.g. after a reload).
  useEffect(() => {
    poll()
    const t = setInterval(poll, job.running ? 1000 : 10000)
    return () => clearInterval(t)
  }, [poll, job.running])

  async function upload(files: File[]) {
    if (!files.length) return
    setUploading(true)
    try {
      const r = await api.upload(files)
      if (r.skipped.length) toast(`Skipped ${r.skipped.length} non-image file(s)`, 'error')
      if (r.saved) toast(`Copied ${r.saved} file(s) to ${r.folder}`)
      wasRunning.current = true
      await poll()
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setUploading(false)
    }
  }

  async function rescan() {
    try {
      setJob(await api.ingest())
      wasRunning.current = true
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }

  const busy = job.running || uploading
  const pct = job.total ? Math.round((100 * (job.done ?? 0)) / job.total) : null

  return (
    <>
      <button className={busy ? 'busy' : 'primary'} onClick={() => setOpen(true)}>
        {busy ? `Importing… ${pct !== null ? pct + '%' : ''}` : '+ Add photos'}
      </button>
      {open && (
        <div className="modal-back" onMouseDown={e => { if (e.target === e.currentTarget) setOpen(false) }}>
          <div className="modal">
            <div className="card-head">
              <h2>Add photos</h2>
              <button className="ghost" onClick={() => setOpen(false)}>✕</button>
            </div>

            <div
              className={`drop ${dragging ? 'over' : ''} ${busy ? 'disabled' : ''}`}
              onDragOver={e => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={e => { e.preventDefault(); setDragging(false); if (!busy) upload([...e.dataTransfer.files]) }}
              onClick={() => !busy && fileRef.current?.click()}
            >
              <div className="drop-big">Drop photos here</div>
              <div className="muted small">or click to choose files · JPG, PNG, TIFF, BMP, WebP</div>
              <input ref={fileRef} type="file" multiple accept="image/*,.tif,.tiff" hidden
                onChange={e => { upload([...(e.target.files ?? [])]); e.target.value = '' }} />
            </div>
            <p className="muted small">
              Uploaded files are copied into <code>Imported/&lt;today&gt;/</code> inside the library folder.
              Name backs like <code>0012_b.jpg</code> next to <code>0012.jpg</code> to pair them.
            </p>

            <div className="action-bar">
              <button onClick={rescan} disabled={busy}>Scan library folder for new files</button>
              <span className="muted small" title={stats?.library_root ?? ''}>
                For photos you copied into <code>{stats?.library_root ?? 'the library folder'}</code> yourself.
              </span>
            </div>

            {(job.running || job.result || job.error) && (
              <div className="job">
                {job.running && (
                  <>
                    <div className="row"><b>{job.stage}</b>
                      <span className="muted small">{job.total ? `${job.done} / ${job.total}` : ''}</span></div>
                    <div className="progress"><div style={{ width: `${pct ?? 5}%` }} className={pct === null ? 'indeterminate' : ''} /></div>
                    <p className="muted small">Face detection takes about 1 second per photo. You can close this and keep working.</p>
                  </>
                )}
                {!job.running && job.error && <p className="hint error">Import failed: {job.error}</p>}
                {!job.running && job.result && (
                  <p>
                    Last import: <b>{job.result.added}</b> new photo(s)
                    {job.result.duplicates > 0 && <>, {job.result.duplicates} duplicate(s) skipped</>},
                    {' '}{job.result.dated} dated from camera info, <b>{job.result.faces}</b> faces found,
                    {' '}{job.result.suggestions} name suggestions.
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
