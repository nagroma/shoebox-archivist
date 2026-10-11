import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, faceThumb, type PersonDetail } from '../api'
import { FaceGrid } from '../components/FaceGrid'
import { PersonPicker } from '../components/PersonPicker'
import { useAction, useApp } from '../state'

export function PeoplePage() {
  const { people, refresh } = useApp()
  const run = useAction()
  const navigate = useNavigate()
  const [filter, setFilter] = useState('')
  const [showAll, setShowAll] = useState(false)

  useEffect(() => { refresh() }, [refresh])

  // Keywords.txt lists ~350 people; most have no photos yet.
  const active = people.filter(p => p.photos > 0 || p.confirmed > 0 || p.suggested > 0)
  const shown = (showAll || filter ? people : active)
    .filter(p => p.name.toLowerCase().includes(filter.toLowerCase()))
    .sort((a, b) => b.photos + b.confirmed - (a.photos + a.confirmed) || a.name.localeCompare(b.name))

  return (
    <div className="page">
      <header className="page-head">
        <h1>People <span className="muted">({active.length})</span></h1>
        <div className="row">
          <label className="small"><input type="checkbox" checked={showAll} onChange={e => setShowAll(e.target.checked)} />
            {' '}Include everyone in the keyword list ({people.length})</label>
          <input placeholder="Filter…" value={filter} onChange={e => setFilter(e.target.value)} />
          <button onClick={async () => {
            const name = prompt('New person name')
            if (!name?.trim()) return
            const p = await run(() => api.createPerson(name.trim()))
            if (p) { await refresh(); navigate(`/people/${p.id}`) }
          }}>+ Add person</button>
        </div>
      </header>
      {people.length === 0 && <p className="empty">No people yet — name a cluster on the Faces page.</p>}
      <div className="people-grid">
        {shown.map(p => (
          <Link key={p.id} to={`/people/${p.id}`} className="person-card">
            {p.cover ? <img src={faceThumb(p.cover)} alt="" /> : <div className="noface">?</div>}
            <div className="name">{p.name}</div>
            <div className="muted small">
              {lifespan(p.birth_year, p.death_year)}
              {p.photos} photos · {p.confirmed} faces{p.suggested > 0 && <> · <span className="sugg-count">{p.suggested} to review</span></>}
            </div>
            {p.groups && <div className="muted groups">{p.groups}</div>}
          </Link>
        ))}
      </div>
    </div>
  )
}

function lifespan(b: number | null, d: number | null) {
  if (!b && !d) return null
  return <>{b ?? '?'}–{d ?? ''} · </>
}

