import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, displayName, faceThumb, imageUrl, type Face, type ParsedDate, type PhotoDetail } from '../api'
import { KeywordsCard } from '../components/Keywords'
import { FileMetadata } from '../components/FileMetadata'
import { PersonPicker } from '../components/PersonPicker'
import { useAction, useApp } from '../state'
import { photoSequence, setPhotoSequence } from './Photos'

type Form = { date_text: string; location: string; caption: string; back_text: string; notes: string }

const toForm = (p: PhotoDetail): Form => ({
  date_text: p.date?.display ?? p.date_text ?? '',
  location: p.location ?? '', caption: p.caption ?? '', back_text: p.back_text ?? '', notes: p.notes ?? '',
})

export function PhotoDetailPage() {
  const { id } = useParams()
  const photoId = Number(id)
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const { refresh } = useApp()
  const run = useAction()
  const [photo, setPhoto] = useState<PhotoDetail | null>(null)
  const [form, setForm] = useState<Form | null>(null)
  const [side, setSide] = useState<'front' | 'back'>('front')
  const [activeFace, setActiveFace] = useState<number | null>(search.get('face') ? Number(search.get('face')) : null)
  const [showBoxes, setShowBoxes] = useState(true)

  const load = useCallback(async () => {
    const p = await api.photo(photoId)
    setPhoto(p)
    setForm(toForm(p))
  }, [photoId])

  useEffect(() => { setSide('front'); load() }, [load])

  // Opened directly (not from the Photos list): step through all photos.
  const [, setSeqLoaded] = useState(false)
  useEffect(() => {
    if (photoSequence.length === 0)
      api.photos({}).then(ps => { setPhotoSequence(ps.map(x => x.id)); setSeqLoaded(true) })
  }, [])

  const idx = photoSequence.indexOf(photoId)
  const prev = idx > 0 ? photoSequence[idx - 1] : null
  const next = idx >= 0 && idx < photoSequence.length - 1 ? photoSequence[idx + 1] : null

  const dirty = photo && form && JSON.stringify(form) !== JSON.stringify(toForm(photo))

  const save = useCallback(async () => {
    if (!form) return false
    const r = await run(() => api.updatePhoto(photoId, { ...form }), 'Saved')
    if (r) { setPhoto(r); setForm(toForm(r)); refresh() }
    return !!r
  }, [form, photoId, run, refresh])

  const go = useCallback(async (target: number | null) => {
    if (target === null) return
    if (dirty && !(await save())) return
    setActiveFace(null)
    navigate(`/photos/${target}`)
  }, [dirty, save, navigate])

  // Keyboard: ←/→ prev/next (outside inputs), Ctrl/Cmd+S save.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const inField = (e.target as HTMLElement).closest('input, textarea')
      if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); save() }
      else if (!inField && e.key === 'ArrowLeft') go(prev)
      else if (!inField && e.key === 'ArrowRight') go(next)
      else if (!inField && e.key === 'b' && photo?.images.some(i => i.role === 'back'))
        setSide(s => (s === 'front' ? 'back' : 'front'))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go, prev, next, save, photo])

  if (!photo || !form) return <p className="muted pad">Loading…</p>

  const front = photo.images.find(i => i.role === 'front') ?? photo.images[0]
  const back = photo.images.find(i => i.role === 'back')
  const shown = side === 'back' && back ? back : front
  const faces = photo.faces.filter(f => f.image_id === shown.id)

  async function faceAct(fn: () => Promise<unknown>, msg: string) {
    if ((await run(fn, msg)) !== undefined) { await load(); refresh() }
  }

  return (
    <div className="photo-detail">
      <div className="viewer">
        <div className="viewer-bar">
          <button onClick={() => navigate(-1)}>← Back</button>
          <button disabled={prev === null} onClick={() => go(prev)} title="Previous (←)">‹ Prev</button>
          <button disabled={next === null} onClick={() => go(next)} title="Next (→)">Next ›</button>
          {idx >= 0 && <span className="muted small">{idx + 1} / {photoSequence.length}</span>}
          <span className="grow" />
          {back && (
            <div className="tabs">
              <button className={side === 'front' ? 'active' : ''} onClick={() => setSide('front')}>Front</button>
              <button className={side === 'back' ? 'active' : ''} onClick={() => setSide('back')} title="Toggle (B)">Back</button>
            </div>
          )}
          <label className="small"><input type="checkbox" checked={showBoxes} onChange={e => setShowBoxes(e.target.checked)} /> Face boxes</label>
        </div>
        <div className="stage">
          <div className="img-wrap">
            <img src={imageUrl(shown.id)} alt="" />
            {showBoxes && (
              <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="boxes">
                {faces.map(f => (
                  <rect key={f.id}
                    x={f.bbox[0]} y={f.bbox[1]} width={f.bbox[2] - f.bbox[0]} height={f.bbox[3] - f.bbox[1]}
                    className={`box ${f.status} ${activeFace === f.id ? 'active' : ''}`}
                    vectorEffect="non-scaling-stroke"
                    onClick={() => setActiveFace(f.id)} />
                ))}
              </svg>
            )}
            {showBoxes && faces.map(f => (
              <span key={f.id} className={`box-label ${f.status}`}
                style={{ left: `${f.bbox[0] * 100}%`, top: `${f.bbox[3] * 100}%` }}
                onClick={() => setActiveFace(f.id)}>
                {f.status === 'confirmed' ? f.person_name : f.status === 'suggested' ? `${f.person_name}?` : f.status === 'ignored' ? '' : '?'}
              </span>
            ))}
          </div>
        </div>
        <div className="muted small path">{shown.path}</div>
      </div>

      <aside className="side">
        <section className="card">
          <h2>Details</h2>
          <DateField value={form.date_text} onChange={v => setForm({ ...form, date_text: v })} />
          {photo.date_source === 'xmp' && form.date_text === toForm(photo).date_text && (
            <p className="source">🗂 From the file: {photo.date_original?.slice(0, 10)}
              {photo.keywords.some(k => k.name === 'unknowndate') && <> · tagged <i>unknowndate</i>, so read as circa year</>}</p>
          )}
          {photo.date_source === 'exif' && form.date_text === toForm(photo).date_text && (
            <p className="source">📷 From camera info{photo.taken_at && <> · taken {photo.taken_at.replace('T', ' ')}</>}</p>
          )}
          <label>Location<input value={form.location} onChange={e => setForm({ ...form, location: e.target.value })}
            placeholder="e.g. Grandma's farm, Lancaster PA" /></label>
          {photo.gps_lat !== null && photo.gps_lon !== null && (
            <p className="source">
              📍 {photo.location_source === 'gps' && form.location === toForm(photo).location ? 'Nearest town from GPS · ' : 'GPS '}
              <a href={`https://www.openstreetmap.org/?mlat=${photo.gps_lat}&mlon=${photo.gps_lon}#map=15/${photo.gps_lat}/${photo.gps_lon}`}
                target="_blank" rel="noreferrer">{photo.gps_lat.toFixed(5)}, {photo.gps_lon.toFixed(5)} ↗</a>
            </p>
          )}
          <label>Caption<textarea rows={2} value={form.caption} onChange={e => setForm({ ...form, caption: e.target.value })} /></label>
          <label>Written on back
            <textarea rows={3} value={form.back_text} onChange={e => setForm({ ...form, back_text: e.target.value })}
              placeholder={back ? 'Transcribe the handwriting…' : 'No back scanned'} />
          </label>
          <label>Notes<textarea rows={2} value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></label>
          <div className="row">
            <button className="primary" disabled={!dirty} onClick={save}>Save</button>
            {dirty && <button onClick={() => setForm(toForm(photo))}>Revert</button>}
            <span className="muted small">Ctrl+S saves · ←/→ saves and moves</span>
          </div>
        </section>

        <section className="card">
          <h2>People <span className="muted">({photo.faces.filter(f => f.status !== 'ignored').length})</span></h2>
          {photo.faces.length === 0 && <p className="muted small">No faces detected.</p>}
          <ul className="face-list">
            {[...photo.faces].sort((a, b) => a.bbox[0] - b.bbox[0]).map(f => (
              <FaceRow key={f.id} face={f} active={activeFace === f.id}
                onFocus={() => setActiveFace(f.id)} act={faceAct} />
            ))}
          </ul>
          <p className="muted small">Listed left to right.</p>
          {(() => {
            const shownPeople = new Set(photo.faces.filter(f => f.status !== 'ignored').map(f => f.person_id))
            const missing = photo.keywords.filter(k => k.person_id && !shownPeople.has(k.person_id))
            return missing.length > 0 && (
              <p className="muted small">In keywords but no face matched: {missing.map(k => displayName(k.name)).join(', ')}</p>
            )
          })()}
        </section>

        <KeywordsCard photoId={photoId} keywords={photo.keywords} onChange={() => { load(); refresh() }} />
        <FileMetadata key={photoId} photoId={photoId} />
      </aside>
    </div>
  )
}

