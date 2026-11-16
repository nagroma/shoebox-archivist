import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Candidate, type Candidates, type Cluster, type Face, type FaceReview, type FaceViewPreference, type PersonRef } from '../api'
import { FaceGrid, FaceThumbnailSizeSlider, PeopleKeywordsCheckbox } from '../components/FaceGrid'
import { useFaceThumbnailSize } from '../faceThumbnailSize'
import { PersonPicker } from '../components/PersonPicker'
import { useAction, useApp } from '../state'

type FaceSort = 'review' | 'name'

export function ClustersPage() {
  const { refresh, stats, showPeopleKeywords, setShowPeopleKeywords } = useApp()
  const run = useAction()
  const [review, setReview] = useState<FaceReview | null>(null)
  const [unclusteredSort, setUnclusteredSort] = useState<FaceSort>('review')
  const [showIgnored, setShowIgnored] = useState(false)
  const [thumbnailSize, setThumbnailSize] = useFaceThumbnailSize()
  const [minSize, setMinSize] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [saving, setSaving] = useState(false)
  const changing = useRef(false)
  const request = useRef(0)

  const load = useCallback(async () => {
    if (changing.current) return
    const id = ++request.current
    const result = await run(api.facesReview)
    if (id === request.current && result) setReview(result)
    refresh()
  }, [refresh, run])

  useEffect(() => { load() }, [load, stats?.db_token])
  useEffect(() => { api.settings().then(s => setMinSize(m => m ?? s.values.min_cluster_size), () => {}) }, [])
  useEffect(() => {
    window.addEventListener('library-changed', load)
    return () => window.removeEventListener('library-changed', load)
  }, [load])

  async function saveView(preference: FaceViewPreference) {
    if (changing.current) return
    changing.current = true
    ++request.current
    setSaving(true)
    const result = await run(() => api.saveFacesView(preference))
    if (result) setReview({ ...result, candidates: { ...result.candidates, preselect: false } })
    changing.current = false
    setSaving(false)
  }

  async function recluster() {
    setBusy(true)
    const r = await run(() => api.recluster(minSize ?? undefined))
    if (r) await load()
    setBusy(false)
  }

  if (!review) return <p className="muted pad">Loading…</p>

  const { view, clusters, candidates, ignored } = review
  const preference = { preferred: view.preferred, also_show: view.also_show }
  const versionLabel = (v: { suffix: string; label: string }) => `${v.label} (${v.suffix || 'no suffix'})`
  const defaultVersion = view.front_types.find(t => t.suffix === view.default_preferred)
  const named = clusters.filter(c => c.cluster_id >= 0)
  const loose = clusters.find(c => c.cluster_id === -1)

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Unnamed faces</h1>
          <p className="muted">
            Select faces that don't belong and use <b>Remove from cluster</b>, then name the rest.
            Shift+click selects a range. Double-click a face (or 🔍) to see the whole photo.
          </p>
        </div>
        <div className="row wrap">
          <FaceThumbnailSizeSlider size={thumbnailSize} onChange={setThumbnailSize} />
          {clusters.some(c => c.faces.some(f => f.status === 'suggested' && f.people_keywords !== undefined)) &&
            <PeopleKeywordsCheckbox checked={showPeopleKeywords} onChange={setShowPeopleKeywords} />}
          <label className="muted" title="Minimum number of faces used to form a cluster from the selected scan variants (default in Settings)">
            Minimum cluster size <input autoComplete="off" type="number" min={2} max={20} value={minSize ?? ''}
              onChange={e => setMinSize(Number(e.target.value))} style={{ width: 52 }} />
          </label>
          <button onClick={recluster} disabled={busy || saving}>{busy ? 'Clustering…' : 'Re-cluster'}</button>
        </div>
      </header>

      <section className="card">
        <h2>Scan variants</h2>
        <fieldset disabled={saving || busy} className="face-version-options">
          <label className="row wrap">Use instead of the original when available
            <select value={view.preferred === null ? 'default' : `suffix:${view.preferred}`} onChange={e =>
              saveView({ ...preference, preferred: e.target.value === 'default' ? null : e.target.value.slice(7) })}>
              <option value="default">Library default: {defaultVersion ? versionLabel(defaultVersion) : 'Original front'}</option>
              <option value="suffix:">None — use original</option>
              {view.front_types.map(t => <option key={t.suffix} value={`suffix:${t.suffix}`}>{versionLabel(t)}</option>)}
            </select>
          </label>
          {view.available.length > 0 && <fieldset className="face-version-extras">
            <legend>Also show</legend>
            <div className="row wrap">{view.available.map(t => <label key={t.suffix} className="row small">
              <input type="checkbox" checked={view.also_show.includes(t.suffix)} onChange={e => saveView({
                ...preference, also_show: e.target.checked ? [...view.also_show, t.suffix] : view.also_show.filter(s => s !== t.suffix),
              })} />{versionLabel(t)}
            </label>)}</div>
          </fieldset>}
        </fieldset>
        <p className="muted small">Uses the original only when the chosen replacement file is missing.
          {view.fallback > 0 && ` Using originals for ${view.fallback} scan ${view.fallback === 1 ? 'family' : 'families'}.`}
          {' '}Re-cluster uses only the selected scan variants. Recognition and keyword sharing keep their own settings.</p>
        {view.unscanned > 0 && <p className="muted small">{view.unscanned} included {view.unscanned === 1 ? 'front has' : 'fronts have'} not been scanned for faces.</p>}
      </section>

      {saving ? <p className="muted" role="status">Updating displayed scan variants…</p> : <>
      {candidates && candidates.faces.length > 0 && <CandidatesCard key={candidates.faces.map(f => f.id).join(',')} data={candidates} onChanged={load} thumbnailSize={thumbnailSize} />}

      {named.length === 0 && !loose && !candidates?.faces.length && <p className="empty">No unnamed faces in these scan variants.</p>}

      {named.map(c => <ClusterCard key={`${c.cluster_id}:${c.faces.map(f => f.id).join(',')}`} cluster={c} onChanged={load}
        thumbnailSize={thumbnailSize} showPeopleKeywords={showPeopleKeywords} />)}
      {loose && <ClusterCard key={loose.faces.map(f => f.id).join(',')} cluster={loose} onChanged={load} thumbnailSize={thumbnailSize}
        showPeopleKeywords={showPeopleKeywords} sort={unclusteredSort} onSortChange={setUnclusteredSort} />}

      <section className="card">
        <div className="card-head">
          <h2>Ignored faces <span className="muted">({ignored.length})</span></h2>
          <button onClick={() => setShowIgnored(s => !s)}>{showIgnored ? 'Hide' : 'Show'}</button>
        </div>
        {showIgnored && <IgnoredGrid key={ignored.map(f => f.id).join(',')} faces={ignored} onChanged={load} thumbnailSize={thumbnailSize} />}
      </section>
      </>}
    </div>
  )
}

