import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type GroupPreview, type Keyword, type SharingRule, type SharingSettings, type VariationConfig } from '../api'
import { useAction, useApp } from '../state'
import { ScopeSelector } from './KeywordScope'

function inheritsRestriction(rule: SharingRule, rules: SharingRule[], index: number) {
  const parent = rules.filter((r, i) => i !== index && r.target === 'hierarchy' && r.path &&
    (rule.path.startsWith(r.path + '|') || (rule.target === 'keyword' && rule.path === r.path)))
    .sort((a, b) => b.path.length - a.path.length)[0]
  return !!parent && parent.scope.mode !== 'all'
}

export function ScanFamilySettings() {
  const run = useAction()
  const { refresh } = useApp()
  const [config, setConfig] = useState<VariationConfig | null>(null)
  const [overrides, setOverrides] = useState<Record<number, string>>({})
  const [appliedEnabled, setAppliedEnabled] = useState(false)
  const [plan, setPlan] = useState<GroupPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [conventionMessage, setConventionMessage] = useState('')
  const [limit, setLimit] = useState(20)
  useEffect(() => {
    run(async () => {
      const c = await api.variations()
      setConfig(c); setAppliedEnabled(c.enabled); setOverrides(c.overrides ?? {})
    })
  }, [run])
  if (!config) return <p className="muted">Loading scan preferences…</p>
  const cfg = config
  function change(next: VariationConfig) { setConfig(next); setPlan(null); setConventionMessage('') }
  function mapping(id: number, key: string) {
    const next = { ...overrides }
    if (key.trim()) next[id] = key.trim(); else delete next[id]
    setOverrides(next); setPlan(p => p ? { ...p, token: '' } : null)
  }
  async function preview() {
    setBusy(true)
    const p = await run(() => api.previewVariations(cfg, overrides))
    if (p) { setPlan(p); setLimit(20) }
    setBusy(false)
  }
  async function apply() {
    if (!plan) return
    setBusy(true)
    const r = await run(() => api.applyVariations(cfg, plan.token, overrides))
    if (r) {
      setAppliedEnabled(true); setPlan(null); setConventionMessage(`Grouped ${r.files} files into ${r.groups} scan ${r.groups === 1 ? 'family' : 'families'}. A database backup was saved. Photo metadata was not changed.`)
      await refresh(); window.dispatchEvent(new Event('library-changed'))
    }
    setBusy(false)
  }
  return <>
    <section className="card" id="scan-families">
      <h2>Scan families and filename conventions</h2>
      <p>A scan family contains the files for one physical photo. Each file—an original, a corrected front, a back, or another scan—is a scan variant. Filenames stay unchanged.</p>
      <label className="row"><input type="checkbox" checked={cfg.enabled} disabled={busy} onChange={e => change({ ...cfg, enabled: e.target.checked })} />
        Enable filename conventions for this library</label>
      {cfg.enabled && <p className="muted small">Click <b>Preview scan families</b> below. If the groups look right, click
        {' '}<b>Save convention and apply scan families</b> at the end of the preview.</p>}
      <fieldset className="filename-convention-fields" disabled={!cfg.enabled || busy}>
        <div className="row wrap">
          <button disabled={busy} onClick={() => change({ enabled: true, pattern: 'suffix', preferred: '_a', recognition: '_a', types: [
            { suffix: '', label: 'Original front', role: 'front' }, { suffix: '_a', label: 'Corrected front', role: 'front' },
            { suffix: '_b', label: 'Back', role: 'back' },
          ] })}>Use Epson FastFoto suggestions</button>
          <label>Filename rule <select value={cfg.pattern} onChange={e => change({ ...cfg, pattern: e.target.value as VariationConfig['pattern'] })}>
            <option value="suffix">Remove a configured suffix from the filename</option>
            <option value="serial">Final number identifies photo; all following characters identify variation</option>
          </select></label>
        </div>
        <p className="muted small">Example: <code>36_Topic_0005_a.jpg</code> → photo <code>36_Topic_0005</code>, scan variant <code>_a</code>.
          Matching is within the same folder. Unknown suffixes remain separate for review. Every mapping below can be changed.</p>
        <div className="table-scroll"><table className="facets"><thead><tr><th>Suffix (blank = none)</th><th>Meaning</th><th>Role</th><th /></tr></thead><tbody>
          {cfg.types.map((t, i) => <tr key={i}>
            <td><input autoComplete="off" aria-label={`Suffix ${i + 1}`} value={t.suffix} onChange={e => change({ ...cfg, types: cfg.types.map((x, j) => j === i ? { ...x, suffix: e.target.value } : x) })} /></td>
            <td><input autoComplete="off" aria-label={`Meaning ${i + 1}`} value={t.label} onChange={e => change({ ...cfg, types: cfg.types.map((x, j) => j === i ? { ...x, label: e.target.value } : x) })} /></td>
            <td><select aria-label={`Role ${i + 1}`} value={t.role} onChange={e => change({ ...cfg, types: cfg.types.map((x, j) => j === i ? { ...x, role: e.target.value as typeof t.role } : x) })}>
              <option value="front">Front</option><option value="back">Back</option><option value="other">Other scan variant</option>
            </select></td>
            <td><button title="Remove scan variant type" onClick={() => change({ ...cfg, types: cfg.types.filter((_, j) => j !== i) })}>×</button></td>
          </tr>)}
        </tbody></table></div>
        <button onClick={() => change({ ...cfg, types: [...cfg.types, { suffix: '', label: '', role: 'other' }] })}>+ Add scan variant type</button>
        <div className="row wrap" style={{ marginTop: 12 }}>
          <label>Display by default <select value={cfg.preferred} onChange={e => change({ ...cfg, preferred: e.target.value })}>
            {cfg.types.filter(t => t.role === 'front').map((t, i) => <option key={i} value={t.suffix}>{t.label || '(name needed)'}</option>)}
          </select></label>
          <label>Use for face recognition <select value={cfg.recognition} onChange={e => change({ ...cfg, recognition: e.target.value })}>
            {cfg.types.filter(t => t.role === 'front').map((t, i) => <option key={i} value={t.suffix}>{t.label || '(name needed)'}</option>)}
          </select></label>
        </div>
        <p className="muted small">If the preferred front is missing, another front is used. Existing face decisions remain attached to their original files.</p>
        <button onClick={preview}>Preview scan families</button>
        {plan && <div className="group-preview">
          <h3>{plan.files} files → {plan.groups.length} scan {plan.groups.length === 1 ? 'family' : 'families'}</h3>
          <p className="muted small">Review before applying. To group exceptions manually, enter the same scan family name on their rows, then preview again.
            Keep separate creates a separate scan family. Clear a manual name to restore filename matching.</p>
          {plan.groups.slice(0, limit).map(g => <div className="card" key={g.key}>
            <b>{g.key}</b>
            {g.issues.map(x => <p className="hint error" key={x}>{x}</p>)}
            {g.metadata_conflicts.length > 0 && <p className="hint">Different app values: {g.metadata_conflicts.join(', ')}.
              The displayed photo keeps its values; other values are preserved in the grouping backup and history.</p>}
            {g.members.map(m => <div className="version-preview" key={m.id}>
              <div><code>{m.path}</code><div className="muted small">{m.label}{m.id === g.primary_id && ' · Display'}{m.id === g.recognition_id && ' · Face recognition'}</div>
                </div>
              <input autoComplete="off" aria-label={`Manual scan family for ${m.path}`} placeholder="Automatic grouping" value={overrides[m.id] ?? ''} onChange={e => mapping(m.id, e.target.value)} />
              <button onClick={() => mapping(m.id, `separate-${m.id}`)}>Keep separate</button>
            </div>)}
          </div>)}
          {limit < plan.groups.length && <button onClick={() => setLimit(n => n + 30)}>Show more scan families</button>}
          <button className="primary" disabled={busy || !plan.token} onClick={apply}>Save convention and apply scan families</button>
        </div>}
      </fieldset>
    </section>
    {!cfg.enabled && appliedEnabled && <div className="row wrap filename-convention-pause">
      <span className="muted small">The saved convention still applies to future scans until you pause it.</span>
      <button disabled={busy} onClick={async () => {
        setBusy(true)
        const r = await run(() => api.pauseVariations())
        if (r) { setConfig(r); setAppliedEnabled(false); setConventionMessage('Automatic grouping paused. Existing scan families and photo metadata are unchanged.'); refresh() }
        setBusy(false)
      }}>Pause automatic grouping for future scans</button>
    </div>}
    {conventionMessage && <p className="hint" role="status">{conventionMessage}</p>}
  </>
}

