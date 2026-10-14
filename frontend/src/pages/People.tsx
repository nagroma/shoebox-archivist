import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, faceThumb, type PersonDetail, type PersonRef, type Relatives } from '../api'
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

  // Person keywords seeded from the files' vocabulary can outnumber photographed people.
  const active = people.filter(p => p.photos > 0 || p.confirmed > 0 || p.suggested > 0)
  const shown = (showAll || filter ? people : active)
    .filter(p => p.name.toLowerCase().includes(filter.toLowerCase()) ||
      p.aliases.some(a => a.name.toLowerCase().includes(filter.toLowerCase())))
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
            <div className="name">{p.display_name}</div>
            {p.relation && <div className="rel small">{p.relation}</div>}
            {p.display_name !== p.name && <div className="muted small">born {p.name}</div>}
            <div className="muted small">
              {lifespan(p.birth_year, p.death_year)}
              {p.photos} photos · {p.confirmed} faces{p.suggested > 0 && <> · <span className="sugg-count">{p.suggested} to review</span></>}
            </div>
            {p.groups && <div className="muted groups">{p.groups}</div>}
            <button className="ghost small" title="Show this person's family tree"
              onClick={e => { e.preventDefault(); navigate(`/tree/${p.id}`) }}>Family tree</button>
          </Link>
        ))}
      </div>
    </div>
  )
}

/** Other names (married name, nickname). The keyword in the files keeps the main name;
 *  a name with a year is shown on photos dated from that year. */
