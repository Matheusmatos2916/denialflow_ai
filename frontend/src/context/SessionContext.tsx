import { createContext, useContext, useState, type ReactNode } from 'react'

export type AuthUser = { id:string; name:string; email:string }
type Session = { lastBatchId: string; lastRunId: string; token: string; user: AuthUser|null; setAuth: (token:string, user:AuthUser) => void; logout: () => void; setLastBatchId: (id:string) => void; setLastRunId: (id:string) => void }
const SessionContext = createContext<Session | null>(null)
export function SessionProvider({ children }: { children: ReactNode }) {
  const [lastBatchId, setLastBatchId] = useState(() => localStorage.getItem('lastBatchId') || '')
  const [lastRunId, setLastRunId] = useState(() => localStorage.getItem('lastRunId') || '')
  const [token, setToken] = useState(() => localStorage.getItem('authToken') || '')
  const [user, setUser] = useState<AuthUser|null>(() => { try { return JSON.parse(localStorage.getItem('authUser') || 'null') } catch { return null } })
  const persist = (key:string, setter:(value:string)=>void) => (value:string) => { localStorage.setItem(key, value); setter(value) }
  const setAuth = (nextToken:string, nextUser:AuthUser) => { localStorage.setItem('authToken', nextToken); localStorage.setItem('authUser', JSON.stringify(nextUser)); setToken(nextToken); setUser(nextUser) }
  const logout = () => { localStorage.removeItem('authToken'); localStorage.removeItem('authUser'); setToken(''); setUser(null) }
  return <SessionContext.Provider value={{ token, user, setAuth, logout, lastBatchId, lastRunId, setLastBatchId: persist('lastBatchId', setLastBatchId), setLastRunId: persist('lastRunId', setLastRunId) }}>{children}</SessionContext.Provider>
}
export function useSession() { const context = useContext(SessionContext); if (!context) throw new Error('SessionProvider missing'); return context }
