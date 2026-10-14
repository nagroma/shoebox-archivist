import { useCallback, useEffect, useState } from 'react'
import { api, type Candidate, type Candidates, type Cluster, type Face, type MatchFace, type MatchGroup, type PersonRef } from '../api'
import { FaceGrid } from '../components/FaceGrid'
import { PersonPicker } from '../components/PersonPicker'
import { useAction, useApp } from '../state'

export function ClustersPage() {
  const { refresh } = useApp()
  const run = useAction()
  const [clusters, setClusters] = useState<Cluster[] | null>(null)
  const [showIgnored, setShowIgnored] = useState(false)
  const [ignored, setIgnored] = useState<Face[]>([])
  const [candidates, setCandidates] = useState<Candidates | null>(null)
  const [matches, setMatches] = useState<MatchGroup[]>([])
  const [minSize, setMinSize] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    const [c, ig, cand, m] = await Promise.all([api.clusters(), api.ignored(), api.candidates(), api.matches()])
    setClusters(c)
    setMatches(m)
    setIgnored(ig)
    setCandidates(cand)
    refresh()
  }, [refresh])

  useEffect(() => { load() }, [load])
  useEffect(() => { api.settings().then(s => setMinSize(m => m ?? s.values.min_cluster_size), () => {}) }, [])
  useEffect(() => {
    window.addEventListener('library-changed', load)
    return () => window.removeEventListener('library-changed', load)
  }, [load])

  async function recluster() {
    setBusy(true)
    const r = await run(() => api.recluster(minSize ?? undefined))
    if (r) await load()
    setBusy(false)
  }

  if (!clusters) return <p className="muted pad">Loading…</p>

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
        <div className="row">
          <label className="muted" title="Smallest group of faces treated as a cluster (default in Settings)">
            Min size <input type="number" min={2} max={20} value={minSize ?? ''}
              onChange={e => setMinSize(Number(e.target.value))} style={{ width: 52 }} />
          </label>
          <button onClick={recluster} disabled={busy}>{busy ? 'Clustering…' : 'Re-cluster'}</button>
        </div>
      </header>

      {candidates && candidates.faces.length > 0 && <CandidatesCard data={candidates} onChanged={load} />}

      {matches.map(g => <MatchCard key={g.person_id} group={g} onChanged={load} />)}

      {named.length === 0 && !loose && matches.length === 0 && !candidates?.faces.length && <p className="empty">No unnamed faces. 🎉</p>}

      {named.map(c => <ClusterCard key={c.cluster_id} cluster={c} onChanged={load} />)}
      {loose && <ClusterCard cluster={loose} onChanged={load} />}

      <section className="card">
        <div className="card-head">
          <h2>Ignored faces <span className="muted">({ignored.length})</span></h2>
          <button onClick={() => setShowIgnored(s => !s)}>{showIgnored ? 'Hide' : 'Show'}</button>
        </div>
        {showIgnored && <IgnoredGrid faces={ignored} onChanged={load} />}
      </section>
    </div>
  )
}

/** Unnamed faces that look like someone already named, strongest match first. */
function MatchCard({ group, onChanged }: { group: MatchGroup; onChanged: () => void }) {
  const run = useAction()
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const seeds = group.faces.filter(f => f.seed).length
  const ids = [...selected]

  async function act(fn: () => Promise<unknown>, msg: string) {
    if (await run(fn, msg)) { setSelected(new Set()); onChanged() }
  }

  return (
    <section className="card">
      <div className="card-head">
        <h2>
          {group.guess ? `Is this ${group.name}?` : `Likely ${group.name}`}{' '}
          <span className="muted">
            ({group.faces.length} faces{group.guess
              ? ` · none confirmed yet; the first ${seeds} are guesses from the photo's keywords`
              : ` · ${group.confirmed} confirmed`})
          </span>
        </h2>
        <div className="row">
          <button onClick={() => setSelected(new Set(group.faces.map(f => f.id)))}>Select all</button>
          <button onClick={() => setSelected(new Set())} disabled={selected.size === 0}>Clear</button>
        </div>
      </div>
      {group.guess && (
        <p className="muted small">
          Check the guessed faces first. Confirm the ones that really are {group.name}; once one is confirmed the
          rest are compared with it and this list gets more reliable.
        </p>
      )}
      <FaceGrid faces={group.faces} selected={selected} onSelect={setSelected} showNames={false}
        badge={f => {
          const m = f as MatchFace
          return m.seed
            ? <span className="likely not_face" title="Guessed from the photo's keywords, not by looks">guess</span>
            : m.similarity != null ? <span className="likely face" title="Similarity to the named faces">{Math.round(m.similarity * 100)}%</span> : null
        }} />
      <div className="action-bar">
        <span className="scope">{selected.size ? `${selected.size} selected` : 'select faces first'}</span>
        <button className="primary" disabled={!ids.length}
          onClick={() => act(() => api.assign(ids, { person_id: group.person_id }), `Named ${ids.length} face(s) ${group.name}`)}>
          Confirm as {group.name}
        </button>
        <button disabled={!ids.length}
          onClick={() => act(() => api.notPerson(ids, group.person_id), `Not ${group.name}`)}>
          Not {group.name}
        </button>
      </div>
    </section>
  )
}