function FaceRow({ face, active, onFocus, act }: {
  face: Face; active: boolean; onFocus: () => void
  act: (fn: () => Promise<unknown>, msg: string) => void
}) {
  const ref = useRef<HTMLLIElement>(null)
  useEffect(() => { if (active) ref.current?.scrollIntoView({ block: 'nearest' }) }, [active])
  const ids = [face.id]
  return (
    <li ref={ref} className={`face-row ${active ? 'active' : ''} ${face.status}`} onClick={onFocus}>
      <img src={faceThumb(face.id)} alt="" />
      <div className="grow">
        <div className="who">
          {face.status === 'confirmed' && <Link to={`/people/${face.person_id}`}>{face.person_name}</Link>}
          {face.status === 'suggested' && <>{face.person_name}? <span className="muted small">{whyText(face)}</span></>}
          {face.status === 'confirmed' && face.label_source === 'keyword' &&
            <span className="muted small"> · from keywords (only face)</span>}
          {face.status === 'unknown' && <span className="muted">Unknown</span>}
          {face.status === 'ignored' && <span className="muted">Ignored</span>}
        </div>
        <div className="row wrap">
          {face.status === 'suggested' && (
            <>
              <button className="primary" onClick={() => act(() => api.assign(ids, { person_id: face.person_id! }), 'Confirmed')}>✓ Yes</button>
              <button onClick={() => act(() => api.reject(ids), 'Rejected')}>✗ No</button>
            </>
          )}
          {face.status === 'ignored' ? (
            <button onClick={() => act(() => api.unignore(ids), 'Restored')}>Restore</button>
          ) : (
            <>
              <PersonPicker buttonLabel={face.status === 'confirmed' ? 'Change' : 'Set'} placeholder="Name…"
                onPick={(who, label) => act(() => api.assign(ids, who), `Named ${label}`)} />
              {face.status === 'confirmed' && <button onClick={() => act(() => api.reject(ids), 'Removed')} title="Not this person">✗</button>}
              <button className="ghost" onClick={() => act(() => api.ignore(ids), 'Ignored')} title="Not worth naming">Ignore</button>
            </>
          )}
        </div>
      </div>
    </li>
  )
}

