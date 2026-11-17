import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type PersonRef } from '../api'
import { keywordSpelling } from '../keywordSpelling'
import { PersonKeywordForm } from './PersonKeywordForm'
import { useAction, useApp } from '../state'

const normalized = (name: string) => name.replace(/\s/g, '').toLowerCase()

interface Props {
  /** Called with an existing person or a new name. */
  onPick: (who: PersonRef, label: string) => void
  placeholder?: string
  initial?: string
  /** Keep an untouched suggestion tied to its person, even when names match. */
  initialPersonId?: number
  buttonLabel?: string
  disabled?: boolean
  /** Exclude a person (e.g. when merging, the person themself). */
  excludeId?: number
  allowNew?: boolean
  autoFocus?: boolean
  /** Empty the box after a pick (for adding several people in a row). */
  clearOnPick?: boolean
}

/** Type-ahead person chooser. Enter picks the highlighted match, or creates a new person. */
export function PersonPicker({
  onPick, placeholder = 'Name…', initial = '', initialPersonId, buttonLabel = 'Assign',
  disabled, excludeId, allowNew = true, autoFocus, clearOnPick,
}: Props) {
  const { people, resolvePerson, refresh } = useApp()
  const run = useAction()
  const [creating, setCreating] = useState(false)
  const [category, setCategory] = useState('')
  const [keyword, setKeyword] = useState('')
  const [saving, setSaving] = useState(false)
  const [text, setText] = useState(initial)
  const [open, setOpen] = useState(false)
  const [hi, setHi] = useState(0)
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => setText(initial), [initial])

  const preferredId = text === initial && initialPersonId !== excludeId ? initialPersonId : undefined
  const matches = useMemo(() => {
    const t = normalized(text)
    return people
      .filter(p => p.id !== excludeId)
      .filter(p => p.id === preferredId || !t || normalized(p.name).includes(t) ||
        p.aliases?.some(a => normalized(a.name).includes(t)) ||
        p.keyword_paths?.some(k => normalized(k).includes(t)))
      .sort((a, b) => {
        if (a.id === preferredId || b.id === preferredId) return a.id === preferredId ? -1 : 1
        const as = normalized(a.name).startsWith(t) ? 0 : 1
        const bs = normalized(b.name).startsWith(t) ? 0 : 1
        return as - bs || a.name.localeCompare(b.name)
      })
      .slice(0, 8)
  }, [people, text, excludeId, preferredId])

  const low = normalized(text)
  const exact = people.some(p => normalized(p.name) === low ||
    p.aliases?.some(a => normalized(a.name) === low) ||
    p.keyword_paths?.some(k => normalized(k.split('|').slice(-1)[0] ?? '') === low))
  const showNew = allowNew && text.trim() !== '' && !exact
  const options: { label: string; paths?: string[]; who: PersonRef }[] = [
    ...matches.map(p => ({
      label: p.aliases?.length ? `${p.display_name} (${[p.name, ...p.aliases.map(a => a.name)].filter(n => n !== p.display_name).join(', ')})` : p.name,
      paths: p.keyword_paths,
      who: { person_id: p.id } as PersonRef,
    })),
    ...(showNew ? [{ label: `+ New person "${text.trim()}"`, who: { name: text.trim() } as PersonRef }] : []),
  ]

  function choose(who: PersonRef, label: string) {
    if ('name' in who) {
      setKeyword(keywordSpelling(who.name)); setCategory(''); setCreating(true); setOpen(false)
    } else {
      onPick(who, label); setOpen(false)
      if (clearOnPick) { setText(''); setHi(0) }
    }
  }

  async function create() {
    setSaving(true)
    const person = await run(() => api.createPerson(text.trim(), category, keyword))
    setSaving(false)
    if (person) {
      await refresh()
      setCreating(false)
      choose({ person_id: person.id }, person.name)
    }
  }

  function pick(i: number) {
    const o = options[i]
    if (!o) {
      if (preferredId !== undefined) { choose({ person_id: preferredId }, text); return }
      const who = resolvePerson(text)
      if (who && (allowNew || 'person_id' in who)) {
        choose(who, text.trim())
      }
      return
    }
    choose(o.who, 'name' in o.who ? o.who.name : o.label)
  }

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  if (creating) return (
    <div className="card">
      <b>New person: {text.trim()}</b>
      <PersonKeywordForm category={category} name={keyword} onChange={(c, n) => { setCategory(c); setKeyword(n) }} />
      <div className="row">
        <button className="primary" disabled={saving || !category.trim() || !keyword.trim()} onClick={create}>
          {saving ? 'Saving…' : `Create person and ${buttonLabel.toLowerCase()}`}
        </button>
        <button disabled={saving} onClick={() => setCreating(false)}>Cancel</button>
      </div>
    </div>
  )

  return (
    <div className="picker" ref={boxRef}>
      <input autoComplete="off"
        value={text}
        placeholder={placeholder}
        disabled={disabled}
        autoFocus={autoFocus}
        onChange={e => { setText(e.target.value); setOpen(true); setHi(0) }}
        onFocus={() => setOpen(true)}
        onKeyDown={e => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setHi(h => Math.min(h + 1, options.length - 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setHi(h => Math.max(h - 1, 0)) }
          else if (e.key === 'Enter') { e.preventDefault(); pick(open ? hi : -1) }
          else if (e.key === 'Escape') setOpen(false)
        }}
      />
      <button className="primary" disabled={disabled || !text.trim()} onClick={() => pick(-1)}>
        {buttonLabel}
      </button>
      {open && options.length > 0 && !disabled && (
        <ul className="picker-menu">
          {options.map((o, i) => (
            <li
              key={o.label}
              className={i === hi ? 'hi' : ''}
              onMouseEnter={() => setHi(i)}
              onMouseDown={e => { e.preventDefault(); pick(i) }}
            >{o.label}{o.paths?.map(path => <code className="picker-path" key={path}>{path}</code>)}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
