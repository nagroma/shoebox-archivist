import { useEffect, useState } from 'react'
import { api, type Settings, type SettingsData } from '../api'
import { useAction } from '../state'

type Key = keyof Settings

/** One row: label, control, help text from the server. */
function Field({ k, label, data, draft, set, indent, children }: {
  k: Key; label: string; data: SettingsData; draft: Settings
  set: (k: Key, v: Settings[Key]) => void; indent?: boolean; children?: React.ReactNode
}) {
  const v = draft[k]
  const changed = v !== data.defaults[k]
  return (
    <div className={`field ${indent ? 'indent' : ''}`}>
      <label htmlFor={k}>{label}{changed && <span className="changed-dot" title={`Default: ${data.defaults[k]}`}>●</span>}</label>
      <div>
        {children ?? (typeof v === 'boolean'
          ? <input id={k} type="checkbox" checked={v} onChange={e => set(k, e.target.checked)} />
          : <input id={k} type="number" value={v as number} style={{ width: 90 }}
              step={k === 'suggest_threshold' ? 0.01 : 1}
              onChange={e => set(k, Number(e.target.value))} />)}
      </div>
      <span className="help muted">{data.help[k]}</span>
    </div>
  )
}

export function SettingsPage() {
  const run = useAction()
  const [data, setData] = useState<SettingsData | null>(null)
  const [draft, setDraft] = useState<Settings | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.settings().then(d => { setData(d); setDraft(d.values) }, e => setError((e as Error).message))
  }, [])

  if (error) return <p className="muted pad">{error}</p>
  if (!data || !draft) return <p className="muted pad">Loading…</p>

  const set = (k: Key, v: Settings[Key]) => setDraft({ ...draft, [k]: v })
  const dirty = (Object.keys(draft) as Key[]).filter(k => draft[k] !== data.values[k])
  const props = { data, draft, set }

  async function save() {
    const changes = Object.fromEntries(dirty.map(k => [k, draft![k]])) as Partial<Settings>
    const d = await run(() => api.saveSettings(changes), 'Settings saved')
    if (d) {
      setData(d); setDraft(d.values)
      window.dispatchEvent(new Event('library-changed'))
    }
  }

  return (
    <div className="page settings">
      <header className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="muted">Shared by this web app and the <code>pm</code> command line. Saved in the library database.</p>
        </div>
        <div className="row">
          <button onClick={() => setDraft(data.defaults)}>Restore defaults</button>
          <button onClick={() => setDraft(data.values)} disabled={!dirty.length}>Undo changes</button>
          <button className="primary" onClick={save} disabled={!dirty.length}>Save</button>
        </div>
      </header>

      <section className="card">
        <h2>Face detection</h2>
        <p className="muted small">Applies to photos scanned from now on. To re-check photos already scanned, run
          {' '}<code>uv run pm ingest &lt;folder&gt; --rescan</code> (existing faces and names are kept).</p>
        <Field k="detection_mode" label="Mode" {...props}>
          <select id="detection_mode" value={draft.detection_mode}
            onChange={e => set('detection_mode', e.target.value as Settings['detection_mode'])}>
            <option value="thorough">Thorough (about 8× slower, misses fewer faces)</option>
            <option value="fast">Fast</option>
          </select>
        </Field>
        <Field k="pass_contrast" label="Contrast-enhanced pass" indent {...props} />
        <Field k="pass_enlarged" label="Enlarged pass" indent {...props} />
        <Field k="pass_rotated" label="Rotated passes" indent {...props} />
      </section>

      <section className="card">
        <h2>Naming faces</h2>
        <Field k="suggest_threshold" label="Suggestion threshold" {...props} />
        <Field k="keyword_autoconfirm" label="Name from keywords" {...props} />
        <Field k="min_cluster_size" label="Minimum cluster size" {...props} />
        <Field k="preselect_non_faces" label="Pre-select likely non-faces" {...props} />
      </section>

      <section className="card">
        <h2>About this library</h2>
        <dl>
          <dt className="muted">Library folder</dt><dd>{data.info.library_root ?? 'not set yet'}</dd>
          <dt className="muted">Data folder</dt><dd>{data.info.data_dir}</dd>
          <dt className="muted">Face model runs on</dt><dd>{data.info.provider}</dd>
        </dl>
      </section>
    </div>
  )
}
