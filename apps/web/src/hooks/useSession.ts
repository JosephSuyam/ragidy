import { createContext, useContext } from 'react'
import type { MeResponse } from '@shared/index'

export type Session = { me: MeResponse; sessionVersion: number; refresh: () => Promise<void> }

export const SessionContext = createContext<Session | null>(null)

export function useSession() {
  const session = useContext(SessionContext)
  if (!session) throw new Error('useSession needs SessionProvider')
  return session
}
