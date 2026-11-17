import { Link } from 'react-router-dom'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, faceRescanSummary, scanProgressText, type Facet, type FolderEntry, type FolderFlag, type FolderListing, type FolderTree, type IngestState, type LibraryInfo, type ProposedFacet, type ScanState } from '../api'
import { ScanFamilySettings } from '../components/VariationSettings'
import { useApp } from '../state'
import { localPathFromUrl } from '../folderPath'

const KIND_HELP: Record<string, string> = {
  person: 'people (linked to faces)', event: 'events', place: 'places', subject: 'subjects',
  attribute: 'workflow / format tags', other: 'anything else',
}

/** Server-side folder browser (the server runs on this computer). */
function FolderPicker({ onPick }: { onPick: (folder: string) => void }) {
  const [listing, setListing] = useState<FolderListing | null>(null)
  const [typed, setTyped] = useState('')
  const [error, setError] = useState('')

  const [loading, setLoading] = useState(false)
  const request = useRef(0)
  const isMac = /Mac/i.test(navigator.platform)

  const go = useCallback(async (value: string) => {
    const path = localPathFromUrl(value) ?? value
    const id = ++request.current
    setTyped(path)
    setLoading(true)
    setError('')
    try {
      const next = await api.listFolder(path)
      if (id !== request.current) return
      setListing(next)
      setTyped('')
    } catch (e) {
      if (id === request.current) setError((e as Error).message)
    } finally {
      if (id === request.current) setLoading(false)
    }
  }, [])

  useEffect(() => { void go('') }, [go])

  const icloud = listing?.icloud
  const canUse = !!listing?.path && !typed && !loading && !error
  return (
    <div className="folder-picker">
      <div className="folder-path-field">
        <label htmlFor="library-folder-path">Drag your photo folder into this field</label>
        <form className="row wrap" onSubmit={event => { event.preventDefault(); void go(typed) }}>
          <input autoComplete="off" id="library-folder-path" className="grow" value={typed} placeholder="Or paste the full folder path"
            aria-describedby="library-folder-help" onChange={event => {
              request.current++
              setLoading(false)
              setError('')
              setTyped(event.target.value)
            }} />
          <button type="submit" disabled={loading}>Go</button>
          <button type="button" className="primary" disabled={!canUse} onClick={() => listing && onPick(listing.path)}>
            Use this folder
          </button>
        </form>
        <p className="muted small" id="library-folder-help">{isMac
          ? 'Or copy the folder path in Finder with Option–Command–C and paste it here. Click Go to browse the folder.'
          : 'Or paste the full folder path here. Click Go to browse the folder.'}</p>
      </div>
      {icloud && <button type="button" className="ghost" onClick={() => go(icloud)}>Browse iCloud Drive</button>}
      {error && <p className="hint error" role="alert">{error}</p>}
      {listing && (
        <>
          <p className="muted small">
            {listing.path || 'Drives'}
            {listing.path && <> · {listing.images} photo(s) directly here</>}
            {listing.has_library && <> · <b>already a Shoebox Archivist library</b></>}
          </p>
          <ul className="folder-list">
            {listing.parent !== null && listing.path && (
              <li><button className="ghost" onClick={() => go(listing.parent ?? '')}>⬑ Up</button></li>
            )}
            {listing.dirs.map(d => (
              <li key={d.path}><button className="ghost" onClick={() => go(d.path)}>📁 {d.name}</button></li>
            ))}
            {listing.dirs.length === 0 && <li className="muted small">No sub-folders</li>}
          </ul>
        </>
      )}
    </div>
  )
}