/** Free-form date entry with a live preview of how it was understood. */
function DateField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [parsed, setParsed] = useState<ParsedDate | null | undefined>(undefined)
  useEffect(() => {
    if (!value.trim()) { setParsed(undefined); return }
    const t = setTimeout(() => api.parseDate(value).then(r => setParsed(r.date)), 200)
    return () => clearTimeout(t)
  }, [value])
  return (
    <label>Date
      <input value={value} onChange={e => onChange(e.target.value)}
        placeholder="e.g. 1920s, c. 1925, May 1923, summer 1948, 1920-1925"
        className={parsed === null ? 'invalid' : ''} />
      <span className={`hint ${parsed === null ? 'error' : parsed === undefined ? 'muted' : ''}`}>
        {parsed === undefined && 'Unknown date'}
        {parsed === null && 'Not understood — try "1920s", "c. 1925", "May 1923"'}
        {parsed && <>{parsed.display} · {parsed.precision} · {parsed.min} → {parsed.max} · <code>{parsed.edtf}</code></>}
      </span>
    </label>
  )
}

function whyText(f: Face) {
  const sim = f.confidence !== null ? f.confidence.toFixed(2) : ''
  if (f.label_source === 'keyword_match') return `named in keywords · ${sim}`
  if (f.label_source === 'elimination') return 'last name left in keywords'
  return sim
}
