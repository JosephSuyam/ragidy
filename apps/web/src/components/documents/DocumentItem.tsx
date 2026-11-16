import type { DocumentOut } from '@shared/index'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

type Props = {
  doc: DocumentOut
  busy?: boolean
  onRetry: () => void
  onDelete: () => void
}

export function DocumentItem({ doc, busy, onRetry, onDelete }: Props) {
  const failed = doc.status === 'failed'
  return (
    <li className="flex flex-col gap-2 rounded-md border p-3">
      <p className="break-all text-sm">{doc.source}</p>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={failed ? 'destructive' : doc.status === 'ready' ? 'default' : 'secondary'}>{doc.status}</Badge>
        {failed && (
          <Button type="button" size="sm" variant="outline" aria-label={`Retry ${doc.source}`} disabled={busy} onClick={onRetry}>
            Retry
          </Button>
        )}
        {doc.status !== 'processing' && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            aria-label={`Delete ${doc.source}`}
            disabled={busy}
            onClick={() => window.confirm(`Delete ${doc.source}?`) && onDelete()}
          >
            Delete
          </Button>
        )}
      </div>
      {failed && doc.error && <p className="break-words text-sm text-destructive">{doc.error}</p>}
    </li>
  )
}
