import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, displayName, type Keyword, type PhotoKeyword } from '../api'
import { useAction } from '../state'

let vocabCache: Keyword[] | null = null

export function useVocabulary(reloadKey?: unknown) {
  const [vocab, setVocab] = useState<Keyword[]>(vocabCache ?? [])
  useEffect(() => { api.keywords().then(v => { vocabCache = v; setVocab(v) }) }, [reloadKey])
  return vocab
}

export const keywordLabel = (k: { kind: string; name: string; category: string }) =>
  `${k.kind === 'person' ? displayName(k.name) : k.name} — ${k.category}`

/** Type-ahead over the keyword list; unknown text can become a new keyword in a chosen category. */
export function KeywordInput({ exclude, onPick }: {
  exclude?: Set<number>
  onPick: (k: Keyword) => Promise<boolean | void>
}) {
  const run = useAction()
  const vocab = useVocabulary()
  const [text, setText] = useState('')
  const [newCategory, setNewCategory] = useState('')
  const categories = useMemo(() => [...new Set(vocab.map(k => k.category))].sort(), [vocab])
  const match = vocab.find(k => keywordLabel(k) === text) ??
    vocab.find(k => k.name.toLowerCase() === text.replace(/\s/g, '').toLowerCase())

  async function add() {
    let k = match
    if (!k && newCategory && text.trim())
      k = await run(() => api.createKeyword({ category: newCategory, name: text.trim() }))
    if (k && (await onPick(k)) !== false) { setText(''); setNewCategory('') }
  }

  return (
    <div className="row kw-add">
      <input list="kw-vocab" value={text} placeholder="Add keyword…" onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') add() }} />
      <datalist id="kw-vocab">
        {vocab.filter(k => !exclude?.has(k.id)).map(k => <option key={k.id} value={keywordLabel(k)} />)}
      </datalist>
      {text.trim() && !match && (
        <select value={newCategory} onChange={e => setNewCategory(e.target.value)} title="Category for a new keyword">
          <option value="">New keyword in…</option>
          {categories.map(c => <option key={c}>{c}</option>)}
        </select>
      )}
      <button disabled={!match && !(newCategory && text.trim())} onClick={add}>Add</button>
    </div>
  )
}

export function KeywordChip({ k, onRemove, extra }: {
  k: PhotoKeyword | Keyword
  onRemove?: () => void
  extra?: React.ReactNode
}) {
  const source = 'source' in k ? k.source : ''
  return (
    <span className={`kw ${k.kind} ${source}`}
      title={source === 'app' ? 'Added by Shoebox Archivist' : source === 'file' ? 'In the file when imported' : ''}>
      {k.person_id
        ? <Link to={`/people/${k.person_id}`}>{displayName(k.name)}</Link>
        : <Link to={`/photos?keyword=${k.id}`}>{k.name}</Link>}
      {extra}
      {onRemove && <button onClick={onRemove} title="Remove">×</button>}
    </span>
  )
}

export function groupByCategory<T extends { category: string }>(items: T[]): [string, T[]][] {
  const g = new Map<string, T[]>()
  for (const k of items) g.set(k.category, [...(g.get(k.category) ?? []), k])
  return [...g.entries()]
}

/** A photo's keywords grouped by category, with add / remove. Changes are written
 *  into the photo file's XMP keywords (lr:hierarchicalSubject). */
export function KeywordsCard({ photoId, keywords, onChange }: {
  photoId: number
  keywords: PhotoKeyword[]
  onChange: () => void
}) {
  const run = useAction()
  const groups = useMemo(() => groupByCategory(keywords), [keywords])

  async function remove(k: PhotoKeyword) {
    if (k.source === 'file' &&
        !confirm(`"${k.category}|${k.name}" was already in the file. Remove it from the file?`)) return
    if (await run(() => api.removeKeyword(photoId, k.id), 'Keyword removed')) onChange()
  }

  return (
    <section className="card">
      <h2>Keywords <span className="muted">({keywords.length})</span></h2>
      {groups.length === 0 && <p className="muted small">No keywords.</p>}
      {groups.map(([cat, ks]) => (
        <div key={cat} className="kw-group">
          <span className="kw-cat">{cat}</span>
          {ks.map(k => <KeywordChip key={k.id} k={k} onRemove={() => remove(k)} />)}
        </div>
      ))}
      <KeywordInput exclude={new Set(keywords.map(k => k.id))} onPick={async k => {
        const r = await run(() => api.addKeyword(photoId, { keyword_id: k.id }), 'Keyword added to file')
        if (r) onChange()
        return !!r
      }} />
      <p className="muted small">
        Saved into the photo file. <span className="kw app legend">Highlighted</span> = added by this app.
      </p>
    </section>
  )
}
