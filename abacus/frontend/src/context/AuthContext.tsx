import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import type { Session, User } from '@supabase/supabase-js'
import { supabase } from '../supabaseClient'

type AppRole = 'manager' | 'driver'
type AuthState = { session: Session | null, user: User | null, role: AppRole, loading: boolean, signOut: () => Promise<void> }
const AuthContext = createContext<AuthState>({ session: null, user: null, role: 'manager', loading: true, signOut: async () => {} })

async function resolveRole(session: Session | null): Promise<AppRole> {
  if (!session) return 'manager'
  try {
    const { data, error } = await supabase.from('profiles').select('role').eq('id', session.user.id).maybeSingle()
    if (!error && data?.role === 'driver') return 'driver'
  } catch {
    // Backward compatibility: if the new role migration is not applied, preserve the old manager UI.
  }
  return 'manager'
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [role, setRole] = useState<AppRole>('manager')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    const applySession = async (next: Session | null) => {
      if (!active) return
      setSession(next)
      const nextRole = await resolveRole(next)
      if (active) { setRole(nextRole); setLoading(false) }
    }
    supabase.auth.getSession().then(({ data }) => { void applySession(data.session) }).catch(() => { if (active) setLoading(false) })
    const { data: sub } = supabase.auth.onAuthStateChange((_event, next) => {
      // Defer the profile query until after Supabase releases its auth callback lock.
      Promise.resolve().then(() => applySession(next))
    })
    return () => { active = false; sub.subscription.unsubscribe() }
  }, [])

  const signOut = async () => { await supabase.auth.signOut(); setSession(null); setRole('manager') }
  return <AuthContext.Provider value={{ session, user: session?.user ?? null, role, loading, signOut }}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
