import type { KeywordScope, VariationType } from '../api'

export function ScopeSelector({ value, onChange, types, allowAll = false }: {
  value: KeywordScope; onChange: (v: KeywordScope) => void; types: VariationType[]; allowAll?: boolean
}) {
  return <div className="scope-selector">
    <select aria-label="Applies to" value={value.mode}
      onChange={e => onChange({ ...value, mode: e.target.value as KeywordScope['mode'] })}>
      {allowAll && <option value="all">All scan variants (override inherited rule)</option>}
      {!allowAll && value.mode === 'all' && <option value="all" disabled>All scan variants (default)</option>}
      <option value="one">One scan variant only</option>
      <option value="fronts">Fronts only</option>
      <option value="backs">Backs only</option>
      <option value="current">Keep separate for each scan variant</option>
      <option value="ask">Ask for each scan family</option>
      <option value="selected">Choose scan variants by suffix…</option>
    </select>
    {value.mode === 'one' && <p className="muted small">Flags the keyword if more than one scan variant in a family has it.</p>}
    {value.mode === 'selected' && <div className="row wrap">{types.map(t => <label className="row small" key={t.suffix}>
      <input type="checkbox" checked={value.suffixes.includes(t.suffix)} onChange={e =>
        onChange({ ...value, suffixes: e.target.checked ? [...value.suffixes, t.suffix] : value.suffixes.filter(s => s !== t.suffix) })} />
      {t.label} <code>{t.suffix || '(no suffix)'}</code>
    </label>)}</div>}
  </div>
}
