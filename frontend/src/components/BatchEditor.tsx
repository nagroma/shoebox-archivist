import { useEffect, useMemo, useState } from 'react'
import { api, type BatchPhoto, type Keyword, type PhotoKeyword } from '../api'
import { useAction, useApp } from '../state'
import { groupByCategory, KeywordChip, KeywordInput } from './Keywords'

type Field = 'date_text' | 'location' | 'caption'
const FIELDS: [Field, string][] = [['date_text', 'Date'], ['location', 'Location'], ['caption', 'Caption']]
export const MIXED = '<...>'

/** The value shared by all photos, or undefined when they differ. */
function common(photos: BatchPhoto[], f: Field): string | undefined {
  const vals = new Set(photos.map(p => p[f] ?? ''))
  return vals.size === 1 ? [...vals][0] : undefined
}

/** Edit date / location / caption / keywords of several photos at once. A field that
 *  differs between the photos shows <...>; it is only changed if you type in it. */
export function BatchEditor({ ids, onClose }: { ids: number[]; onClose: () => void }) {
  const run = useAction()
  const { refresh, toast } = useApp()
  const [photos, setPhotos] = useState<BatchPhoto[] | null>(null)
  const [edits, setEdits] = useState<Partial<Record<Field, string>>>({})
  const [addKw, setAddKw] = useState<Keyword[]>([])
  const [removeKw, setRemoveKw] = useState<Set<number>>(new Set())
  const [saving, setSaving] = useState(false)
  const key = ids.join(',')

  useEffect(() => {
    let live = true
    setPhotos(null); setEdits({}); setAddKw([]); setRemoveKw(new Set())
    api.batchGet(ids).then(p => { if (live) setPhotos(p) })
    return () => { live = false }
  }, [key])  // eslint-disable-line react-hooks/exhaustive-deps

  // keyword id -> keyword + how many selected photos have it
  const counts = useMemo(() => {
    const m = new Map<number, { k: PhotoKeyword; n: number }>()
    for (const p of photos ?? []) for (const k of p.keywords) {
      const e = m.get(k.id)
      m.set(k.id, { k, n: (e?.n ?? 0) + 1 })
    }
    return m
  }, [photos])

  if (!photos) return <aside className="batch-editor card"><p className="muted">Loading…</p></aside>
  const total = photos.length
  const dirty = Object.keys(edits).length > 0 || addKw.length > 0 || removeKw.size > 0
  const kwGroups = groupByCategory([...counts.values()].map(e => ({ ...e, category: e.k.category })))

  async function save() {
    const fileKeywords = [...removeKw].filter(id => counts.get(id)?.k.source === 'file')
    if (fileKeywords.length && !confirm(
      `Remove ${fileKeywords.length} keyword(s) that were already in the files from ${total} photo(s)?`)) return
    setSaving(true)
    const r = await run(() => api.batchEdit({
      photo_ids: ids, fields: edits,
      add_keyword_ids: addKw.map(k => k.id), remove_keyword_ids: [...removeKw],
    }))
    setSaving(false)
    if (!r) return
    refresh()
    window.dispatchEvent(new Event('library-changed'))
    const kw = r.keywords_added || r.keywords_removed
      ? ` · keywords +${r.keywords_added} / −${r.keywords_removed}` : ''
    toast(`Saved ${r.photos} photo(s)${kw}`)
    setPhotos(await api.batchGet(ids))
    setEdits({}); setAddKw([]); setRemoveKw(new Set())
  }
  return (
    <aside className="batch-editor card">
      <div className="card-head">
        <h2>{total} photo{total === 1 ? '' : 's'} selected</h2>
        <button onClick={onClose} title="Clear selection (Esc)">×</button>
      </div>

      {FIELDS.map(([f, label]) => {
        const shared = common(photos, f)
        const edited = f in edits
        const Input = f === 'caption' ? 'textarea' : 'input'
        return (
          <label key={f} className={`field ${edited ? 'edited' : ''}`}>
            <span>{label}{edited && <button className="link small" onClick={() => {
              const { [f]: _, ...rest } = edits; setEdits(rest)
            }}>undo</button>}</span>
            <Input value={edited ? edits[f] : shared ?? ''}
              placeholder={shared === undefined ? MIXED : f === 'date_text' ? 'e.g. 1975, c. 1950, May 1948' : ''}
              title={shared === undefined && !edited ? 'Differs between the selected photos; type to set it on all of them' : ''}
              onChange={e => {
                const { [f]: _, ...rest } = edits
                // emptying a <...> field means "leave alone", not "clear on all"
                setEdits(shared === undefined && !e.target.value ? rest : { ...rest, [f]: e.target.value })
              }} />
          </label>
        )
      })}

      <h3>Keywords</h3>
      {kwGroups.length === 0 && addKw.length === 0 && <p className="muted small">No keywords.</p>}
      {kwGroups.map(([cat, es]) => (
        <div key={cat} className="kw-group">
          <span className="kw-cat">{cat}</span>
          {es.map(({ k, n }) => removeKw.has(k.id)
            ? <span key={k.id} className="kw removed" title="Will be removed">
                {k.name}<button onClick={() => { const s = new Set(removeKw); s.delete(k.id); setRemoveKw(s) }}
                  title="Keep">↺</button>
              </span>
            : <KeywordChip key={k.id} k={k}
                extra={n < total && <>
                  <span className="kw-count" title={`On ${n} of ${total} photos`}>{n}/{total}</span>
                  {!addKw.some(a => a.id === k.id) &&
                    <button onClick={() => setAddKw([...addKw, k])} title="Add to all selected photos">+all</button>}
                </>}
                onRemove={() => setRemoveKw(new Set(removeKw).add(k.id))} />)}
        </div>
      ))}
      {addKw.length > 0 && (
        <div className="kw-group">
          <span className="kw-cat">Adding to all</span>
          {addKw.map(k => <KeywordChip key={k.id} k={k}
            onRemove={() => setAddKw(addKw.filter(a => a.id !== k.id))} />)}
        </div>
      )}
      <KeywordInput
        exclude={new Set([...addKw.map(k => k.id),
          ...[...counts.values()].filter(e => e.n === total).map(e => e.k.id)])}
        onPick={async k => {
          if (removeKw.has(k.id)) { const s = new Set(removeKw); s.delete(k.id); setRemoveKw(s) }
          if (!addKw.some(a => a.id === k.id)) setAddKw([...addKw, k])
        }} />

      <div className="row batch-actions">
        <button className="primary" disabled={!dirty || saving} onClick={save}>
          {saving ? 'Saving…' : `Save to ${total} photo${total === 1 ? '' : 's'}`}
        </button>
        <button disabled={!dirty || saving} onClick={() => { setEdits({}); setAddKw([]); setRemoveKw(new Set()) }}>
          Discard
        </button>
      </div>
      <p className="muted small">
        Fields showing {MIXED} differ between photos and are left alone unless you type in them.
        Changes are written into the photo files.
      </p>
    </aside>
  )
}