/** Choose a folder, read its existing keywords, review the starting facets, create. */
function NewLibrary({ info }: { info: LibraryInfo }) {
  const [folder, setFolder] = useState<string | null>(null)
  const [scan, setScan] = useState<ScanState | null>(null)
  const [staged, setStaged] = useState(true)
  const [preset, setPreset] = useState('auto')
  const [facets, setFacets] = useState<ProposedFacet[] | null>(null)
  const [useKeywords, setUseKeywords] = useState(true)
  const [curator, setCurator] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const timer = useRef<number | undefined>(undefined)

  const poll = useCallback(async (p: string) => {
    const s = await api.inspectStatus(p)
    setScan(s)
    if (s.running) { timer.current = window.setTimeout(() => poll(p), 600); return }
    if (s.preset) setPreset(s.preset)
    if (s.facets) setFacets(s.facets)
  }, [])
  useEffect(() => () => window.clearTimeout(timer.current), [])

  async function choose(path: string) {
    setError(''); setScan(null); setFacets(null); setFolder(path); setPreset('auto')
    try {
      const s = await api.inspectFolder(path, staged, 'auto')
      setScan(s)
      if (s.preset) setPreset(s.preset)
      if (s.facets) setFacets(s.facets)
      else if (!s.existing) void poll('auto').catch(e => setError((e as Error).message))
    } catch (e) { setError((e as Error).message); setFolder(null) }
  }

  async function changePreset(p: string) {
    setPreset(p)
    if (!folder) return
    try {
      if (staged) {
        const next = await api.inspectFolder(folder, true, p)
        setScan(next); setFacets(next.facets ?? null)
      } else if (scan?.result) await poll(p)
    } catch (e) { setError((e as Error).message) }
  }

  const setFacet = (i: number, patch: Partial<Facet>) =>
    setFacets(fs => fs && fs.map((f, j) => (j === i ? { ...f, ...patch } : f)))

  async function create() {
    if (!folder || !facets) return
    setBusy(true); setError('')
    try {
      await api.createLibrary(folder, facets.map(f => ({ name: f.name, kind: f.kind })), useKeywords, curator, staged)
      window.location.assign('/library')
    } catch (e) { setError((e as Error).message); setBusy(false) }
  }

  async function open() {
    if (!folder) return
    setBusy(true)
    try { await api.openLibrary(folder); window.location.assign('/library') }
    catch (e) { setError((e as Error).message); setBusy(false) }
  }

  const r = scan?.result
  return (
    <section className="card">
      <h2>Open or create a library</h2>
      <p className="muted small">
        A library is a folder of photos. The app keeps its own data in a <code>.shoebox</code> folder inside it;
        your photos are only changed when you name a face or edit a keyword, date or caption.
      </p>

      {!folder && <>
        <label className="row">
          <input type="checkbox" checked={staged} onChange={e => setStaged(e.target.checked)} />
          Choose which folders to scan after creating the library
        </label>
        <FolderPicker onPick={choose} />
      </>}
      {error && <p className="hint error">{error}</p>}

      {folder && (
        <>
          <div className="row">
            <b className="grow" style={{ wordBreak: 'break-all' }}>{folder}</b>
            <button onClick={() => { window.clearTimeout(timer.current); setFolder(null); setScan(null); setFacets(null) }} disabled={busy || !scan || scan.running}>Change folder</button>
          </div>

          {scan?.existing && (
            <div className="job">
              <p>This folder already has a library.</p>
              <button className="primary" onClick={open} disabled={busy}>Open library</button>
            </div>
          )}

          {scan && !scan.existing && scan.running && (
            <div className="job">
              <div className="row"><b>Reading keywords already in the photos…</b>
                <span className="muted small">{scan.total ? `${scan.done} / ${scan.total}` : ''}</span></div>
              <div className="progress"><div className={scan.total ? '' : 'indeterminate'}
                style={{ width: scan.total ? `${Math.round(100 * (scan.done ?? 0) / scan.total)}%` : '5%' }} /></div>
            </div>
          )}

          {scan?.error && <p className="hint error">{scan.error}</p>}

          {(r || scan?.staged) && facets && (
            <div className="job">
              {r ? <p>
                <b>{r.images}</b> photo(s) found; <b>{r.with_keywords}</b> already have keywords
                ({r.n_paths} hierarchical, {r.n_flat} flat).
              </p> : <p>{scan?.keyword_file
                ? 'Keywords.txt at the library root will supply the starting vocabulary.'
                : 'The vocabulary will grow from photo metadata in folders you choose to learn from.'}</p>}
              {scan?.staged && !scan.keyword_file && <p className="muted small">If your photos already have a custom top-level group for people, add it below and set its kind to person.</p>}

              <div className="field-block">
                <label className="muted small" htmlFor="curator">Who is curating this library? (your full name)</label>
                <input autoComplete="off" id="curator" value={curator} placeholder="e.g. Jane Morgan" style={{ width: '100%', maxWidth: 360 }}
                  onChange={e => setCurator(e.target.value)} />
                <p className="muted small">
                  The family is organised around you: generations, sides of the family and relationships
                  (parent, cousin, ...) are measured from this person. Optional; you can set it later.
                </p>
              </div>

              <div className="field-block">
                <label className="muted small">Starting point</label>
                <div className="row wrap">
                  {Object.entries(info.presets).map(([key, p]) => (
                    <label key={key} className="radio" title={p.help}>
                      <input type="radio" name="preset" checked={preset === key} onChange={() => changePreset(key)} />
                      {p.label}
                    </label>
                  ))}
                </div>
                <p className="muted small">{info.presets[preset]?.help}</p>
              </div>

              <table className="facets">
                <thead><tr><th>Top-level keyword group (facet)</th><th>Kind</th><th>Examples</th><th>{staged ? "In Keywords.txt" : "In photos"}</th><th /></tr></thead>
                <tbody>
                  {facets.map((f, i) => (
                    <tr key={i}>
                      <td><input autoComplete="off" value={f.name} onChange={e => setFacet(i, { name: e.target.value })} /></td>
                      <td>
                        <select value={f.kind} onChange={e => setFacet(i, { kind: e.target.value })}>
                          {info.kinds.map(k => <option key={k} value={k}>{k} – {KIND_HELP[k] ?? ''}</option>)}
                        </select>
                      </td>
                      <td className="muted small">
                        {f.samples?.join(', ')}
                        {f.looks_like_people && f.kind !== 'person' && (
                          <div>Looks like names of people.{' '}
                            <button className="ghost" onClick={() => setFacet(i, { kind: 'person' })}>Use as people</button>
                          </div>
                        )}
                      </td>
                      <td className="muted">{f.found || ''}{f.from_files && ' (from files)'}</td>
                      <td><button className="ghost" title="Remove"
                        onClick={() => setFacets(facets.filter((_, j) => j !== i))}>×</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="ghost" onClick={() => setFacets([...facets, { name: '', kind: 'other', found: 0, from_files: false }])}>
                + Add facet
              </button>

              {r && r.n_paths > 0 && (
                <>
                  <label className="row" style={{ marginTop: 8 }}>
                    <input type="checkbox" checked={useKeywords} onChange={e => setUseKeywords(e.target.checked)} />
                    Start the vocabulary with the {r.n_paths} keyword(s) found in the photos
                  </label>
                  <details>
                    <summary className="muted small">Show keywords found</summary>
                    <ul className="kw-found">
                      {Object.entries(r.paths).map(([k, n]) => <li key={k}><code>{k}</code> <span className="muted">×{n}</span></li>)}
                    </ul>
                  </details>
                </>
              )}
              {r && r.n_flat > 0 && (
                <details>
                  <summary className="muted small">{r.n_flat} flat keyword(s) found (no group; filed under "Other Keywords" until you move them)</summary>
                  <ul className="kw-found">
                    {Object.entries(r.flat).map(([k, n]) => <li key={k}><code>{k}</code> <span className="muted">×{n}</span></li>)}
                  </ul>
                </details>
              )}

              <div className="action-bar">
                <button className="primary" onClick={create} disabled={busy || facets.some(f => !f.name.trim())}>
                  {busy ? 'Creating…' : staged ? 'Create library' : 'Create library and scan photos'}
                </button>
                <span className="muted small">{staged ? 'Choose folders to scan on the Library page.' : 'Face detection starts right away.'}</span>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  )
}

/** Facets, Keywords.txt export and reset for the open library. */
function CurrentLibrary({ info, reload }: { info: LibraryInfo; reload: () => void }) {
  const [curator, setCurator] = useState(info.curator?.name ?? '')
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  return (
      <section className="card">
        <h2>Current library</h2>
        <dl>
          <dt className="muted">Photo folder</dt><dd>{info.root}</dd>
          <dt className="muted">App data</dt><dd>{info.data_dir}</dd>
        </dl>
        <div className="field-block">
          <label className="muted small" htmlFor="curator-now">Curator (the person this family tree is measured from)</label>
          <div className="row">
            <input autoComplete="off" id="curator-now" value={curator} placeholder="Full name" onChange={e => setCurator(e.target.value)} />
            <button disabled={curator.trim() === (info.curator?.name ?? '')}
              onClick={async () => {
                try { await api.setCurator(curator); setMsg('Curator saved'); reload() }
                catch (e) { setError((e as Error).message) }
              }}>Save</button>
          </div>
        </div>
        <div className="row">
          <button onClick={async () => { try { await api.closeLibrary(); window.location.assign('/library') } catch (e) { setError((e as Error).message) } }}>Close library</button>
        </div>
        {msg && <p className="hint" role="status">{msg}</p>}
        {error && <p className="hint error" role="alert">{error}</p>}
      </section>

  )
}

function ResetLibrary() {
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  async function reset() {
    setError('')
    try { await api.resetLibrary(confirm); window.location.assign('/library') }
    catch (e) { setError((e as Error).message) }
  }

  return (
        <section className="card danger-zone">
          <h2>Reset this library</h2>
          <p className="muted small">
            Deletes the app's data for this folder (database, face names, thumbnails, facets) so it can be
            set up again like a new folder. Your photos are not deleted. Keywords, captions and dates the app
            already wrote into the photo files stay there and will be read as existing keywords the next time.
            (<code>pm strip</code> removes them from the files first, if you want a clean start.)
          </p>
          <div className="row">
            <input autoComplete="off" value={confirm} placeholder="Type reset to confirm" onChange={e => setConfirm(e.target.value)} />
            <button className="danger" disabled={confirm !== 'reset'} onClick={reset}>Reset library</button>
          </div>
          {error && <p className="hint error" role="alert">{error}</p>}
        </section>
  )
}

const folderFlags: { key: FolderFlag; label: string }[] = [
  { key: 'learn', label: 'Learn from this folder' },
  { key: 'identify', label: 'Identify faces in this folder' },
]

function parentPath(path: string) {
  return path.substring(0, path.lastIndexOf('/'))
}

function FolderTable({ entries, busy, choose, rescan }: {
  entries: FolderEntry[]
  busy: boolean
  choose: (path: string, flag: FolderFlag, enabled: boolean) => void
  rescan: (path: string) => void
}) {
  const [expanded, setExpanded] = useState(() => new Set(['']))
  const byPath = new Map(entries.map(entry => [entry.path, entry]))
  const children = new Set<string>()
  const mixed = new Map<string, Set<FolderFlag>>()
  const rescanPaths = new Set(entries.filter(entry => entry.identify && entry.fronts > 0).map(entry => entry.path))
  for (const { path } of [...entries].reverse()) {
    if (!path) continue
    const parent = parentPath(path)
    children.add(parent)
    if (rescanPaths.has(path)) rescanPaths.add(parent)
    const entry = byPath.get(path)!
    const parentEntry = byPath.get(parent)!
    for (const { key } of folderFlags) {
      if (entry[key] === parentEntry[key] && !mixed.get(path)?.has(key)) continue
      if (!mixed.has(parent)) mixed.set(parent, new Set())
      mixed.get(parent)!.add(key)
    }
  }
  const visible = new Set<string>()
  return (
    <div className="table-scroll">
      <table className="facets folder-scope">
        <thead><tr><th>Folder</th>{folderFlags.map(({ key, label }) => <th key={key}>{label}</th>)}<th>Status</th></tr></thead>
        <tbody>
          {entries.map(entry => {
            const { path, name, indexed, fronts, scanned } = entry
            if (path && (!visible.has(parentPath(path)) || !expanded.has(parentPath(path)))) return null
            visible.add(path)
            const depth = path ? path.split('/').length : 0
            return <tr key={path}>
              <th scope="row">
                <div className="folder-name" style={{ '--folder-depth': depth } as React.CSSProperties}>
                  {children.has(path) ? <button className="ghost folder-toggle" aria-expanded={expanded.has(path)}
                    aria-label={`${expanded.has(path) ? 'Collapse' : 'Expand'} ${name}`}
                    onClick={() => setExpanded(current => {
                      const next = new Set(current)
                      if (next.has(path)) next.delete(path); else next.add(path)
                      return next
                    })} /> : <span className="folder-toggle" />}
                  <span className="folder-name-label">{name}</span>
                </div>
              </th>
              {folderFlags.map(({ key, label }) => {
                const partial = mixed.get(path)?.has(key) ?? false
                return <td key={key}>
                  <input type="checkbox" aria-label={`${label} — ${path || name}`}
                    ref={node => { if (node) node.indeterminate = partial }}
                    checked={entry[key]} disabled={busy}
                    onChange={e => choose(path, key, partial || e.target.checked)} />
                </td>
              })}
              <td className="muted">
                <div className="folder-status">
                  <span className="folder-status-text">{indexed ? `${indexed} indexed · ${scanned}/${fronts} fronts scanned` : 'Not indexed'}</span>
                  {rescanPaths.has(path) && <button className="small folder-rescan" disabled={busy}
                    aria-label={`Re-scan for faces in ${path || name}`} onClick={() => rescan(path)}>Re-scan for faces</button>}
                </div>
              </td>
            </tr>
          })}
        </tbody>
      </table>
    </div>
  )
}

function FolderScope({ reload }: { reload: () => void }) {
  const { refresh } = useApp()
  const [tree, setTree] = useState<FolderTree | null>(null)
  const [job, setJob] = useState<IngestState>({ running: false })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const wasRunning = useRef(false)
  const refreshTree = useCallback(() => {
    api.folders().then(setTree).catch(e => setError((e as Error).message))
  }, [])
  useEffect(() => {
    refreshTree()
    window.addEventListener('library-changed', refreshTree)
    return () => window.removeEventListener('library-changed', refreshTree)
  }, [refreshTree])
  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const next = await api.ingestStatus()
        if (cancelled) return
        if (wasRunning.current && !next.running) {
          refresh()
          window.dispatchEvent(new Event('library-changed'))
        }
        wasRunning.current = next.running
        setJob(next)
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      }
    }
    void poll()
    const timer = window.setInterval(poll, 1000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [refresh])

  async function choose(path: string, flag: FolderFlag, enabled: boolean) {
    setSaving(true); setError('')
    try {
      setTree(await api.chooseFolder(path, flag, enabled))
      reload()
      refresh()
    } catch (e) { setError((e as Error).message) }
    finally { setSaving(false) }
  }

  async function scan(path?: string) {
    setSaving(true); setError('')
    try {
      setJob(path === undefined ? await api.ingest() : await api.rescanFolderFaces(path))
      wasRunning.current = true
    } catch (e) { setError((e as Error).message) }
    finally { setSaving(false) }
  }

  const busy = saving || job.running
  return <section className="card">
    <h2>Photo folders</h2>
    <p><b>Learn</b> uses confirmed faces for future suggestions. <b>Identify</b> finds faces and adds them to the <Link to="/faces">Faces</Link> page.</p>
    <p className="muted small">Checking a folder sets that choice for its subfolders. You can then change individual subfolders. Counts show files directly in each folder.</p>
    <p className="muted small">Use <b>Re-scan for faces</b> to check indexed photos again in a folder and its subfolders where <b>Identify</b> is on. Existing face labels and crops are kept.</p>
    {tree && <>
      <p className="muted small">{tree.keyword_file
        ? 'Starting vocabulary comes from Keywords.txt at the library root.'
        : tree.scoped ? 'Keyword choices include metadata from folders marked Learn.'
          : 'Keyword choices include metadata from indexed photos.'}</p>
      <FolderTable entries={tree.folders} busy={busy} choose={choose} rescan={scan} />
      <div className="action-bar">
        <button className="primary" disabled={busy || !tree.folders.some(f => f.learn || f.identify)}
          onClick={() => scan()}>Scan selected folders</button>
        <span className="muted small">The scan reads your photos in place.</span>
      </div>
    </>}
    {!tree && !error && <p className="muted">Loading folders…</p>}
    {job.running && <p role="status">{job.rescan_folder && <b>{job.rescan_folder} · </b>}{scanProgressText(job)}</p>}
    {!job.running && job.result && !error && <p role="status">{job.rescan_folder
      ? faceRescanSummary(job.rescan_folder, job.result)
      : `Last scan indexed ${job.result.added} new files and found ${job.result.faces} faces.`}</p>}
    {(error || job.error) && <p className="hint error" role="alert">{error || job.error}</p>}
  </section>
}

export function LibraryPage({ info, reload }: { info: LibraryInfo; reload: () => void }) {
  return <div className={info.open ? 'page settings library-page' : 'page settings'}>
    <header className="page-head">
      <h1>{info.open ? 'Library' : 'Welcome to Shoebox Archivist'}</h1>
    </header>
    {info.open ? <>
      <CurrentLibrary info={info} reload={reload} />
      <FolderScope reload={reload} />
      <ScanFamilySettings />
      {info.managed && <ResetLibrary />}
    </> : <NewLibrary info={info} />}
  </div>
}
