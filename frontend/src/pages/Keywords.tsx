import { KeywordSharingSettings } from '../components/VariationSettings'
import { useCallback, useEffect, useState } from 'react'
import { api, type Facet, type Keyword, type LibraryInfo } from '../api'

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

      <KeywordSharingSettings />
      <UnusedKeywords />
    </div>
  )
}