export function PersonPage() {
  const { id } = useParams()
  const pid = Number(id)
  const { refresh } = useApp()
  const run = useAction()
  const navigate = useNavigate()
  const [p, setP] = useState<PersonDetail | null>(null)
  const [form, setForm] = useState({ name: '', birth_year: '', death_year: '', notes: '' })
  const [selSugg, setSelSugg] = useState<Set<number>>(new Set())
  const [selConf, setSelConf] = useState<Set<number>>(new Set())

  const load = useCallback(async () => {
    const d = await api.person(pid)
    setP(d)
    setForm({
      name: d.name, birth_year: d.birth_year?.toString() ?? '',
      death_year: d.death_year?.toString() ?? '', notes: d.notes ?? '',
    })
    setSelSugg(new Set()); setSelConf(new Set())
    refresh()
  }, [pid, refresh])

  useEffect(() => { load() }, [load])

  if (!p) return <p className="muted pad">Loading…</p>

  const dirty = form.name !== p.name || form.birth_year !== (p.birth_year?.toString() ?? '') ||
    form.death_year !== (p.death_year?.toString() ?? '') || form.notes !== (p.notes ?? '')

  async function save() {
    const year = (s: string) => (s.trim() ? Number(s) : null)
    const r = await run(() => api.updatePerson(pid, {
      name: form.name, birth_year: year(form.birth_year), death_year: year(form.death_year), notes: form.notes || null,
    }), 'Saved')
    if (r) load()
  }

  async function act(fn: () => Promise<unknown>, msg: string) {
    if ((await run(fn, msg)) !== undefined) load()
  }

  const suggIds = selSugg.size ? [...selSugg] : p.suggested.map(f => f.id)

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <Link to="/people" className="muted">← People</Link>
          <h1>{p.name}</h1>
          {p.keywords.length > 0 && <p className="muted small">
            Keyword{p.keywords.length > 1 && 's'}: {p.keywords.map(k => (
              <Link key={k.id} to={`/photos?keyword=${k.id}`}><code>{k.category}|{k.name}</code></Link>
            )).reduce<React.ReactNode[]>((acc, el, i) => (i ? [...acc, ', ', el] : [el]), [])}
            {' '}· on {p.keywords.reduce((n, k) => n + k.photos, 0)} photos
          </p>}
        </div>
        <div className="row">
          <Link to={`/photos?person=${pid}`}><button>View photos</button></Link>
        </div>
      </header>

      <section className="card person-form">
        <label>Name <input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
        <label>Born <input value={form.birth_year} placeholder="year" inputMode="numeric"
          onChange={e => setForm({ ...form, birth_year: e.target.value.replace(/\D/g, '') })} style={{ width: 80 }} /></label>
        <label>Died <input value={form.death_year} placeholder="year" inputMode="numeric"
          onChange={e => setForm({ ...form, death_year: e.target.value.replace(/\D/g, '') })} style={{ width: 80 }} /></label>
        <label className="grow">Notes <input value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></label>
        <button className="primary" disabled={!dirty} onClick={save}>Save</button>
        <p className="muted small full">Birth/death years stop this person being suggested in photos dated outside their lifetime.</p>
      </section>

      {p.suggested.length > 0 && (
        <section className="card">
          <div className="card-head">
            <h2>Suggested — is this {p.name}? <span className="muted">({p.suggested.length})</span></h2>
            <div className="row">
              <button onClick={() => setSelSugg(new Set(p.suggested.map(f => f.id)))}>Select all</button>
              <button onClick={() => setSelSugg(new Set())} disabled={!selSugg.size}>Clear</button>
            </div>
          </div>
          <p className="muted small">Select the wrong ones and click <b>Not {p.name}</b>, then <b>Confirm</b> the rest.</p>
          <FaceGrid faces={p.suggested} selected={selSugg} onSelect={setSelSugg} />
          <div className="action-bar">
            <span className="scope">{selSugg.size ? `${selSugg.size} selected` : `all ${p.suggested.length}`}</span>
            <button className="primary" onClick={() => act(() => api.assign(suggIds, { person_id: pid }), `Confirmed ${suggIds.length}`)}>
              Confirm
            </button>
            <button disabled={!selSugg.size} onClick={() => act(() => api.reject([...selSugg]), 'Rejected')}>
              Not {p.name}
            </button>
          </div>
        </section>
      )}

      <section className="card">
        <div className="card-head">
          <h2>Confirmed <span className="muted">({p.confirmed.length})</span></h2>
          <div className="row">
            <button onClick={() => setSelConf(new Set(p.confirmed.map(f => f.id)))}>Select all</button>
            <button onClick={() => setSelConf(new Set())} disabled={!selConf.size}>Clear</button>
          </div>
        </div>
        <FaceGrid faces={p.confirmed} selected={selConf} onSelect={setSelConf} showNames={false} />
        <div className="action-bar">
          <span className="scope">{selConf.size} selected</span>
          <button disabled={!selConf.size} onClick={() => act(() => api.reject([...selConf]), `Removed ${selConf.size}`)}
            title="Not this person - won't be suggested as them again">
            Not {p.name}
          </button>
          <PersonPicker buttonLabel="Move to" placeholder="Move to person…" disabled={!selConf.size}
            excludeId={pid} onPick={(who, label) => act(() => api.assign([...selConf], who), `Moved to ${label}`)} />
          <button disabled={selConf.size !== 1}
            onClick={() => act(() => api.updatePerson(pid, { cover_face_id: [...selConf][0] }), 'Cover set')}>
            Use as cover
          </button>
        </div>
      </section>

      <section className="card danger-zone">
        <h2>Merge or delete</h2>
        <div className="action-bar">
          <span className="muted small">Merge {p.name} into:</span>
          <PersonPicker buttonLabel="Merge" placeholder="Person…" excludeId={pid} allowNew={false}
            onPick={async who => {
              if (!('person_id' in who)) return
              if (!confirm(`Merge ${p.name} into the selected person? This can't be undone.`)) return
              if (await run(() => api.mergePerson(pid, who.person_id), 'Merged')) {
                await refresh(); navigate(`/people/${who.person_id}`)
              }
            }} />
          <button className="danger" onClick={async () => {
            if (!confirm(`Delete ${p.name}? Their faces go back to unnamed.`)) return
            if (await run(() => api.deletePerson(pid), 'Deleted')) { await refresh(); navigate('/people') }
          }}>Delete person</button>
        </div>
      </section>
    </div>
  )
}
