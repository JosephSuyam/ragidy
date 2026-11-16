import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useSession } from '@/hooks/useSession'
import { navigate } from '@/routes/navigate'
import { api, clearSessionState } from '@/services/api'

export function Header() {
  const { me, refresh } = useSession()
  const [failed, setFailed] = useState(false)

  async function signOut() {
    setFailed(false)
    clearSessionState()
    try {
      await api.post('/auth/logout')
      await refresh()
    } catch {
      setFailed(true)
    }
  }

  return (
    <header className="flex flex-wrap items-center gap-3 border-b px-6 py-3">
      <h1 className="text-lg font-semibold tracking-tight">Ragidy</h1>
      <Badge variant="secondary">{me.tier}</Badge>
      <div className="ml-auto flex flex-wrap items-center gap-3 text-sm">
        {me.email && <span>{me.email}</span>}
        {me.guest_expires_at && (
          <span className="text-muted-foreground">
            Guest session expires {new Date(me.guest_expires_at).toLocaleString()}
          </span>
        )}
        {failed && <span role="alert">Sign out failed. Try again.</span>}
        {me.tier === 'user' ? (
          <Button variant="outline" size="sm" onClick={() => void signOut()}>
            Sign out
          </Button>
        ) : (
          <Button variant="outline" size="sm" asChild>
            <a
              href="/login"
              onClick={(e) => {
                e.preventDefault()
                navigate('/login')
              }}
            >
              Sign in
            </a>
          </Button>
        )}
      </div>
    </header>
  )
}
