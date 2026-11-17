import { useEffect, useId, useState } from 'react'
import { api } from '../api'

/** Exact keyword spelling is independent of the readable person name. */
export function PersonKeywordForm({ category, name, onChange }: {
  category: string; name: string; onChange: (category: string, name: string) => void
}) {
  const [groups, setGroups] = useState<string[]>([])
  const [error, setError] = useState('')
  const id = useId()
  useEffect(() => {
    Promise.all([api.library(), api.keywords(true)]).then(([lib, kws]) => {
      setGroups([...new Set([
        ...(lib.facets ?? []).filter(f => f.kind === 'person').map(f => f.name),
        ...kws.filter(k => k.kind === 'person').map(k => k.category),
      ])].sort())
    }).catch(e => setError(e.message))
  }, [])
  return (
    <div className="keyword-form">
      <label>Parent group or path
        <input autoComplete="off" list={id} value={category} placeholder="Choose a person group…"
          onChange={e => onChange(e.target.value, name)} />
        <datalist id={id}>{groups.map(g => <option key={g} value={g} />)}</datalist>
      </label>
      <label>Keyword spelling
        <input autoComplete="off" value={name} placeholder="FirstLast" onChange={e => onChange(category, e.target.value)} />
      </label>
      <p className="muted small">Keyword to write: <code>{category || '…'}|{name || '…'}</code></p>
      <p className="muted small">Use an existing person group from Library. Separate nested groups with |.</p>
      {error && <p className="hint error">{error}</p>}
    </div>
  )
}

