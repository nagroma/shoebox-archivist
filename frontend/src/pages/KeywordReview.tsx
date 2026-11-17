import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type ExclusiveConflict, type KeywordReview, type KeywordScope, type VariationType } from '../api'
import { useAction, useApp } from '../state'
import { ScopeSelector } from '../components/KeywordScope'

function ChooseScope({ photo, keyword, path, types, onSaved }: { photo: number; keyword: number; path: string; types: VariationType[]; onSaved: () => void }) {
  const run = useAction()
  const [scope, setScope] = useState<KeywordScope>({ mode: 'all', suffixes: [] })
  const [global, setGlobal] = useState(true)
  async function save() {
    const result = await run(async () => {
      if (!global) return api.photoKeywordScope(photo, keyword, scope)
      const settings = await api.sharing()
      return api.saveSharing({ ...settings, rules: [...settings.rules.filter(r => !(r.target === 'keyword' && r.path === path)),
        { target: 'keyword', path, scope }] })
    })
    if (result) onSaved()
  }
  return <div className="row wrap"><ScopeSelector value={scope} types={types} allowAll onChange={setScope} />
    <label className="row"><input type="checkbox" checked={global} onChange={e => setGlobal(e.target.checked)} />Use this keyword rule throughout the library</label>
    <button disabled={scope.mode === 'ask'} onClick={save}>{global ? 'Save keyword rule' : "Save scope for this scan family"}</button></div>
}

function KeepOne({ conflict, onSaved }: { conflict: ExclusiveConflict; onSaved: (r: KeywordReview) => void }) {
  const run = useAction()
  const [keep, setKeep] = useState('')
  const [busy, setBusy] = useState(false)
  async function apply() {
    const chosen = conflict.variants.find(v => String(v.image_id) === keep)
    if (!chosen || !confirm(`Keep "${conflict.keyword}" on ${chosen.path} only? This removes it from the other listed files and clears conflicting keep-present exceptions.`)) return
    setBusy(true)
    const result = await run(() => api.keepKeywordOnOneVariant(conflict.id, chosen.image_id))
    if (result) onSaved(result)
    setBusy(false)
  }
  return <div className="review-difference">
    <code>{conflict.keyword}</code> · <Link to={`/photos/${conflict.photo_id}`}>View scan family</Link>
    <ul>{conflict.variants.map(v => <li key={v.image_id}><code>{v.path}</code> · {v.present ? 'Present' : 'Keep-present exception'}</li>)}</ul>
    {conflict.blocked ? <p className="hint error">One or more scan variants could not be read. Check again before choosing.</p> :
      <div className="row wrap"><label>Keep on <select value={keep} onChange={e => setKeep(e.target.value)}>
        <option value="">Choose a scan variant…</option>
        {conflict.variants.map(v => <option key={v.image_id} value={v.image_id}>{v.variation} — {v.path}</option>)}
      </select></label><button disabled={!keep || busy} onClick={apply}>Keep on this scan variant only</button></div>}
  </div>
}