const LIKELY = {
  face: ['likely face', 'Looks like faces you marked as Face'],
  not_face: ['likely not', 'Looks like things you marked as Not a face'],
} as const

/** Thorough-scan finds that may not be faces at all (wheels, lamps, hands…).
 *  Sorted most face-like first using earlier decisions; likely non-faces are pre-selected. */
function CandidatesCard({ data, onChanged }: { data: Candidates; onChanged: () => void }) {
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
      <FaceGrid faces={faces} selected={selected} onSelect={setSelected} showNames={false} size={96}
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

function ClusterCard({ cluster, onChanged }: { cluster: Cluster; onChanged: () => void }) {
  const run = useAction()
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const isLoose = cluster.cluster_id === -1
  const faces = cluster.faces

  // Most common suggestion in this cluster, used to pre-fill the name box.
  const counts = new Map<string, number>()
  for (const f of faces) if (f.status === 'suggested' && f.person_name)
    counts.set(f.person_name, (counts.get(f.person_name) ?? 0) + 1)
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]

  // Act on the selection; in a real cluster, an empty selection means "the whole cluster".
  const targets = selected.size > 0 ? [...selected] : isLoose ? [] : faces.map(f => f.id)
  const scope = selected.size > 0 ? `${selected.size} selected` : isLoose ? 'select faces first' : `all ${faces.length}`

  async function act(fn: () => Promise<unknown>, msg: string) {
    const r = await run(fn, msg)
    if (r !== undefined) { setSelected(new Set()); onChanged() }
  }

  const assign = (who: PersonRef, label: string) =>
    act(() => api.assign(targets, who), `Named ${targets.length} face(s) ${label}`)

  return (
    <section className="card">
      <div className="card-head">
        <h2>
          {isLoose ? 'Unclustered' : `Cluster ${cluster.cluster_id}`}{' '}
          <span className="muted">({faces.length} faces{top ? ` · mostly suggested as ${top[0]} (${top[1]})` : ''})</span>
        </h2>
        <div className="row">
          <button onClick={() => setSelected(new Set(faces.map(f => f.id)))}>Select all</button>
          <button onClick={() => setSelected(new Set())} disabled={selected.size === 0}>Clear</button>
        </div>
      </div>

      <FaceGrid faces={faces} selected={selected} onSelect={setSelected} />

      <div className="action-bar">
        <span className="scope">{scope}</span>
        <PersonPicker
          key={top?.[0] ?? ''}
          initial={top?.[0] ?? ''}
          placeholder="Who is this?"
          buttonLabel="Name"
          disabled={targets.length === 0}
          onPick={assign}
        />
        {!isLoose && (
          <button disabled={selected.size === 0}
            onClick={() => act(() => api.removeFromCluster([...selected]), `Moved ${selected.size} to unclustered`)}>
            Remove from cluster
          </button>
        )}
        {top && <button disabled={selected.size === 0 || ![...selected].some(id => faces.find(f => f.id === id)?.status === 'suggested')}
          onClick={() => act(() => api.reject([...selected]), 'Suggestion rejected')}
          title="This is not the suggested person">
          Not {top[0]}
        </button>}
        <button className="danger" disabled={targets.length === 0}
          onClick={() => act(() => api.ignore(targets), `Ignored ${targets.length} face(s)`)}
          title="Strangers, statues, paintings, bad detections">
          Ignore
        </button>
      </div>
    </section>
  )
}

function IgnoredGrid({ faces, onChanged }: { faces: Face[]; onChanged: () => void }) {
  const run = useAction()
  const [selected, setSelected] = useState<Set<number>>(new Set())
  if (faces.length === 0) return <p className="muted">Nothing ignored.</p>
  return (
    <>
      <FaceGrid faces={faces} selected={selected} onSelect={setSelected} showNames={false} size={88} />
      <div className="action-bar">
        <button disabled={selected.size === 0} onClick={async () => {
          if (await run(() => api.unignore([...selected]), 'Restored')) { setSelected(new Set()); onChanged() }
        }}>Restore selected</button>
      </div>
    </>
  )
}
