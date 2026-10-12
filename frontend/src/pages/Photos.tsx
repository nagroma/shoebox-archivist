import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, imageUrl, type PhotoSummary } from '../api'
import { useApp } from '../state'
import { BatchEditor } from '../components/BatchEditor'

const FILTERS: [string, string][] = [
  ['all', 'All'],
  ['unnamed', 'Unnamed faces'],
  ['undated', 'No date'],
  ['has_back', 'Has back'],
]

/** Last list shown, so the photo page can step prev/next through it. */
export let photoSequence: number[] = []
export const setPhotoSequence = (ids: number[]) => { photoSequence = ids }

export function PhotosPage() {
  const { people } = useApp()
  const [params, setParams] = useSearchParams()
  const filter = params.get('filter') ?? 'all'
  const personId = params.get('person') ? Number(params.get('person')) : undefined
  const familyId = params.get('family') ? Number(params.get('family')) : undefined
  const generations = Number(params.get('generations') ?? 1) || 1
  const keywordId = params.get('keyword') ? Number(params.get('keyword')) : undefined
  const [keywordName, setKeywordName] = useState<string | null>(null)
  useEffect(() => {
    if (keywordId === undefined) { setKeywordName(null); return }
    api.keywords().then(ks => { const k = ks.find(x => x.id === keywordId); setKeywordName(k ? `${k.category}|${k.name}` : '?') })
  }, [keywordId])
  const [q, setQ] = useState(params.get('q') ?? '')
  const [photos, setPhotos] = useState<PhotoSummary[] | null>(null)
  const [version, setVersion] = useState(0)
  const [selected, setSelected] = useState<number[]>([])
  const anchor = useRef<number | null>(null)

  useEffect(() => {
    const bump = () => setVersion(v => v + 1)
    window.addEventListener('library-changed', bump)
    return () => window.removeEventListener('library-changed', bump)
  }, [])

  useEffect(() => {
    const t = setTimeout(() => {
      api.photos({ filter, person_id: personId, keyword_id: keywordId, family_id: familyId, generations, q: params.get('q') ?? undefined }).then(p => {
        setPhotos(p)
        photoSequence = p.map(x => x.id)
        const shown = new Set(photoSequence)
        setSelected(sel => sel.filter(id => shown.has(id)))
      })
    }, 0)
    return () => clearTimeout(t)
  }, [filter, personId, keywordId, familyId, generations, params, version])

  function set(key: string, value: string | null, ...alsoClear: string[]) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value); else next.delete(key)
    alsoClear.forEach(k => next.delete(k))
    setParams(next, { replace: true })
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input, textarea, select')) return
      if (e.key === 'Escape') setSelected([])
      if (e.key === 'a' && (e.ctrlKey || e.metaKey) && photos) { e.preventDefault(); setSelected(photos.map(p => p.id)) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [photos])

  /** Ctrl/Cmd-click or the checkbox toggles, Shift-click selects a range; a plain click opens the photo. */
  function select(e: React.MouseEvent, id: number, viaCheckbox = false) {
    if (!photos || !(viaCheckbox || e.ctrlKey || e.metaKey || e.shiftKey)) return
    e.preventDefault()
    e.stopPropagation()
    if (e.shiftKey && anchor.current !== null) {
      const ids = photos.map(p => p.id)
      const [a, b] = [ids.indexOf(anchor.current), ids.indexOf(id)].sort((x, y) => x - y)
      if (a >= 0) { setSelected([...new Set([...selected, ...ids.slice(a, b + 1)])]); return }
    }
    anchor.current = id
    setSelected(selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id])
  }

  const person = people.find(p => p.id === personId)
  const familyOf = people.find(p => p.id === familyId)

  return (
    <div className="page">
      <header className="page-head">
        <h1>Photos {photos && <span className="muted">({photos.length})</span>}</h1>
        <div className="row">
          <div className="tabs">
            {FILTERS.map(([k, label]) => (
              <button key={k} className={filter === k ? 'active' : ''} onClick={() => set('filter', k === 'all' ? null : k)}>
                {label}
              </button>
            ))}
          </div>
          {photos && photos.length > 0 && (selected.length
            ? <button onClick={() => setSelected([])}>Clear selection</button>
            : <button onClick={() => setSelected(photos.map(p => p.id))} title="Ctrl/Cmd+A">Select all</button>)}
          <input placeholder="Search keyword, caption, place, file…" value={q}
            onChange={e => setQ(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') set('q', q || null) }}
            onBlur={() => set('q', q || null)} />
        </div>
      </header>
      {(person || keywordName || familyOf) && (
        <p className="chip-row">
          {person && <span className="chip">With {person.name} <button onClick={() => set('person', null)}>×</button></span>}
          {familyOf && <span className="chip">Family of {familyOf.display_name}{generations > 1 && ` (${generations} generations)`} <button onClick={() => set('family', null, 'generations')}>×</button></span>}
          {keywordName && <span className="chip">Keyword {keywordName} <button onClick={() => set('keyword', null)}>×</button></span>}
        </p>
      )}
      {photos === null && <p className="muted">Loading…</p>}
      {photos?.length === 0 && <p className="empty">No photos match.</p>}
      {photos && photos.length > 0 && selected.length === 0 && (
        <p className="muted small">Tip: Ctrl/Cmd-click or tick photos (Shift-click for a range) to edit several at once.</p>
      )}
      <div className={selected.length ? 'photos-with-editor' : ''}>
      <div className="photo-grid">
        {photos?.map(p => (
          <Link key={p.id} to={`/photos/${p.id}`} onClick={e => select(e, p.id)}
            className={`photo-card ${selected.includes(p.id) ? 'selected' : ''}`}>
            <span className="pick" onClick={e => select(e, p.id, true)}>
              <input type="checkbox" readOnly checked={selected.includes(p.id)} tabIndex={-1} />
            </span>
            <img src={imageUrl(p.front_id, 'thumb')} loading="lazy" alt="" />
            <div className="meta">
              <span className={p.date ? '' : 'muted'}>{p.date?.display ?? 'No date'}</span>
              {p.faces > 0 && (
                <span className={`badge ${p.named === p.faces ? 'done' : ''}`} title="named / faces">
                  {p.named}/{p.faces}
                </span>
              )}
            </div>
          </Link>
        ))}
      </div>
      {selected.length > 0 && <BatchEditor ids={selected} onClose={() => setSelected([])} />}
      </div>
    </div>
  )
}
