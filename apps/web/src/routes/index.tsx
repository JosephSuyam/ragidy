import { useSyncExternalStore } from 'react'
import { LoginPage } from '@/features/authentication/LoginPage'
import { AppShell } from '@/components/layout/AppShell'

function subscribe(onChange: () => void) {
  window.addEventListener('popstate', onChange)
  return () => window.removeEventListener('popstate', onChange)
}

export function Router() {
  const pathname = useSyncExternalStore(subscribe, () => window.location.pathname)
  switch (pathname) {
    case '/login':
      return <LoginPage />
    default:
      return <AppShell />
  }
}