const LIKELY = {
  face: ['likely face', 'Looks like faces you marked as Face'],
  not_face: ['likely not', 'Looks like things you marked as Not a face'],
} as const

/** Thorough-scan finds that may not be faces at all (wheels, lamps, hands…).
 *  Sorted most face-like first using earlier decisions; likely non-faces are pre-selected. */
function CandidatesCard({ data, onChanged, thumbnailSize }: { data: Candidates; onChanged: () => void; thumbnailSize: number }) {
  const run = useAction()
  const { faces, learning } = data
  const likelyNot = faces.filter(f => f.likely === 'not_face').map(f => f.id)
  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(data.preselect ? likelyNot : []))
  const targets = selected.size ? [...selected] : faces.map(f => f.id)
  const what = selected.size ? `${selected.size} selected` : `all ${faces.length}`
  const decided = learning.faces + learning.non_faces

  async function act(fn: () => Promise<unknown>, msg: string) {
    if (await run(fn, msg)) { setSelected(new Set()); onChanged() }
  }

  return (
    <section className="card candidates">
      <div className="card-head">
        <h2>Possible faces <span className="muted">({faces.length})</span></h2>
      </div>
      <p className="muted small">
        Found by the thorough scan (tilted, small or faded). Many are not faces. Select the real ones and click
        <b> Face</b>, or select the rest and click <b>Not a face</b>. Double-click or 🔍 to see the whole photo.
      </p>
      <p className="muted small">
        {learning.active
          ? <>Sorted most face-like first, learning from {decided} faces and {learning.non_faces} “not a face” decisions.
              {data.preselect && likelyNot.length > 0 && <> The {likelyNot.length} marked <i>likely not</i> are pre-selected: check them, then click <b>Not a face</b>.</>}
              {' '}A guess only; nothing is hidden automatically.</>
          : <>Sorting starts after {learning.non_faces < 5 ? `${5 - learning.non_faces} more “not a face” decision(s)` : 'a few more confirmed faces'}.</>}
      </p>
      <FaceGrid faces={faces} selected={selected} onSelect={setSelected} showNames={false} size={thumbnailSize}
        badge={f => {
          const l = (f as Candidate).likely
          return l ? <span className={`likely ${l}`} title={LIKELY[l][1]}>{LIKELY[l][0]}</span> : null
        }} />
      <div className="row">
        <span className="muted small">{what}</span>
        {likelyNot.length > 0 && <button onClick={() => setSelected(new Set(likelyNot))}>Select likely not</button>}
        <button onClick={() => setSelected(new Set())} disabled={selected.size === 0}>Clear</button>
        <button className="primary" onClick={() => act(() => api.verify(targets), `${targets.length} confirmed as faces`)}>
          ✓ Face</button>
        <button onClick={() => act(() => api.ignore(targets), `${targets.length} hidden`)}>✗ Not a face</button>
      </div>
    </section>
  )
}