export function KeywordSharingSettings() {
  const run = useAction()
  const [types, setTypes] = useState<VariationConfig['types'] | null>(null)
  const [sharing, setSharing] = useState<SharingSettings | null>(null)
  const [vocab, setVocab] = useState<Keyword[]>([])
  const [busy, setBusy] = useState(false)
  const [sharingMessage, setSharingMessage] = useState<{ text: string; error?: boolean } | null>(null)
  useEffect(() => {
    run(async () => {
      const [config, rules, keywords] = await Promise.all([api.variations(), api.sharing(), api.keywords()])
      setTypes(config.types); setSharing(rules); setVocab(keywords)
    })
  }, [run])
  if (!types || !sharing) return <p className="muted">Loading keyword sharing preferences…</p>
  const rules = sharing
  async function saveRules() {
    setBusy(true)
    setSharingMessage(null)
    try {
      const saved = await api.saveSharing(rules)
      setSharing(saved)
      setSharingMessage({ text: 'Sharing preferences saved.' })
    } catch (error) {
      setSharingMessage({ text: (error as Error).message, error: true })
    } finally {
      setBusy(false)
    }
  }
  const hierarchies = [...new Set(vocab.flatMap(k => k.category.split('|').map((_, i, a) => a.slice(0, i + 1).join('|'))))].sort()
  return (
    <section className="card">
      <h2>Where keywords apply</h2>
      <p>All keywords apply to all scan variants by default. Add exceptions here.
        Individual keyword rules override hierarchy rules; the closest parent hierarchy wins.</p>
      <fieldset className="keyword-sharing-fields" disabled={busy}>
        <datalist id="scope-hierarchies">{hierarchies.map(h => <option key={h}>{h}</option>)}</datalist>
        <datalist id="scope-keywords">{vocab.map(k => <option key={k.id}>{k.category}|{k.name}</option>)}</datalist>
        {rules.rules.map((r, i) => <div className="scope-rule card" key={i}>
          <div className="row wrap">
            <select aria-label="Rule type" value={r.target} onChange={e => setSharing({ ...rules, rules: rules.rules.map((x, j) => j === i ? { ...x, target: e.target.value as typeof r.target } : x) })}>
              <option value="hierarchy">Hierarchy and descendants</option><option value="keyword">Individual keyword</option>
            </select>
            <input autoComplete="off" className="scope-rule-path" aria-label="Hierarchy or keyword path" title={r.path}
              list={r.target === 'hierarchy' ? 'scope-hierarchies' : 'scope-keywords'} value={r.path}
              placeholder={r.target === 'hierarchy' ? 'Attributes' : 'Attributes|portrait'}
              onChange={e => setSharing({ ...rules, rules: rules.rules.map((x, j) => j === i ? { ...x, path: e.target.value } : x) })} />
            <button title="Remove rule and inherit defaults" onClick={() => setSharing({ ...rules, rules: rules.rules.filter((_, j) => j !== i) })}>×</button>
          </div>
          <ScopeSelector value={r.scope} types={types} allowAll={inheritsRestriction(r, rules.rules, i)} onChange={scope => setSharing({ ...rules, rules: rules.rules.map((x, j) => j === i ? { ...x, scope } : x) })} />
        </div>)}
        <button onClick={() => setSharing({ ...rules, rules: [...rules.rules, { target: 'hierarchy', path: '', scope: { mode: 'current', suffixes: [] } }] })}>+ Add sharing rule</button>
        <p className="muted small">Use “Ask separately” for a hierarchy whose keywords need individual choices. The all-variants option includes future suffixes; a list of specific suffixes stays fixed.</p>
      </fieldset>
      <div className="row wrap">
        <button className="primary" disabled={busy} onClick={saveRules}>
          {busy ? 'Saving preferences…' : 'Save sharing preferences'}
        </button>
        <Link to="/keywords/review">Review keyword differences for rule violations</Link>
      </div>
      {sharingMessage && <p className={sharingMessage.error ? 'hint error' : 'hint'} role={sharingMessage.error ? 'alert' : 'status'}>{sharingMessage.text}</p>}
    </section>
  )
}
