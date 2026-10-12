import { useEffect, useMemo, useRef, useState } from 'react'
import type { PersonRef } from '../api'
import { useApp } from '../state'

interface Props {
  /** Called with an existing person or a new name. */
  onPick: (who: PersonRef, label: string) => void
  placeholder?: string
  initial?: string
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
  onPick, placeholder = 'Name…', initial = '', buttonLabel = 'Assign',
  disabled, excludeId, allowNew = true, autoFocus, clearOnPick,
}: Props) {
  const { people, resolvePerson } = useApp()
  const [text, setText] = useState(initial)
  const [open, setOpen] = useState(false)
  const [hi, setHi] = useState(0)
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => setText(initial), [initial])

  const matches = useMemo(() => {
    const t = text.trim().toLowerCase()
    return people
      .filter(p => p.id !== excludeId)
      .filter(p => !t || p.name.toLowerCase().includes(t) ||
        p.aliases?.some(a => a.name.toLowerCase().includes(t)))
      .sort((a, b) => {
        const as = a.name.toLowerCase().startsWith(t) ? 0 : 1
        const bs = b.name.toLowerCase().startsWith(t) ? 0 : 1
        return as - bs || a.name.localeCompare(b.name)
      })
      .slice(0, 8)
  }, [people, text, excludeId])

  const low = text.trim().toLowerCase()
  const exact = people.some(p => p.name.toLowerCase() === low ||
    p.aliases?.some(a => a.name.toLowerCase() === low))
  const showNew = allowNew && text.trim() !== '' && !exact
  const options: { label: string; who: PersonRef }[] = [
    ...matches.map(p => ({
      label: p.aliases?.length ? `${p.display_name} (${[p.name, ...p.aliases.map(a => a.name)].filter(n => n !== p.display_name).join(', ')})` : p.name,
      who: { person_id: p.id } as PersonRef,
    })),
    ...(showNew ? [{ label: `+ New person "${text.trim()}"`, who: { name: text.trim() } as PersonRef }] : []),
  ]

  function pick(i: number) {
    const o = options[i]
    if (!o) {
      const who = resolvePerson(text)
      if (who && (allowNew || 'person_id' in who)) {
        onPick(who, text.trim())
        if (clearOnPick) { setText(''); setHi(0) }
      }
      return
    }
    onPick(o.who, 'name' in o.who ? o.who.name : o.label)
    setOpen(false)
    if (clearOnPick) { setText(''); setHi(0) }
  }

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  return (
    <div className="picker" ref={boxRef}>
      <input
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
            >{o.label}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