function ClusterCard({ cluster, onChanged, thumbnailSize, showPeopleKeywords, sort = 'review', onSortChange }: {
  cluster: Cluster; onChanged: () => void; thumbnailSize: number; showPeopleKeywords: boolean
  sort?: FaceSort; onSortChange?: (sort: FaceSort) => void
}) {
  const run = useAction()
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [accepting, setAccepting] = useState(false)
  const isLoose = cluster.cluster_id === -1
  const guessedName = (f: Face) => f.status === 'suggested' ? f.person_name ?? '' : ''
  const faces = isLoose && sort === 'name' ? [...cluster.faces].sort((a, b) => {
    const first = guessedName(a), second = guessedName(b)
    return Number(!first) - Number(!second) || first.localeCompare(second, undefined, { sensitivity: 'base' })
  }) : cluster.faces

  // The cluster summary describes all faces, but the name field follows the selection.
  const suggestions = faces.filter(f => f.status === 'suggested' && f.person_name && f.person_id !== null)
  const counts = new Map<number, { face: Face; count: number }>()
  for (const f of suggestions) {
    const id = f.person_id!
    counts.set(id, { face: f, count: (counts.get(id)?.count ?? 0) + 1 })
  }
  const top = [...counts.values()].sort((a, b) => b.count - a.count)[0]
  const selectedSuggestions = suggestions.filter(f => selected.has(f.id))
  const allSelectedHaveGuesses = selected.size > 0 && selectedSuggestions.length === selected.size
  const mixed = new Set(selectedSuggestions.map(f => f.person_id)).size > 1
  const suggestion = selected.size ? (mixed ? undefined : selectedSuggestions[0]) : top?.face

  // Act on the selection; in a real cluster, an empty selection means "the whole cluster".
  const targets = selected.size > 0 ? [...selected] : isLoose ? [] : faces.map(f => f.id)
  const scope = selected.size > 0 ? `${selected.size} selected` : isLoose ? 'select faces first' : `all ${faces.length}`

  async function act(fn: () => Promise<unknown>, msg: string) {
    const r = await run(fn, msg)
    if (r !== undefined) { setSelected(new Set()); onChanged() }
  }

  const assign = (who: PersonRef, label: string) =>
    act(() => api.assign(targets, who), `Named ${targets.length} face(s) ${label}`)

  async function acceptGuesses() {
    if (!allSelectedHaveGuesses || accepting) return
    setAccepting(true)
    const guesses = selectedSuggestions.map(f => ({ face_id: f.id, person_id: f.person_id! }))
    const result = await run(() => api.acceptGuesses(guesses), `Accepted ${guesses.length} ${guesses.length === 1 ? 'guess' : 'guesses'}`)
    if (result) setSelected(new Set())
    setAccepting(false)
    onChanged()
  }

  return (
    <section className="card">
      <div className="card-head">
        <h2>
          {isLoose ? 'Unclustered' : `Cluster ${cluster.cluster_id}`}{' '}
          <span className="muted">({faces.length} faces{top ? ` · mostly suggested as ${top.face.person_name} (${top.count})` : ''})</span>
        </h2>
        <div className="row wrap">
          {isLoose && onSortChange && <label className="row small">Sort unclustered faces
            <select value={sort} onChange={e => onSortChange(e.target.value as FaceSort)}>
              <option value="review">Review order</option>
              <option value="name">Suggested name</option>
            </select>
          </label>}
          <button onClick={() => setSelected(new Set(faces.map(f => f.id)))}>Select all</button>
          <button onClick={() => setSelected(new Set())} disabled={selected.size === 0}>Clear</button>
        </div>
      </div>

      <FaceGrid key={sort} faces={faces} selected={selected} onSelect={setSelected} size={thumbnailSize}
        showPeopleKeywords={showPeopleKeywords} />

      <div className="action-bar">
        <span className="scope">{scope}</span>
        {isLoose && <button className="primary" disabled={!allSelectedHaveGuesses || accepting}
          title="Confirm each selected face under its own suggested name"
          onClick={acceptGuesses}>
          {accepting ? 'Accepting…' : selected.size === 0 ? 'Accept guesses' :
            selected.size === 1 ? 'Accept 1 guess' : `Accept ${selected.size} guesses`}
        </button>}
        <PersonPicker
          key={JSON.stringify([...selected].sort((a, b) => a - b))}
          initial={suggestion?.person_name ?? ''}
          initialPersonId={suggestion?.person_id ?? undefined}
          placeholder="Who is this?"
          buttonLabel="Name"
          disabled={targets.length === 0 || accepting}
          onPick={assign}
        />
        {!isLoose && (
          <button disabled={selected.size === 0}
            onClick={() => act(() => api.removeFromCluster([...selected]), `Moved ${selected.size} to unclustered`)}>
            Remove from cluster
          </button>
        )}
        {selectedSuggestions.length > 0 && !mixed && <button disabled={accepting}
          onClick={() => act(() => api.reject(selectedSuggestions.map(f => f.id)), 'Suggestion rejected')}
          title="Reject this suggestion for the selected faces that have it">
          Not {selectedSuggestions[0].person_name}
        </button>}
        {mixed && <span className="muted small">{isLoose && allSelectedHaveGuesses
          ? 'Accept keeps each guess. Name applies one name to the selection.'
          : 'Different guesses selected. Choose a name to apply to all selected faces.'}</span>}
        {isLoose && selected.size > 0 && !allSelectedHaveGuesses &&
          <span className="muted small">Select only faces with guesses to accept them together.</span>}
        <button className="danger" disabled={targets.length === 0 || accepting}
          onClick={() => act(() => api.ignore(targets), `Ignored ${targets.length} face(s)`)}
          title="Strangers, statues, paintings, bad detections">
          Ignore
        </button>
      </div>
    </section>
  )
}

function IgnoredGrid({ faces, onChanged, thumbnailSize }: { faces: Face[]; onChanged: () => void; thumbnailSize: number }) {
  const run = useAction()
  const [selected, setSelected] = useState<Set<number>>(new Set())
  if (faces.length === 0) return <p className="muted">Nothing ignored.</p>
  return (
    <>
      <FaceGrid faces={faces} selected={selected} onSelect={setSelected} showNames={false} size={thumbnailSize} />
      <div className="action-bar">
        <button disabled={selected.size === 0} onClick={async () => {
          if (await run(() => api.unignore([...selected]), 'Restored')) { setSelected(new Set()); onChanged() }
        }}>Restore selected</button>
      </div>
    </>
  )
}