export function KeywordReviewPage() {
  const run = useAction()
  const { refresh } = useApp()
  const [review, setReview] = useState<KeywordReview | null>(null)
  const [types, setTypes] = useState<VariationType[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [checking, setChecking] = useState(false)
  const [checkStatus, setCheckStatus] = useState<{ text: string; error?: boolean } | null>(null)
  const [message, setMessage] = useState('')
  const [filter, setFilter] = useState('')
  const [limit, setLimit] = useState(100)
  const load = useCallback(async (showResult = false) => {
    setChecking(true)
    setCheckStatus(null)
    try {
      const result = await run(api.keywordReview)
      if (!result) {
        setCheckStatus({ text: 'The check could not finish. Try Check again.', error: true })
        return
      }
      setReview(result)
      setSelected(new Set())
      if (showResult) {
        const differences = result.differences.length + result.conflicts.length
        const items = [
          differences ? `${differences} keyword ${differences === 1 ? 'difference' : 'differences'}` : 'no keyword differences',
          result.choices.length ? `${result.choices.length} scope ${result.choices.length === 1 ? 'choice' : 'choices'}` : '',
          result.errors.length ? `${result.errors.length} unreadable ${result.errors.length === 1 ? 'file' : 'files'}` : '',
          result.grouping_issues.length ? `${result.grouping_issues.length} scan ${result.grouping_issues.length === 1 ? 'variant needs' : 'variants need'} review` : '',
        ].filter(Boolean)
        const checked = result.photos_checked
        const summary = checked === undefined
          ? 'Check complete.'
          : `Checked ${checked} indexed ${checked === 1 ? 'photo' : 'photos'}.`
        setCheckStatus({ text: `${summary} Found ${items.join(', ')}.` })
      }
      await run(refresh)
    } finally {
      setChecking(false)
    }
  }, [run, refresh])
  useEffect(() => { load(true); api.variations().then(c => setTypes(c.types)) }, [load])
  if (!review) return checkStatus?.error
    ? <div className="page"><p className="hint error" role="status">{checkStatus.text}</p>
      <button disabled={checking} onClick={() => load(true)}>Check again</button></div>
    : <p className="muted pad" role="status">Checking keyword differences…</p>
  const r = review
  const rows = r.differences.filter(d => `${d.path} ${d.keyword}`.toLowerCase().includes(filter.toLowerCase()))
  async function apply() {
    const ownerRemovals = r.differences.filter(d => selected.has(d.id) && d.action === 'remove' && d.source === 'file')
    if (ownerRemovals.length && !confirm(`Remove ${ownerRemovals.length} selected keyword(s) that were already in the original files? Prior values will be saved for undo.`)) return
    setBusy(true)
    const result = await run(() => api.applyKeywordReview([...selected].map(id => ({ id,
      allow_owner_removal: ownerRemovals.some(d => d.id === id) }))))
    if (result) {
      setReview(result.review); setSelected(new Set()); await refresh()
      setMessage(`${result.completed.length} file changes applied.${result.errors.length ? ' Errors: ' + result.errors.map(e => e.error).join('; ') : ''}`)
    }
    setBusy(false)
  }
  return <div className="page">
    <header className="page-head"><h1>Keyword differences</h1><Link to="/keywords">Back to Keywords</Link>
      <button disabled={busy || checking} onClick={() => load(true)}>{checking ? 'Checking…' : 'Check again'}</button></header>
    <div role="status">{checking ? <p className="muted small">Checking keyword differences…</p> :
      checkStatus && <p className={checkStatus.error ? 'hint error' : 'hint'}>{checkStatus.text}</p>}</div>
    <p>Imports and scans check affected scan families against your current preferences. This review changes no photo metadata until you apply selected fixes.
      Deliberate exceptions are preserved.</p>
    {r.grouping_issues.length > 0 && <section className="card"><h2>Scan variants need review ({r.grouping_issues.length})</h2>
      <p><Link to="/library">Adjust filename conventions on Library, then preview scan families again.</Link> These files remain separate.</p>
      {r.grouping_issues.map(i => <p key={i.image_id}><code>{i.path}</code> · {i.issue}</p>)}
    </section>}
    {r.errors.map(e => <p className="hint error" key={e.image_id}><code>{e.path}</code>: {e.error}</p>)}
    {r.choices.length > 0 && <section className="card"><h2>Choose where these keywords apply ({r.choices.length})</h2>
      {[...new Map(r.choices.map(c => [c.keyword_id, c])).values()].map(c => <div className="scope-rule" key={`${c.photo_id}:${c.keyword_id}`}>
        <code>{c.keyword}</code> · {r.choices.filter(x => x.keyword_id === c.keyword_id).length} scan families need a choice.<br />
        <Link to={`/photos/${c.photo_id}`}>Example: {c.path}</Link>
        <ChooseScope photo={c.photo_id} keyword={c.keyword_id} path={c.keyword} types={types} onSaved={load} />
      </div>)}
    </section>}
    {r.conflicts.length > 0 && <section className="card">
      <h2>More than one scan variant ({r.conflicts.length})</h2>
      <p>These keywords are limited to one scan variant per family. Choose which variant to keep.</p>
      {r.conflicts.map(c => <KeepOne key={c.id} conflict={c} onSaved={next => {
        setReview(next); setSelected(new Set()); refresh()
      }} />)}
    </section>}
    <section className="card"><h2>Differences ({r.differences.length})</h2>
      <div className="row wrap"><input autoComplete="off" placeholder="Filter by file or keyword…" value={filter} onChange={e => { setFilter(e.target.value); setLimit(100) }} />
        <button onClick={() => setSelected(new Set(rows.filter(d => d.action === 'add').map(d => d.id)))}>Select missing keywords</button>
        <button onClick={() => setSelected(new Set())}>Clear selection</button>
        <button className="primary" disabled={busy || checking || !selected.size} onClick={apply}>Apply {selected.size} selected fixes</button>
      </div>
      {!rows.length && <p className="muted">No differences to show.</p>}
      {rows.slice(0, limit).map(d => <div className="review-difference" key={d.id}>
        <label className="row"><input type="checkbox" checked={selected.has(d.id)} onChange={e => setSelected(s => {
          const next = new Set(s); if (e.target.checked) next.add(d.id); else next.delete(d.id); return next
        })} />
          <b>{d.reason ?? (d.action === 'add' ? 'Missing keyword' : 'Outside selected scope')}</b></label>
        <Link to={`/photos/${d.photo_id}`}>{d.path}</Link> · {d.variation}<br />
        <code>{d.keyword}</code> · {d.inherited === 'This photograph' ? 'This scan family' : d.inherited}
        {d.action === 'remove' && d.source === 'file' && <strong className="hint error"> · Existing owner keyword — explicit confirmation required</strong>}
        <div><button disabled={busy || checking} onClick={async () => {
          if (await run(() => api.keywordException(d.image_id, d.keyword_id, d.present))) load()
        }}>Keep current value as an exception</button></div>
      </div>)}
      {rows.length > limit && <button onClick={() => setLimit(n => n + 100)}>Show more differences</button>}
    </section>
    <details className="card"><summary>Deliberate exceptions ({r.exceptions.length})</summary>
      {r.exceptions.map(e => <div className="review-difference" key={`${e.image_id}:${e.keyword_id}`}>
        <Link to={`/photos/${e.photo_id}`}>{e.path}</Link> · <code>{e.keyword}</code> · Keep {e.expected ? 'present' : 'absent'}
        <button onClick={async () => { if (await run(() => api.keywordException(e.image_id, e.keyword_id, null))) load() }}>Restore inherited preference</button>
      </div>)}
    </details>
    {message && <p className="hint">{message}</p>}
  </div>
}
