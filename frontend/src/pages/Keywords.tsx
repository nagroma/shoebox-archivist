import { KeywordSharingSettings } from '../components/VariationSettings'
import { useCallback, useEffect, useState } from 'react'
import { api, type Facet, type Keyword, type LibraryInfo, type RegroupPlan, type UnmappedGroup } from '../api'

/** Family-name groups (Ashdown|JuliaAshdown) -> People|JuliaAshdown + Family|Ashdown. Preview, then one click. */
function FamilyGroups({ reload }: { reload: () => void }) {
  const [groups, setGroups] = useState<{ name: string; kind: string; keywords: number }[]>([])
  const [picked, setPicked] = useState<string[]>([])
  const [plan, setPlan] = useState<RegroupPlan | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(() => { api.regroupGroups().then(setGroups).catch(() => setGroups([])) }, [])
  useEffect(load, [load])
  if (!groups.length && !msg) return null

  async function preview(next: string[]) {
    setPicked(next); setPlan(null); setError(''); setMsg('')
    if (!next.length) return
    try { setPlan(await api.regroupPlan(next)) } catch (e) { setError((e as Error).message) }
  }

  async function apply() {
    setBusy(true); setError('')
    try {
      const r = await api.regroupApply(picked)
      setMsg(`Converted ${r.converted} keywords on ${r.photos} photos` + (r.failed ? ` (${r.failed} failed)` : '') +
        '. `pm strip` undoes it.')
      setPlan(null); setPicked([]); load(); await reload()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <section className="card">
      <h2>Family-name groups</h2>
      <p className="muted small">
        Groups like <code>Ashdown|JuliaAshdown</code> name people under a family. Tick the groups that are family names;
        each keyword becomes <code>People|JuliaAshdown</code> plus <code>Family|Ashdown</code> in the photo files.
        Nothing changes until you confirm the preview, and <code>pm strip</code> puts the old keywords back.
      </p>
      <div className="row">
        {groups.map(g => (
          <label key={g.name} className="row small">
            <input type="checkbox" checked={picked.includes(g.name)}
              onChange={e => preview(e.target.checked ? [...picked, g.name] : picked.filter(x => x !== g.name))} />
            {g.name} <span className="muted">({g.keywords})</span>
          </label>
        ))}
      </div>
      {plan && (
        <>
          {plan.groups.map(g => (
            <details key={g.group} open={plan.groups.length === 1}>
              <summary>{g.group} &rarr; {plan.people_category}|&lt;name&gt; + {g.family_keyword}
                {' '}<span className="muted">({g.people.length} people)</span></summary>
              <table className="facets"><tbody>
                {g.people.map(p => (
                  <tr key={p.name}><td>{p.display}</td><td className="muted">{p.photos} photos</td>
                    <td className="muted">{p.merges_existing ? `joins existing ${p.to}` : p.to}</td></tr>
                ))}
              </tbody></table>
              {g.skipped_deeper > 0 && <p className="muted small">{g.skipped_deeper} deeper keywords are left alone.</p>}
            </details>
          ))}
          <div className="row">
            <span className="grow muted small">{plan.keywords} keywords on {plan.photos} photos will change.</span>
            <button className="primary" disabled={busy} onClick={apply}>
              {busy ? 'Converting…' : `Convert ${plan.photos} photos`}
            </button>
          </div>
        </>
      )}
      {msg && <p className="hint">{msg}</p>}
      {error && <p className="hint error">{error}</p>}
    </section>
  )
}

/** Keyword groups that arrived with later photos and match no facet: add as a facet, or leave. */
function NewGroups({ reload, kinds }: { reload: () => void; kinds: string[] }) {
  const [groups, setGroups] = useState<UnmappedGroup[]>([])
  const [kind, setKind] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  useEffect(() => { api.unmappedGroups().then(setGroups).catch(() => setGroups([])) }, [])
  if (!groups.length) return null

  async function resolve(g: UnmappedGroup, action: 'facet' | 'leave') {
    setError('')
    try {
      setGroups(await api.resolveGroup(g.name, action, kind[g.name] ?? (g.looks_like_people ? 'person' : g.kind)))
      if (action === 'facet') await reload()
    } catch (e) { setError((e as Error).message) }
  }

  return (
    <section className="card">
      <h2>New keyword groups</h2>
      <p className="muted small">
        These groups came in with newly added photos and are not facets yet. Adding one only tells the app what
        it is; the keywords in your files are not changed. Leaving one alone hides it here.
      </p>
      <table className="facets">
        <tbody>
          {groups.map(g => (
            <tr key={g.name}>
              <td><strong>{g.name}</strong> <span className="muted small">({g.keywords} keywords, {g.photos} photos)</span>
                <div className="muted small">{g.samples.join(', ')}</div></td>
              <td>
                <select value={kind[g.name] ?? (g.looks_like_people ? 'person' : g.kind)}
                  onChange={e => setKind({ ...kind, [g.name]: e.target.value })}>
                  {kinds.map(k => <option key={k} value={k}>{k}</option>)}
                </select>
              </td>
              <td className="row">
                <button className="primary" onClick={() => resolve(g, 'facet')}>Add as facet</button>
                <button className="ghost" onClick={() => resolve(g, 'leave')}>Leave</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {error && <p className="hint error">{error}</p>}
    </section>
  )
}

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

export function KeywordsPage({ info, reload }: { info: LibraryInfo; reload: () => void }) {
  const [facets, setFacets] = useState<(Facet & { keywords?: number })[]>(info.facets ?? [])
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  const dirty = JSON.stringify(facets.map(f => [f.name, f.kind])) !==
    JSON.stringify((info.facets ?? []).map(f => [f.name, f.kind]))

  async function save() {
    setError(''); setMsg('')
    try {
      await api.saveFacets(facets.map(f => ({ name: f.name, kind: f.kind })))
      setMsg('Saved'); reload()
    } catch (e) { setError((e as Error).message) }
  }

  async function refreshFacets() {
    setFacets((await api.library()).facets ?? [])
    reload()
  }

  return (
    <div className="page settings">
      <header className="page-head"><h1>Keywords</h1></header>
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
                <td><input autoComplete="off" value={f.name} disabled={!!f.keywords}
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

      {!dirty && <>
        <NewGroups reload={refreshFacets} kinds={info.kinds} />
        <FamilyGroups reload={refreshFacets} />
      </>}
      <KeywordSharingSettings />
      <UnusedKeywords />
    </div>
  )
}
