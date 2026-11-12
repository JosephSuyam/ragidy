import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { MeResponse } from '@shared/index'
import { SessionContext } from '@/hooks/useSession'
import { api, setSessionHandler, setSessionState } from '@/services/api'

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<MeResponse | null>(null)
  const [failed, setFailed] = useState(false)
  const [sessionVersion, setVersion] = useState(0)

  const meRef = useRef(me)
  useLayoutEffect(() => {
    meRef.current = me
  }, [me])

  const apply = useCallback((next: MeResponse, remount = true) => {
    setSessionState(next)
    setMe(next)
    if (remount) setVersion((v) => v + 1)
  }, [])

  const load = useCallback(
    (signal?: AbortSignal) =>
      api.get<MeResponse>('/me', signal).then(
        (next) => apply(next),
        () => {
          if (!signal?.aborted) setFailed(true)
        },
      ),
    [apply],
  )

  useEffect(() => {
    const c = new AbortController()
    void load(c.signal)
    return () => c.abort()
  }, [load])

  // Cookies are shared across tabs: re-check the owner when this tab comes back.
  useEffect(() => {
    const c = new AbortController()
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return
      api.get<MeResponse>('/me', c.signal).then(
        (next) => {
          const prev = meRef.current
          const ownerChanged =
            !!prev &&
            (prev.tier !== next.tier ||
              prev.email !== next.email ||
              prev.guest_expires_at !== next.guest_expires_at)
          apply(next, ownerChanged)
        },
        () => undefined,
      )
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      c.abort()
    }
  }, [apply])

  useEffect(() => {
    setSessionHandler(apply)
    return () => setSessionHandler()
  }, [apply])

  const value = useMemo(() => (me ? { me, sessionVersion, refresh: () => load() } : null), [me, sessionVersion, load])

  if (failed)
    return (
      <div role="alert" className="p-6">
        <p>Could not reach the server.</p>
        <button type="button" className="underline" onClick={() => {
            setFailed(false)
            void load()
          }}>
          Retry
        </button>
      </div>
    )
  if (!value) return <p role="status" className="p-6">Loading…</p>
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}
