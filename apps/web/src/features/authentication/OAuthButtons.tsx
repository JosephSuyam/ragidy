import { useEffect, useState } from 'react'
import type { ProviderResponse } from '@shared/index'
import { Button } from '@/components/ui/button'
import { api } from '@/services/api'

export function OAuthButtons() {
  const [providers, setProviders] = useState<ProviderResponse[]>([])

  useEffect(() => {
    const controller = new AbortController()
    api
      .get<ProviderResponse[]>('/auth/providers', controller.signal)
      .then(setProviders)
      .catch(() => undefined) // password sign-in still works without OAuth
    return () => controller.abort()
  }, [])

  if (providers.length === 0) return null
  return (
    <div className="flex flex-col gap-2">
      {providers.map((p) => (
        <Button key={p.id} variant="outline" asChild>
          <a href={`/api/auth/oauth/${encodeURIComponent(p.id)}/start`}>Continue with {p.name}</a>
        </Button>
      ))}
    </div>
  )
}
