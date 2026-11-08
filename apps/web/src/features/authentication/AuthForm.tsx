import { useState, type FormEvent } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useSession } from '@/hooks/useSession'
import { navigate } from '@/routes/navigate'
import { ApiError, api } from '@/services/api'

function message(err: unknown) {
  if (!(err instanceof ApiError)) return 'Something went wrong. Try again.'
  switch (err.code) {
    case 'invalid_credentials':
      return 'Wrong email or password.'
    case 'email_taken':
      return 'An account with this email already exists.'
    case 'validation_error':
      return `Check your input: ${err.detail}`
    case 'rate_limited':
      return err.retryAfter === undefined
        ? 'Too many attempts. Try again later.'
        : `Too many attempts. Try again in ${err.retryAfter} seconds.`
    default:
      return err.detail
  }
}

export function AuthForm() {
  const { refresh } = useSession()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const registering = mode === 'register'

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    setBusy(true)
    setError(null)
    try {
      await api.post(registering ? '/auth/register' : '/auth/login', {
        email: form.get('email'),
        password: form.get('password'),
      })
      navigate('/')
      await refresh()
    } catch (err) {
      setError(message(err))
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(e) => void onSubmit(e)} className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor="email">Email</Label>
        <Input id="email" name="email" type="email" autoComplete="email" required maxLength={254} />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete={registering ? 'new-password' : 'current-password'}
          required
          minLength={registering ? 8 : undefined}
          maxLength={128}
        />
      </div>
      {error && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <Button type="submit" disabled={busy}>
        {registering ? 'Create account' : 'Sign in'}
      </Button>
      <Button type="button" variant="link" onClick={() => { setMode(registering ? 'login' : 'register'); setError(null) }}>
        {registering ? 'Have an account? Sign in' : 'No account? Create one'}
      </Button>
    </form>
  )
}