function AliasCard({ person, onSaved }: { person: PersonDetail; onSaved: () => void }) {
  const run = useAction()
  const [rows, setRows] = useState<{ name: string; kind: string; from_year: string }[]>(
    person.aliases.map(a => ({ name: a.name, kind: a.kind, from_year: a.from_year?.toString() ?? '' })))
  const upd = (i: number, patch: Partial<(typeof rows)[number]>) =>
    setRows(rs => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const same = JSON.stringify(rows) === JSON.stringify(
    person.aliases.map(a => ({ name: a.name, kind: a.kind, from_year: a.from_year?.toString() ?? '' })))

  async function save() {
    const r = await run(() => api.saveAliases(person.id, rows.filter(x => x.name.trim()).map(x => ({
      name: x.name.trim(), kind: x.kind, from_year: x.from_year ? Number(x.from_year) : null,
    }))), 'Names saved')
    if (r) onSaved()
  }

  return (
    <section className="card">
      <h2>Other names</h2>
      <p className="muted small">
        Files keep the keyword <b>{person.keywords[0]?.name ?? person.name.replace(/\s+/g, '')}</b>; this app
        shows the name that fits the photo's date. Typing any of these names finds {person.name}.
      </p>
      {rows.map((r, i) => (
        <div key={i} className="row" style={{ marginBottom: 6 }}>
          <input value={r.name} placeholder="Full name" onChange={e => upd(i, { name: e.target.value })} />
          <select value={r.kind} onChange={e => upd(i, { kind: e.target.value })}>
            <option value="married">married name</option>
            <option value="birth">birth name</option>
            <option value="nickname">nickname</option>
            <option value="other">other</option>
          </select>
          <input value={r.from_year} placeholder="used from year" inputMode="numeric" style={{ width: 120 }}
            onChange={e => upd(i, { from_year: e.target.value.replace(/\D/g, '') })} />
          <button className="ghost" title="Remove" onClick={() => setRows(rs => rs.filter((_, j) => j !== i))}>×</button>
        </div>
      ))}
      <div className="row">
        <button className="ghost" onClick={() => setRows([...rows, { name: '', kind: 'married', from_year: '' }])}>+ Add name</button>
        <button className="primary" disabled={same} onClick={save}>Save names</button>
      </div>
    </section>
  )
}

/** Parents, partners and children of one person; siblings are derived. Labels are from the curator. */
function FamilyCard({ person, onChanged }: { person: PersonDetail; onChanged: () => void }) {
  const run = useAction()
  const [rel, setRel] = useState<Relatives | null>(null)
  useEffect(() => { api.relatives(person.id).then(setRel) }, [person.id])
  if (!rel) return null

  async function add(relation: 'parent' | 'child' | 'partner', who: PersonRef) {
    const r = await run(() => api.addRelative(person.id, relation, who))
    if (r) { setRel(r); onChanged() }
  }
  async function remove(relation: 'parent' | 'child' | 'partner', other: number) {
    const r = await run(() => api.removeRelative(person.id, relation, other))
    if (r) { setRel(r); onChanged() }
  }

  async function endPartnership(other: number, ended: boolean) {
    let year: number | null = null
    if (ended) {
      const text = window.prompt('Year the partnership ended (leave blank if unknown)', '')
      if (text === null) return
      year = text.trim() ? Number(text) : null
      if (year !== null && !Number.isInteger(year)) return
    }
    const r = await run(() => api.setPartnership(person.id, other, ended, year))
    if (r) { setRel(r); onChanged() }
  }

  const group = (title: string, relation: 'parent' | 'child' | 'partner', list: Relatives['parents'], noun: string,
                 former = false) => (
    <div className="family-group">
      <div className="muted small">{title}</div>
      <div className="row">
        {list.map(r => (
          <span key={r.id} className="kw person">
            <Link to={`/people/${r.id}`}>{r.name}</Link>
            {r.relation && <span className="muted small"> {r.relation}</span>}
            {former && <span className="muted small"> {r.end_year ? `ended ${r.end_year}` : 'ended'}</span>}
            {relation === 'partner' && (
              <button title={former ? 'Partners again' : 'Mark as a former partner'}
                onClick={() => endPartnership(r.id, !former)}>{former ? '↺' : 'ended'}</button>
            )}
            <button title="Remove link" onClick={() => remove(relation, r.id)}>×</button>
          </span>
        ))}
        {!former && (
          <PersonPicker buttonLabel="Add" placeholder={`Add ${noun}…`} excludeId={person.id} clearOnPick
            onPick={who => add(relation, who)} />
        )}
      </div>
    </div>
  )

  return (
    <section className="card">
      <h2>Family</h2>
      {!rel.curator && <p className="muted small">Set the curator on the Library page so relatives are labelled from them.</p>}
      {group('Parents', 'parent', rel.parents, 'parent')}
      {group('Partners', 'partner', rel.partners, 'partner')}
      {rel.former_partners.length > 0 && group('Former partners', 'partner', rel.former_partners, 'partner', true)}
      {group('Children', 'child', rel.children, 'child')}
      {rel.siblings.length > 0 && (
        <div className="family-group">
          <div className="muted small">Siblings (shared parent)</div>
          <div className="row">
            {rel.siblings.map(r => <Link key={r.id} to={`/people/${r.id}`} className="kw person">{r.name}</Link>)}
          </div>
        </div>
      )}
    </section>
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
  const [form, setForm] = useState({ name: '', birth_year: '', death_year: '', name_from_year: '', notes: '' })
  const [selSugg, setSelSugg] = useState<Set<number>>(new Set())
  const [selConf, setSelConf] = useState<Set<number>>(new Set())

  const load = useCallback(async () => {
    const d = await api.person(pid)
    setP(d)
    setForm({
      name: d.name, birth_year: d.birth_year?.toString() ?? '',
      death_year: d.death_year?.toString() ?? '', name_from_year: d.name_from_year?.toString() ?? '',
      notes: d.notes ?? '',
    })
    setSelSugg(new Set()); setSelConf(new Set())
    refresh()
  }, [pid, refresh])

  useEffect(() => { load() }, [load])

  if (!p) return <p className="muted pad">Loading…</p>

  const dirty = form.name !== p.name || form.birth_year !== (p.birth_year?.toString() ?? '') ||
    form.death_year !== (p.death_year?.toString() ?? '') ||
    form.name_from_year !== (p.name_from_year?.toString() ?? '') || form.notes !== (p.notes ?? '')

  async function save() {
    const year = (s: string) => (s.trim() ? Number(s) : null)
    const r = await run(() => api.updatePerson(pid, {
      name: form.name, birth_year: year(form.birth_year), death_year: year(form.death_year),
      name_from_year: year(form.name_from_year), notes: form.notes || null,
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
          <h1>{p.display_name}{p.relation && <span className="muted rel-tag"> · {p.relation}</span>}</h1>
          {p.keywords.length > 0 && <p className="muted small">
            Keyword{p.keywords.length > 1 && 's'}: {p.keywords.map(k => (
              <Link key={k.id} to={`/photos?keyword=${k.id}`}><code>{k.category}|{k.name}</code></Link>
            )).reduce<React.ReactNode[]>((acc, el, i) => (i ? [...acc, ', ', el] : [el]), [])}
            {' '}· on {p.keywords.reduce((n, k) => n + k.photos, 0)} photos
          </p>}
        </div>
        <div className="row">
          <Link to={`/photos?person=${pid}`}><button>View photos</button></Link>
          <Link to={`/tree/${pid}`}><button>Family tree</button></Link>
        </div>
      </header>

      <section className="card person-form">
        <label>Name <input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
        <label title="Year this name came into use. Leave blank if it was always their name.">Name used from <input value={form.name_from_year} placeholder="year" inputMode="numeric"
          onChange={e => setForm({ ...form, name_from_year: e.target.value.replace(/\D/g, '') })} style={{ width: 80 }} /></label>
        <label>Born <input value={form.birth_year} placeholder="year" inputMode="numeric"
          onChange={e => setForm({ ...form, birth_year: e.target.value.replace(/\D/g, '') })} style={{ width: 80 }} /></label>
        <label>Died <input value={form.death_year} placeholder="year" inputMode="numeric"
          onChange={e => setForm({ ...form, death_year: e.target.value.replace(/\D/g, '') })} style={{ width: 80 }} /></label>
        <label className="grow">Notes <input value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></label>
        <button className="primary" disabled={!dirty} onClick={save}>Save</button>
        <p className="muted small full">Birth/death years stop this person being suggested in photos dated outside their lifetime. <b>Notes</b> are for you only: they stay in the app and are not written to photo files.</p>
      </section>

      <FamilyCard person={p} onChanged={() => { refresh() }} />

      <AliasCard key={p.id + ':' + JSON.stringify(p.aliases)} person={p} onSaved={load} />

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
