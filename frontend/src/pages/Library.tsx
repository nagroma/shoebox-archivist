import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Facet, type Keyword, type FolderListing, type LibraryInfo, type ProposedFacet, type ScanState } from '../api'

const KIND_HELP: Record<string, string> = {
  person: 'people (linked to faces)', event: 'events', place: 'places', subject: 'subjects',
  attribute: 'workflow / format tags', other: 'anything else',
}

/** Server-side folder browser (the server runs on this computer). */
function FolderPicker({ onPick }: { onPick: (folder: string) => void }) {
  const [listing, setListing] = useState<FolderListing | null>(null)
  const [typed, setTyped] = useState('')
  const [error, setError] = useState('')

  const go = useCallback(async (path: string) => {
    try {
      const l = await api.listFolder(path)
      setListing(l); setTyped(l.path); setError('')
    } catch (e) { setError((e as Error).message) }
  }, [])

  useEffect(() => { go('') }, [go])

  return (
    <div className="folder-picker">
      <div className="row">
        <input className="grow" value={typed} placeholder="Folder with your photos, e.g. D:\Photos"
          onChange={e => setTyped(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') go(typed) }} />
        <button onClick={() => go(typed)}>Go</button>
        <button className="primary" disabled={!listing?.path} onClick={() => listing && onPick(listing.path)}>
          Use this folder
        </button>
      </div>
      {error && <p className="hint error">{error}</p>}
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
  const [preset, setPreset] = useState('family')
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
    if (s.facets) setFacets(s.facets)
  }, [])
  useEffect(() => () => window.clearTimeout(timer.current), [])

  async function choose(path: string) {
    setError(''); setScan(null); setFacets(null); setFolder(path)
    try {
      const s = await api.inspectFolder(path)
      setScan(s)
      if (!s.existing) poll(preset)
    } catch (e) { setError((e as Error).message); setFolder(null) }
  }

  async function changePreset(p: string) {
    setPreset(p)
    if (scan?.result) poll(p)
  }

  const setFacet = (i: number, patch: Partial<Facet>) =>
    setFacets(fs => fs && fs.map((f, j) => (j === i ? { ...f, ...patch } : f)))

  async function create() {
    if (!folder || !facets) return
    setBusy(true); setError('')
    try {
      await api.createLibrary(folder, facets.map(f => ({ name: f.name, kind: f.kind })), useKeywords, curator)
      window.location.assign('/photos')
    } catch (e) { setError((e as Error).message); setBusy(false) }
  }

  async function open() {
    if (!folder) return
    setBusy(true)
    try { await api.openLibrary(folder); window.location.assign('/photos') }
    catch (e) { setError((e as Error).message); setBusy(false) }
  }

  const r = scan?.result
  return (
    <section className="card">
      <h2>{info.open ? 'Open or create another library' : 'Create a library'}</h2>
      <p className="muted small">
        A library is a folder of photos. The app keeps its own data in a <code>.shoebox</code> folder inside it;
        your photos are only changed when you name a face or edit a keyword, date or caption.
      </p>

      {!folder && <FolderPicker onPick={choose} />}
      {error && <p className="hint error">{error}</p>}

      {folder && (
        <>
          <div className="row">
            <b className="grow" style={{ wordBreak: 'break-all' }}>{folder}</b>
            <button onClick={() => { setFolder(null); setScan(null); setFacets(null) }} disabled={busy}>Change folder</button>
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

          {r && facets && (
            <div className="job">
              <p>
                <b>{r.images}</b> photo(s) found; <b>{r.with_keywords}</b> already have keywords
                ({r.n_paths} hierarchical, {r.n_flat} flat).
                {r.images > 0 && r.with_keywords === 0 && <> This will be an <b>empty</b> keyword set; it grows as you work.</>}
              </p>

              <div className="field-block">
                <label className="muted small" htmlFor="curator">Who is curating this library? (your full name)</label>
                <input id="curator" value={curator} placeholder="e.g. Jane Morgan" style={{ width: '100%', maxWidth: 360 }}
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
                <thead><tr><th>Top-level keyword group (facet)</th><th>Kind</th><th>In photos</th><th /></tr></thead>
                <tbody>
                  {facets.map((f, i) => (
                    <tr key={i}>
                      <td><input value={f.name} onChange={e => setFacet(i, { name: e.target.value })} /></td>
                      <td>
                        <select value={f.kind} onChange={e => setFacet(i, { kind: e.target.value })}>
                          {info.kinds.map(k => <option key={k} value={k}>{k} – {KIND_HELP[k] ?? ''}</option>)}
                        </select>
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

              {r.n_paths > 0 && (
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
              {r.n_flat > 0 && (
                <details>
                  <summary className="muted small">{r.n_flat} flat keyword(s) found (no group; filed under "Other Keywords" until you move them)</summary>
                  <ul className="kw-found">
                    {Object.entries(r.flat).map(([k, n]) => <li key={k}><code>{k}</code> <span className="muted">×{n}</span></li>)}
                  </ul>
                </details>
              )}

              <div className="action-bar">
                <button className="primary" onClick={create} disabled={busy || facets.some(f => !f.name.trim())}>
                  {busy ? 'Creating…' : 'Create library and import photos'}
                </button>
                <span className="muted small">Face detection starts right away (about 1 second per photo).</span>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  )
}

/** Facets, Keywords.txt export and reset for the open library. */
/** Keywords on no photo: mistakes, or vocabulary entries nobody used. */
function UnusedKeywords() {
  const [list, setList] = useState<Keyword[] | null>(null)
  const [error, setError] = useState('')
  const load = useCallback(() => {
    api.keywords().then(ks => setList(ks.filter(k => !k.photos))).catch(e => setError((e as Error).message))
  }, [])
  useEffect(() => { load() }, [load])
  if (!list?.length) return null
  async function del(k: Keyword) {
    try { await api.deleteKeyword(k.id); load() } catch (e) { setError((e as Error).message) }
  }
  return (
    <section className="card">
      <h2>Unused keywords <span className="muted">({list.length})</span></h2>
      <p className="muted small">Keywords on no photo. Delete mistakes; this doesn't touch any photo file.</p>
      <div className="kw-found">
        {list.map(k => (
          <span key={k.id} className={`kw ${k.kind}`} title={k.category}>
            {k.name} <button onClick={() => del(k)} title="Delete">×</button>
          </span>
        ))}
      </div>
      {error && <p className="hint error">{error}</p>}
    </section>
  )
}

function CurrentLibrary({ info, reload }: { info: LibraryInfo; reload: () => void }) {
  const [facets, setFacets] = useState<(Facet & { keywords?: number })[]>(info.facets ?? [])
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  const [confirm, setConfirm] = useState('')
  const [curator, setCurator] = useState(info.curator?.name ?? '')
  const dirty = JSON.stringify(facets.map(f => [f.name, f.kind])) !==
    JSON.stringify((info.facets ?? []).map(f => [f.name, f.kind]))

  async function save() {
    setError(''); setMsg('')
    try {
      await api.saveFacets(facets.map(f => ({ name: f.name, kind: f.kind })))
      setMsg('Saved'); reload()
    } catch (e) { setError((e as Error).message) }
  }

  async function reset() {
    setError('')
    try { await api.resetLibrary(confirm); window.location.assign('/library') }
    catch (e) { setError((e as Error).message) }
  }

  return (
    <>
      <section className="card">
        <h2>Current library</h2>
        <dl>
          <dt className="muted">Photo folder</dt><dd>{info.root}</dd>
          <dt className="muted">App data</dt><dd>{info.data_dir}</dd>
        </dl>
        <div className="field-block">
          <label className="muted small" htmlFor="curator-now">Curator (the person this family tree is measured from)</label>
          <div className="row">
            <input id="curator-now" value={curator} placeholder="Full name" onChange={e => setCurator(e.target.value)} />
            <button disabled={curator.trim() === (info.curator?.name ?? '')}
              onClick={async () => {
                try { await api.setCurator(curator); setMsg('Curator saved'); reload() }
                catch (e) { setError((e as Error).message) }
              }}>Save</button>
          </div>
        </div>
        <div className="row">
          <button onClick={async () => { await api.closeLibrary(); window.location.assign('/library') }}>Close library</button>
        </div>
      </section>

      <section className="card">
        <h2>Keyword facets</h2>
        <p className="muted small">
          Top-level keyword groups for this library. Keywords are stored in the photos as Bridge / Lightroom
          hierarchical keywords (<code>Facet|Group|Keyword</code>). A facet can only be removed or retyped
          from/to <i>person</i> while it has no keywords.
        </p>
        <table className="facets">
          <thead><tr><th>Facet</th><th>Kind</th><th>Keywords</th><th /></tr></thead>
          <tbody>
            {facets.map((f, i) => (
              <tr key={i}>
                <td><input value={f.name} disabled={!!f.keywords}
                  onChange={e => setFacets(fs => fs.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} /></td>
                <td>
                  <select value={f.kind}
                    onChange={e => setFacets(fs => fs.map((x, j) => j === i ? { ...x, kind: e.target.value } : x))}>
                    {info.kinds.concat(info.kinds.includes(f.kind) ? [] : [f.kind]).map(k => <option key={k}>{k}</option>)}
                  </select>
                </td>
                <td className="muted">{f.keywords ?? 0}</td>
                <td><button className="ghost" disabled={!!f.keywords} title="Remove"
                  onClick={() => setFacets(facets.filter((_, j) => j !== i))}>×</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row">
          <button className="ghost" onClick={() => setFacets([...facets, { name: '', kind: 'other' }])}>+ Add facet</button>
          <span className="grow" />
          <a href="/api/keywords/export" download="Keywords.txt">Export Keywords.txt (for Bridge / Lightroom)</a>
          <button className="primary" disabled={!dirty} onClick={save}>Save facets</button>
        </div>
        {msg && <p className="hint">{msg}</p>}
        {error && <p className="hint error">{error}</p>}
      </section>

      <UnusedKeywords />

      {info.managed && (
        <section className="card danger-zone">
          <h2>Reset this library</h2>
          <p className="muted small">
            Deletes the app's data for this folder (database, face names, thumbnails, facets) so it can be
            set up again like a new folder. Your photos are not deleted. Keywords, captions and dates the app
            already wrote into the photo files stay there and will be read as existing keywords the next time.
            (<code>pm strip</code> removes them from the files first, if you want a clean start.)
          </p>
          <div className="row">
            <input value={confirm} placeholder="Type reset to confirm" onChange={e => setConfirm(e.target.value)} />
            <button className="danger" disabled={confirm !== 'reset'} onClick={reset}>Reset library</button>
          </div>
        </section>
      )}
    </>
  )
}

export function LibraryPage({ info, reload }: { info: LibraryInfo; reload: () => void }) {
  return (
    <div className="page settings">
      <header className="page-head">
        <div>
          <h1>{info.open ? 'Library' : 'Welcome to Shoebox Archivist'}</h1>
          {!info.open && <p className="muted">Choose the folder that holds your photos to get started.</p>}
        </div>
      </header>
      {info.open && <CurrentLibrary info={info} reload={reload} />}
      <NewLibrary info={info} />
    </div>
  )
}
