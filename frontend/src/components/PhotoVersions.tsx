import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type KeywordScope, type PhotoDetail, type PhotoKeyword, type VariationType } from '../api'
import { useAction, useApp } from '../state'
import { ScopeSelector } from './KeywordScope'

function PhotoKeywordScope({ photo, keyword, types, onChange }: {
  photo: PhotoDetail; keyword: PhotoKeyword; types: VariationType[]; onChange: () => void
}) {
  const run = useAction()
  const { refresh } = useApp()
  const saved = photo.keyword_scopes[keyword.id]
  const familyOverride = saved?.inherited === 'This photograph'
  const [scope, setScope] = useState<KeywordScope>(saved?.scope ?? { mode: 'all', suffixes: [] })
  const [busy, setBusy] = useState(false)
  async function save(value: KeywordScope | null) {
    setBusy(true)
    if (await run(() => api.photoKeywordScope(photo.id, keyword.id, value), 'Scope saved; review file differences before applying')) {
      onChange(); refresh()
    }
    setBusy(false)
  }
  return <div className="scope-rule">
    <b><code>{keyword.category}|{keyword.name}</code></b> <span className="muted small">{familyOverride ? 'This scan family' : saved?.inherited}</span>
    <ScopeSelector value={scope} types={types} allowAll={!!saved && saved.library_mode !== 'all'} onChange={setScope} />
    <div className="row wrap"><button disabled={busy || (scope.mode === 'all' && saved?.library_mode === 'all')} onClick={() => save(scope)}>Save scope for this scan family</button>
      {familyOverride && <button disabled={busy} onClick={() => save(null)}>Use inherited preference</button>}</div>
    <details><summary>Exceptions for individual scan variants</summary>
      {photo.images.map(image => {
        const exception = image.exceptions.find(e => e.keyword_id === keyword.id)
        return <label className="version-exception" key={image.id}>
          <span><code>{image.path}</code><br /><span className="muted small">Currently {image.keyword_ids.includes(keyword.id) ? 'present' : 'absent'}</span></span>
          <select aria-label={`Exception for ${image.path}`} value={exception ? String(exception.present) : 'inherit'} onChange={async e => {
            const value = e.target.value === 'inherit' ? null : e.target.value === '1'
            if (await run(() => api.keywordException(image.id, keyword.id, value))) { onChange(); refresh() }
          }}><option value="inherit">Use scope above</option><option value="1">Keep present</option><option value="0">Keep absent</option></select>
        </label>
      })}
    </details>
  </div>
}

export function PhotoVersionsCard({ photo, onChange }: { photo: PhotoDetail; onChange: () => void }) {
  const [types, setTypes] = useState<VariationType[]>([])
  useEffect(() => { api.variations().then(c => setTypes(c.types)) }, [])
  return <section className="card">
    <h2>Keyword sharing for this scan family</h2>
    <p className="muted small">These preferences create a review; saving does not rewrite files. Scan variant exceptions survive later confirmations and imports.</p>
    {photo.keywords.map(k => <PhotoKeywordScope key={`${photo.id}:${k.id}:${JSON.stringify(photo.keyword_scopes[k.id])}`} photo={photo} keyword={k} types={types} onChange={onChange} />)}
    {!photo.keywords.length && <p className="muted small">Add a keyword to choose its scope.</p>}
    <Link to="/keyword-review">Review and apply keyword differences</Link>
  </section>
}
