import { useState, type FormEvent } from 'react'
import type { DocumentOut, Limits } from '@shared/index'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, errorMessage } from '@/services/api'

const EXTENSIONS: Record<string, string[]> = { html: ['.html', '.htm'] }
const MAX_URL_LENGTH = 2048

type Props = { limits: Limits; disabled: boolean; onAdded: () => void }

export function UploadForm({ limits, disabled, onAdded }: Props) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const allowed = limits.upload_types.flatMap((t) => EXTENSIONS[t] ?? [`.${t}`])

  // Validators return an error message or the request to send.
  const submit = (e: FormEvent<HTMLFormElement>, build: (data: FormData) => string | Promise<DocumentOut>) => {
    e.preventDefault()
    const form = e.currentTarget
    const result = build(new FormData(form))
    if (typeof result === 'string') return setError(result)
    setError(null)
    setBusy(true)
    result.then(
      () => {
        form.reset()
        setBusy(false)
        onAdded()
      },
      (err: unknown) => {
        setError(errorMessage(err))
        setBusy(false)
      },
    )
  }

  const buildFile = (data: FormData) => {
    const file = data.get('file')
    if (!(file instanceof File) || !file.name) return 'Choose a file.'
    if (!allowed.some((ext) => file.name.toLowerCase().endsWith(ext))) return `Unsupported file type. Allowed: ${allowed.join(', ')}.`
    if (file.size > limits.max_upload_mb * 1024 * 1024) return `File is larger than ${limits.max_upload_mb} MB.`
    const body = new FormData()
    body.append('file', file)
    return api.post<DocumentOut>('/documents', body)
  }

  const buildUrl = (data: FormData) => {
    const url = String(data.get('url') ?? '').trim()
    if (!url) return 'Enter a URL.'
    if (url.length > MAX_URL_LENGTH) return `URL is longer than ${MAX_URL_LENGTH} characters.`
    return api.post<DocumentOut>('/documents/url', { url })
  }

  const off = disabled || busy

  return (
    <div className="flex flex-col gap-4">
      {disabled && (
        <Alert role="status">
          <AlertDescription>Document limit reached ({limits.max_docs}). Delete one to add more.</AlertDescription>
        </Alert>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <form onSubmit={(e) => submit(e, buildFile)} className="flex flex-col gap-2">
        <Label htmlFor="document-file">Upload a file</Label>
        <Input id="document-file" name="file" type="file" accept={allowed.join(',')} disabled={off} />
        <Button type="submit" disabled={off}>
          Upload
        </Button>
      </form>
      <form onSubmit={(e) => submit(e, buildUrl)} className="flex flex-col gap-2">
        <Label htmlFor="document-url">Or add a URL</Label>
        <Input id="document-url" name="url" type="url" placeholder="https://" disabled={off} />
        <Button type="submit" disabled={off}>
          Add URL
        </Button>
      </form>
    </div>
  )
}
