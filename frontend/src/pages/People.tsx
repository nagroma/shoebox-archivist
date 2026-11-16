import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, faceThumb, type PersonDetail, type PersonRef, type PhotoSummary, type Relatives } from '../api'
import { FaceGrid, FaceThumbnailSizeSlider, PeopleKeywordsCheckbox } from '../components/FaceGrid'
import { confirmedFacesForDisplay } from '../confirmedFaces'
import { useFaceThumbnailSize } from '../faceThumbnailSize'
import { PersonPicker } from '../components/PersonPicker'
import { keywordSpelling } from '../keywordSpelling'
import { PersonKeywordForm } from '../components/PersonKeywordForm'
import { useAction, useApp } from '../state'
import { PEOPLE_SORT_OPTIONS, loadPeopleSort, rememberPeopleSort, sortPeople, type PeopleSort, type PeopleSortKey } from '../peopleSort'

export function PeoplePage() {
  const { people, refresh } = useApp()
  const navigate = useNavigate()
  const [filter, setFilter] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [sort, setSort] = useState(loadPeopleSort)

  useEffect(() => { refresh() }, [refresh])

  const sorted = useMemo(() => sortPeople(people, sort), [people, sort])
  const active = sorted.filter(p => p.photos > 0 || p.confirmed > 0 || p.suggested > 0)
  const shown = (showAll || filter ? sorted : active)
    .filter(p => p.name.toLowerCase().includes(filter.toLowerCase()) ||
      p.aliases.some(a => a.name.toLowerCase().includes(filter.toLowerCase())))

  function updateSort(next: PeopleSort) {
    setSort(next)
    rememberPeopleSort(next)
  }

  const ascending = sort.direction === 'asc'
  const nameSort = sort.key === 'firstName' || sort.key === 'lastName'
  const orderLabel = nameSort ? (ascending ? 'A–Z' : 'Z–A') : (ascending ? 'Fewest first' : 'Most first')

  return (
    <div className="page">
      <header className="page-head">
        <h1>People <span className="muted">({active.length})</span></h1>
        <div className="row wrap">
          <label className="row">Sort by
            <select value={sort.key} onChange={e => {
              const key = e.target.value as PeopleSortKey
              updateSort({ key, direction: PEOPLE_SORT_OPTIONS[key].direction })
            }}>
              {Object.entries(PEOPLE_SORT_OPTIONS).map(([key, { label }]) =>
                <option key={key} value={key}>{label}</option>)}
            </select>
          </label>
          <button type="button" aria-label={`Sort order, ${orderLabel}. Reverse sort order`}
            onClick={() => updateSort({ ...sort, direction: ascending ? 'desc' : 'asc' })}>
            <span aria-hidden="true">{ascending ? '↑' : '↓'}</span> {orderLabel}
          </button>
          <label className="small"><input type="checkbox" checked={showAll} onChange={e => setShowAll(e.target.checked)} />
            {' '}Include everyone in the keyword list ({people.length})</label>
          <input autoComplete="off" placeholder="Filter…" value={filter} onChange={e => setFilter(e.target.value)} />
          <PersonPicker buttonLabel="Add" placeholder="Find or create a person…" clearOnPick
            onPick={who => { if ('person_id' in who) navigate(`/people/${who.person_id}`) }} />
        </div>
      </header>
      {people.length === 0 && <p className="empty">No people yet — name a cluster on the Faces page.</p>}
      <div className="people-grid">
        {shown.map(p => (
          <Link key={p.id} to={`/people/${p.id}`} className="person-card">
            {p.cover ? <img src={faceThumb(p.cover)} alt="" /> : <div className="noface">?</div>}
            <div className="name">{p.display_name}</div>
            {p.relation && <div className="person-relationship rel small">{p.relation}</div>}
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

function PersonKeywordsCard({ person, onSaved }: { person: PersonDetail; onSaved: () => void }) {
  const run = useAction()
  const [selected, setSelected] = useState(person.keyword_ids)
  const [adding, setAdding] = useState(person.keywords.length === 0)
  const [category, setCategory] = useState('')
  const [name, setName] = useState(keywordSpelling(person.name))
  const [saving, setSaving] = useState(false)
  async function save() {
    setSaving(true)
    const r = await run(() => api.savePersonKeywords(person.id, selected,
      adding ? category : undefined, adding ? name : undefined), 'Keyword choices saved')
    setSaving(false)
    if (r) onSaved()
  }
  return <section className="card">
    <h2>Keywords for face confirmations</h2>
    <p className="muted small">Select the keyword or combination to add when you confirm this person.
      Saving these choices leaves previously labelled photos as they are.</p>
    {person.keywords.map(k => <label className="row" key={k.id}>
      <input type="checkbox" checked={selected.includes(k.id)} onChange={e =>
        setSelected(e.target.checked ? [...selected, k.id] : selected.filter(id => id !== k.id))} />
      <code>{k.category}|{k.name}</code>
    </label>)}
    <label className="row"><input type="checkbox" checked={adding} onChange={e => setAdding(e.target.checked)} />
      Add a keyword for this person</label>
    {adding && <PersonKeywordForm category={category} name={name} onChange={(c, n) => { setCategory(c); setName(n) }} />}
    <button className="primary" disabled={saving || (adding ? !category.trim() || !name.trim() : !selected.length)}
      onClick={save}>{saving ? 'Saving…' : 'Save keyword choices'}</button>
  </section>
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
          <input autoComplete="off" value={r.name} placeholder="Full name" onChange={e => upd(i, { name: e.target.value })} />
          <select value={r.kind} onChange={e => upd(i, { kind: e.target.value })}>
            <option value="married">married name</option>
            <option value="birth">birth name</option>
            <option value="nickname">nickname</option>
            <option value="other">other</option>
          </select>
          <input autoComplete="off" value={r.from_year} placeholder="used from year" inputMode="numeric" style={{ width: 120 }}
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

  const group = (title: string, relation: 'parent' | 'child' | 'partner', list: Relatives['parents'], noun: string) => (
    <div className="family-group">
      <div className="muted small">{title}</div>
      <div className="row wrap">
        {list.map(r => (
          <span key={r.id} className="kw person">
            <Link to={`/people/${r.id}`}>
              {r.name}
              {r.relation && <span className="person-relationship muted small">{r.relation}</span>}
            </Link>
            <button title="Remove link" onClick={() => remove(relation, r.id)}>×</button>
          </span>
        ))}
        <PersonPicker buttonLabel="Add" placeholder={`Add ${noun}…`} excludeId={person.id} clearOnPick
          onPick={who => add(relation, who)} />
      </div>
    </div>
  )

  return (
    <section className="card">
      <h2>Family</h2>
      {!rel.curator && <p className="muted small">Set the curator on the Library page so relatives are labelled from them.</p>}
      {group('Parents', 'parent', rel.parents, 'parent')}
      {group('Partners', 'partner', rel.partners, 'partner')}
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

type FaceReviewAction = 'confirm' | 'reject' | 'ignore'
type FaceReviewList = 'suggested' | 'confirmed'

export function PersonPage() {
  const { id } = useParams()
  const pid = Number(id)
  const { refresh, showPeopleKeywords, setShowPeopleKeywords } = useApp()
  const run = useAction()
  const navigate = useNavigate()
  const [p, setP] = useState<PersonDetail | null>(null)
  const [photos, setPhotos] = useState<PhotoSummary[]>([])
  const [form, setForm] = useState({ name: '', birth_year: '', death_year: '', name_from_year: '', notes: '' })
  const [selSugg, setSelSugg] = useState<Set<number>>(new Set())
  const [selConf, setSelConf] = useState<Set<number>>(new Set())
  const [pendingReview, setPendingReview] = useState<{ action: FaceReviewAction; list: FaceReviewList; count: number } | null>(null)
  const [thumbnailSize, setThumbnailSize] = useFaceThumbnailSize()

  const load = useCallback(async () => {
    const [d, personPhotos] = await Promise.all([api.person(pid), api.photos({ person_id: pid })])
    setP(d)
    setPhotos(personPhotos)
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
  const confirmed = confirmedFacesForDisplay(p.confirmed, photos)
  const reviewing = pendingReview !== null
  const pendingFaces = pendingReview && `${pendingReview.count} ${pendingReview.count === 1 ? 'face' : 'faces'}`
  const pendingDetections = pendingReview && `${pendingReview.count} ${pendingReview.count === 1 ? 'detection' : 'detections'}`
  const suggestedAction = pendingReview?.list === 'suggested' ? pendingReview.action : null
  const confirmedAction = pendingReview?.list === 'confirmed' ? pendingReview.action : null
  const notPerson = `Not ${p.name}`

  async function reviewFaces(action: FaceReviewAction, list: FaceReviewList, ids: number[]) {
    if (reviewing || !ids.length) return
    const count = ids.length
    const faces = `${count} ${count === 1 ? 'face' : 'faces'}`
    const operations = {
      confirm: { request: () => api.assign(ids, { person_id: pid }), message: `Confirmed ${faces}` },
      reject: { request: () => api.reject(ids), message: list === 'suggested'
        ? `Rejected ${faces}` : `Removed ${count} ${count === 1 ? 'confirmation' : 'confirmations'}` },
      ignore: { request: () => api.ignore(ids), message: `Ignored ${count} ${count === 1 ? 'detection' : 'detections'}` },
    }
    const { request, message } = operations[action]
    setPendingReview({ action, list, count })
    try {
      const result = await run(request, message)
      if (result !== undefined) await run(load)
    } finally {
      setPendingReview(null)
    }
  }

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
        <div className="row wrap">
          <FaceThumbnailSizeSlider size={thumbnailSize} onChange={setThumbnailSize} />
          <Link to={`/photos?person=${pid}`}><button>View photos</button></Link>
          <Link to={`/tree/${pid}`}><button>Family tree</button></Link>
        </div>
      </header>

      <section className="card person-form">
        <label>Name <input autoComplete="off" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
        <label title="Year this name came into use. Leave blank if it was always their name.">Name used from <input autoComplete="off" value={form.name_from_year} placeholder="year" inputMode="numeric"
          onChange={e => setForm({ ...form, name_from_year: e.target.value.replace(/\D/g, '') })} style={{ width: 80 }} /></label>
        <label>Born <input autoComplete="off" value={form.birth_year} placeholder="year" inputMode="numeric"
          onChange={e => setForm({ ...form, birth_year: e.target.value.replace(/\D/g, '') })} style={{ width: 80 }} /></label>
        <label>Died <input autoComplete="off" value={form.death_year} placeholder="year" inputMode="numeric"
          onChange={e => setForm({ ...form, death_year: e.target.value.replace(/\D/g, '') })} style={{ width: 80 }} /></label>
        <label className="grow">Notes <input autoComplete="off" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></label>
        <button className="primary" disabled={!dirty} onClick={save}>Save</button>
        <p className="muted small full">Birth/death years stop this person being suggested in photos dated outside their lifetime. <b>Notes</b> are for you only: they stay in the app and are not written to photo files.</p>
      </section>

      <FamilyCard person={p} onChanged={() => { refresh() }} />

      <PersonKeywordsCard key={JSON.stringify([p.id, p.keywords, p.keyword_ids])} person={p} onSaved={load} />
      <AliasCard key={p.id + ':' + JSON.stringify(p.aliases)} person={p} onSaved={load} />

      {p.suggested.length > 0 && (
        <section className="card">
          <div className="card-head">
            <h2>Suggested — is this {p.name}? <span className="muted">({p.suggested.length})</span></h2>
            <div className="row wrap">
              {p.suggested.some(f => f.people_keywords !== undefined) &&
                <PeopleKeywordsCheckbox checked={showPeopleKeywords} onChange={setShowPeopleKeywords} />}
              <button disabled={reviewing} onClick={() => setSelSugg(new Set(p.suggested.map(f => f.id)))}>Select all</button>
              <button onClick={() => setSelSugg(new Set())} disabled={reviewing || !selSugg.size}>Clear</button>
            </div>
          </div>
          <p className="muted small">Use <b>Ignore</b> for false detections and <b>Not {p.name}</b> for a different person. Then <b>Confirm</b> the correct suggestions.</p>
          <FaceGrid faces={p.suggested} selected={selSugg} onSelect={next => { if (!reviewing) setSelSugg(next) }} size={thumbnailSize}
            showPeopleKeywords={showPeopleKeywords} />
          <div className="action-bar">
            <span className="scope">{selSugg.size ? `${selSugg.size} selected` : `all ${p.suggested.length}`}</span>
            <button className="primary" disabled={reviewing} onClick={() => reviewFaces('confirm', 'suggested', suggIds)}>
              <span aria-live="polite">
                {suggestedAction === 'confirm' ? `Confirming ${pendingFaces}…` : 'Confirm'}
              </span>
            </button>
            <button disabled={reviewing || !selSugg.size} onClick={() => reviewFaces('reject', 'suggested', [...selSugg])}>
              <span aria-live="polite">{suggestedAction === 'reject' ? `Rejecting ${pendingFaces}…` : notPerson}</span>
            </button>
            <button className="danger" disabled={reviewing || !selSugg.size}
              onClick={() => reviewFaces('ignore', 'suggested', [...selSugg])} title="Ignore selected false detections">
              <span aria-live="polite">{suggestedAction === 'ignore' ? `Ignoring ${pendingDetections}…` : 'Ignore'}</span>
            </button>
          </div>
        </section>
      )}

      <section className="card">
        <div className="card-head">
          <h2>Confirmed <span className="muted">({confirmed.faces.length})</span></h2>
          <div className="row">
            <button disabled={reviewing} onClick={() => setSelConf(new Set(confirmed.faces.map(f => f.id)))}>Select all</button>
            <button onClick={() => setSelConf(new Set())} disabled={reviewing || !selConf.size}>Clear</button>
          </div>
        </div>
        <FaceGrid faces={confirmed.faces} alternateImages={confirmed.alternateImages}
          selected={selConf} onSelect={next => { if (!reviewing) setSelConf(next) }} showNames={false} size={thumbnailSize} />
        <div className="action-bar">
          <span className="scope">{selConf.size} selected</span>
          <button disabled={reviewing || !selConf.size} onClick={() => reviewFaces('reject', 'confirmed', [...selConf])}
            title="Not this person - won't be suggested as them again">
            <span aria-live="polite">{confirmedAction === 'reject' ? `Rejecting ${pendingFaces}…` : notPerson}</span>
          </button>
          <button className="danger" disabled={reviewing || !selConf.size} onClick={() => reviewFaces('ignore', 'confirmed', [...selConf])}
            title="Ignore selected false detections. Removing the last confirmation may remove an app-added person keyword.">
            <span aria-live="polite">{confirmedAction === 'ignore' ? `Ignoring ${pendingDetections}…` : 'Ignore'}</span>
          </button>
          <PersonPicker buttonLabel="Move to" placeholder="Move to person…" disabled={reviewing || !selConf.size}
            excludeId={pid} onPick={(who, label) => act(() => api.assign([...selConf], who), `Moved to ${label}`)} />
          <button disabled={reviewing || selConf.size !== 1}
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
