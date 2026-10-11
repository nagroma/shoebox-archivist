import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, setCacheKey, type PersonRef, type PersonSummary, type Stats } from './api'

interface AppState {
  people: PersonSummary[]
  stats: Stats | null
  /** Re-fetch people + stats after anything that changes them. */
  refresh: () => Promise<void>
  /** Resolve typed text to an existing person (case-insensitive) or a new name. */
  resolvePerson: (text: string) => PersonRef | null
  toast: (msg: string, kind?: 'ok' | 'error') => void
}

const Ctx = createContext<AppState | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [people, setPeople] = useState<PersonSummary[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [toasts, setToasts] = useState<{ id: number; msg: string; kind: string }[]>([])

  const refresh = useCallback(async () => {
    const [p, s] = await Promise.all([api.people(), api.stats()])
    setCacheKey(s.db_token)
    setPeople(p)
    setStats(s)
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const resolvePerson = useCallback((text: string): PersonRef | null => {
    const t = text.trim()
    if (!t) return null
    const hit = people.find(p => p.name.toLowerCase() === t.toLowerCase())
    return hit ? { person_id: hit.id } : { name: t }
  }, [people])

  const toast = useCallback((msg: string, kind: 'ok' | 'error' = 'ok') => {
    const id = Date.now() + Math.random()
    setToasts(ts => [...ts, { id, msg, kind }])
    setTimeout(() => setToasts(ts => ts.filter(t => t.id !== id)), kind === 'error' ? 6000 : 2500)
  }, [])

  return (
    <Ctx.Provider value={{ people, stats, refresh, resolvePerson, toast }}>
      {stats ? children : <p className="muted pad">Loading…</p>}
      <div className="toasts">
        {toasts.map(t => <div key={t.id} className={`toast ${t.kind}`}>{t.msg}</div>)}
      </div>
    </Ctx.Provider>
  )
}

export function useApp(): AppState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useApp outside AppProvider')
  return v
}

/** Run an async action, showing errors as toasts. */
export function useAction() {
  const { toast } = useApp()
  return useCallback(async <T,>(fn: () => Promise<T>, okMsg?: string): Promise<T | undefined> => {
    try {
      const r = await fn()
      if (okMsg) toast(okMsg)
      return r
    } catch (e) {
      toast((e as Error).message, 'error')
      return undefined
    }
  }, [toast])
}
