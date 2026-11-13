import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { DocumentOut } from '@shared/index'
import { DocumentItem } from '@/components/documents/DocumentItem'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { UploadForm } from '@/features/upload/UploadForm'
import { useSession } from '@/hooks/useSession'
import { api, errorMessage } from '@/services/api'

const POLL_MS = 3000

export function DocumentsPanel({ onLoaded }: { onLoaded?: (docs: DocumentOut[]) => void }) {
  const { me } = useSession()
  const [docs, setDocs] = useState<DocumentOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [pending, setPending] = useState<ReadonlySet<string>>(new Set())
  const inflight = useRef<AbortController | null>(null)
  const onLoadedRef = useRef(onLoaded)
  useLayoutEffect(() => {
    onLoadedRef.current = onLoaded
  }, [onLoaded])

  // One list request at a time: a newer load aborts the older, so a stale response never wins.
  const load = useCallback(() => {
    inflight.current?.abort()
    const c = new AbortController()
    inflight.current = c
    const settle = () => {
      if (inflight.current === c) inflight.current = null
    }
    return api.get<DocumentOut[]>('/documents', c.signal).then(
      (next) => {
        settle()
        setError(null)
        setDocs(next)
        onLoadedRef.current?.(next)
      },
      (err: unknown) => {
        settle()
        if (!c.signal.aborted) setError(errorMessage(err))
      },
    )
  }, [])

  useEffect(() => {
    void load()
    return () => inflight.current?.abort()
  }, [load])

  const active = !!docs?.some((d) => d.status === 'pending' || d.status === 'processing')
  useEffect(() => {
    if (!active) return
    // Polls never abort: skip the tick while a load is in flight, or a slow list never lands.
    const timer = setInterval(() => {
      if (!inflight.current) void load()
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [active, load])

  const act = (id: string, run: () => Promise<unknown>) => {
    setPending((p) => new Set(p).add(id))
    void run().then(
      () => load(),
      (err: unknown) => setError(errorMessage(err)),
    ).finally(() =>
      setPending((p) => {
        const next = new Set(p)
        next.delete(id)
        return next
      }),
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <UploadForm limits={me.limits} disabled={(docs?.length ?? 0) >= me.limits.max_docs} onAdded={() => void load()} />
      {error && (
        <Alert variant="destructive">
          <AlertDescription className="flex items-center justify-between gap-2">
            {error}
            <Button type="button" size="sm" variant="outline" onClick={() => void load()}>
              Reload
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {docs === null ? (
        !error && <p role="status">Loading documents…</p>
      ) : docs.length === 0 ? (
        <p className="text-sm text-muted-foreground">No documents yet. Upload a file or add a URL.</p>
      ) : (
        <ul aria-label="Document list" className="flex flex-col gap-2">
          {docs.map((d) => (
            <DocumentItem
              key={d.id}
              doc={d}
              busy={pending.has(d.id)}
              onRetry={() => act(d.id, () => api.post(`/documents/${d.id}/retry`))}
              onDelete={() => act(d.id, () => api.delete(`/documents/${d.id}`))}
            />
          ))}
        </ul>
      )}
    </div>
  )
}
