import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { DocumentOut, MeResponse } from '@shared/index'
import { DocumentsPanel } from '@/features/sources/DocumentsPanel'
import { SessionContext } from '@/hooks/useSession'
import { clearSessionState, setSessionState } from '@/services/api'

const MiB = 1024 * 1024
const LIST = '/api/documents'
const UPLOAD_ID = '11111111-1111-4111-8111-111111111111'
const limits = { max_upload_mb: 1, upload_types: ['pdf', 'md'], max_docs: 3, chat_messages_per_hour: 10 }
const me: MeResponse = { tier: 'user', email: 'a@b.co', limits, document_count: 0, guest_expires_at: null }

function doc(over: Partial<DocumentOut> = {}): DocumentOut {
  return {
    id: UPLOAD_ID,
    source: 'notes.pdf',
    status: 'ready',
    error: null,
    attempts: 1,
    created_at: '2026-11-12T00:00:00Z',
    ...over,
  }
}

// Fake server: the list is a live array, so handlers can add, change or remove rows.
type Handler = (method: string, url: string, init: RequestInit) => Response | Promise<Response> | undefined

// The next list requests stay open until the test releases them or their signal aborts, like a slow network.
let holdNextLists = 0
const held: { signal?: AbortSignal; release: (res: Response) => void }[] = []

function holdList(signal?: AbortSignal) {
  return new Promise<Response>((resolve, reject) => {
    signal?.addEventListener('abort', () => reject(new DOMException('The operation was aborted.', 'AbortError')))
    held.push({ signal, release: resolve })
  })
}

function mockServer(docs: DocumentOut[], handle: Handler = () => undefined) {
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    if (method === 'GET' && url === LIST) {
      if (holdNextLists > 0) {
        holdNextLists--
        return holdList(init.signal ?? undefined)
      }
      return Response.json(docs)
    }
    const res = handle(method, url, init)
    if (res) return res
    throw new Error(`unexpected ${method} ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function requestsWith(fetchMock: ReturnType<typeof mockServer>, method: string) {
  return fetchMock.mock.calls.filter(([, init]) => (init?.method ?? 'GET') === method).map(([url]) => url)
}

function renderPanel(docLimits = limits) {
  const session = { me: { ...me, limits: docLimits }, sessionVersion: 0, refresh: async () => {} }
  return render(
    <SessionContext.Provider value={session}>
      <DocumentsPanel />
    </SessionContext.Provider>,
  )
}

// Lets pending promises (fetch mocks, state updates) settle without real waits.
const flush = () => act(() => new Promise<void>((resolve) => setTimeout(resolve, 0)))

// jsdom keeps a file input's selection internally, so neither `files` overrides nor fireEvent.change reach
// FormData. The stub adds the chosen file to the file form's FormData, as a browser would.
let chosen: File | null = null

function chooseFile(file: File) {
  chosen = file
}

function upload(file: File) {
  chooseFile(file)
  fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
}

beforeEach(() => {
  setSessionState(me)
  const RealFormData = FormData
  vi.stubGlobal(
    'FormData',
    class extends RealFormData {
      constructor(form?: HTMLFormElement) {
        super(form)
        const input = form?.querySelector<HTMLInputElement>('input[type=file]')
        if (chosen && input) this.set(input.name, chosen)
      }
    },
  )
})

afterEach(() => {
  chosen = null
  holdNextLists = 0
  held.length = 0
  clearSessionState()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

test.each([
  ['oversize', new File([new Uint8Array(MiB + 1)], 'big.pdf'), `File is larger than ${limits.max_upload_mb} MB.`],
  ['disallowed extension', new File(['x'], 'data.csv'), 'Unsupported file type. Allowed: .pdf, .md.'],
])('%s file is rejected client-side with no upload request', async (_name, file, message) => {
  const fetchMock = mockServer([])
  renderPanel()
  await flush()
  upload(file)
  expect(await screen.findByRole('alert')).toHaveTextContent(message)
  expect(requestsWith(fetchMock, 'POST')).toEqual([])
})

test('a file exactly at the size limit is uploaded', async () => {
  const docs: DocumentOut[] = []
  const fetchMock = mockServer(docs, (method, url) => {
    if (method === 'POST' && url === LIST) {
      docs.push(doc({ status: 'pending' }))
      return Response.json(docs[0], { status: 202 })
    }
  })
  renderPanel()
  await flush()
  upload(new File([new Uint8Array(limits.max_upload_mb * MiB)], 'exact.pdf'))
  await flush()
  expect(requestsWith(fetchMock, 'POST')).toEqual([LIST])
})

test('at the document cap the upload controls are disabled and nothing is posted', async () => {
  const docs = [doc({ id: '1', source: 'a.pdf' }), doc({ id: '2', source: 'b.pdf' }), doc({ id: '3', source: 'c.pdf' })]
  const fetchMock = mockServer(docs)
  renderPanel()
  await flush()
  expect(screen.getByRole('status')).toHaveTextContent(`Document limit reached (${limits.max_docs}). Delete one to add more.`)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Upload a file')).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Upload' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Add URL' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
  expect(requestsWith(fetchMock, 'POST')).toEqual([])
})

test('upload posts multipart with the file part and shows the pending item', async () => {
  const docs: DocumentOut[] = []
  const fetchMock = mockServer(docs, (method, url) => {
    if (method === 'POST' && url === LIST) {
      docs.push(doc({ status: 'pending' }))
      return Response.json(docs[0], { status: 202 })
    }
  })
  renderPanel()
  await flush()
  upload(new File(['hello'], 'notes.pdf', { type: 'application/pdf' }))
  await flush()

  const [, init] = fetchMock.mock.calls.find(([, i]) => i?.method === 'POST') ?? []
  expect(init?.body).toBeInstanceOf(FormData)
  const body = init?.body as FormData
  const fileInput = document.querySelector<HTMLInputElement>('input[type=file]')
  expect([...body.keys()]).toEqual([fileInput?.name])
  expect((body.get('file') as File).name).toBe('notes.pdf')
  expect(screen.getByRole('listitem')).toHaveTextContent('notes.pdf')
  expect(screen.getByRole('listitem')).toHaveTextContent('pending')
})

test('polls every 3 s while a document is pending and stops once it is ready', async () => {
  const docs = [doc({ status: 'pending' })]
  const fetchMock = mockServer(docs)
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  renderPanel()
  await flush()
  expect(requestsWith(fetchMock, 'GET')).toHaveLength(1)

  await act(async () => vi.advanceTimersByTime(3000))
  await flush()
  expect(requestsWith(fetchMock, 'GET')).toHaveLength(2)

  docs[0] = doc({ status: 'ready' })
  await act(async () => vi.advanceTimersByTime(3000))
  await flush()
  expect(requestsWith(fetchMock, 'GET')).toHaveLength(3)
  expect(screen.getByText('ready')).toBeInTheDocument()

  await act(async () => vi.advanceTimersByTime(9000))
  await flush()
  expect(requestsWith(fetchMock, 'GET')).toHaveLength(3)
})

test('a processing document also keeps polling', async () => {
  const docs = [doc({ status: 'processing' })]
  const fetchMock = mockServer(docs)
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  renderPanel()
  await flush()
  await act(async () => vi.advanceTimersByTime(3000))
  await flush()
  expect(requestsWith(fetchMock, 'GET')).toHaveLength(2)
})

test('polling stops once the panel unmounts', async () => {
  const fetchMock = mockServer([doc({ status: 'pending' })])
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  const { unmount } = renderPanel()
  await flush()
  unmount()
  const before = requestsWith(fetchMock, 'GET').length
  await act(async () => vi.advanceTimersByTime(9000))
  expect(requestsWith(fetchMock, 'GET')).toHaveLength(before)
})

test('a stale list never wins: Delete aborts the held poll and the deleted row stays gone', async () => {
  const docs = [doc({ id: '1', source: 'a.pdf', status: 'pending' }), doc({ id: UPLOAD_ID, source: 'notes.pdf' })]
  mockServer(docs, (method, url) => {
    if (method === 'DELETE' && url === `${LIST}/${UPLOAD_ID}`) {
      docs.splice(1, 1)
      return new Response(null, { status: 204 })
    }
  })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  renderPanel()
  await flush()
  holdNextLists = 1
  await act(async () => vi.advanceTimersByTime(3000))
  expect(held).toHaveLength(1)

  fireEvent.click(screen.getByRole('button', { name: 'Delete notes.pdf' }))
  await flush()

  expect(held[0]?.signal?.aborted).toBe(true)
  expect(screen.getByRole('listitem')).toHaveTextContent('a.pdf')
  expect(screen.queryByText('notes.pdf')).not.toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('a poll tick does not send a second list while one is in flight, nor abort it', async () => {
  const docs = [doc({ status: 'pending' })]
  const fetchMock = mockServer(docs)
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  renderPanel()
  await flush()
  holdNextLists = 1
  await act(async () => vi.advanceTimersByTime(3000))
  await act(async () => vi.advanceTimersByTime(6000))

  expect(requestsWith(fetchMock, 'GET')).toHaveLength(2)
  expect(held[0]?.signal?.aborted).toBe(false)

  docs[0] = doc({ status: 'ready' })
  held[0]?.release(Response.json(docs))
  await flush()
  expect(screen.getByText('ready')).toBeInTheDocument()
})

test('a second Retry click while the first is running sends no request, and the item is disabled meanwhile', async () => {
  const docs = [doc({ status: 'failed', error: 'Could not parse the PDF.' })]
  let finish: (res: Response) => void = () => {}
  const fetchMock = mockServer(docs, (method, url) => {
    if (method === 'POST' && url === `${LIST}/${UPLOAD_ID}/retry`) return new Promise<Response>((resolve) => (finish = resolve))
  })
  renderPanel()
  await flush()
  const retry = screen.getByRole('button', { name: 'Retry notes.pdf' })
  fireEvent.click(retry)
  fireEvent.click(retry)

  expect(requestsWith(fetchMock, 'POST')).toEqual([`${LIST}/${UPLOAD_ID}/retry`])
  expect(screen.getByRole('button', { name: 'Retry notes.pdf' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Delete notes.pdf' })).toBeDisabled()

  docs[0] = doc({ status: 'pending' })
  finish(Response.json(docs[0], { status: 202 }))
  await flush()
  expect(screen.getByRole('listitem')).toHaveTextContent('pending')
  expect(requestsWith(fetchMock, 'POST')).toHaveLength(1)
})

test('URL submit posts the url as JSON to /documents/url', async () => {
  const docs: DocumentOut[] = []
  const fetchMock = mockServer(docs, (method, url) => {
    if (method === 'POST' && url === '/api/documents/url') {
      docs.push(doc({ status: 'pending', source: 'https://example.com/page' }))
      return Response.json(docs[0], { status: 202 })
    }
  })
  renderPanel()
  await flush()
  fireEvent.change(screen.getByLabelText('Or add a URL'), { target: { value: 'https://example.com/page' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add URL' }))
  await flush()

  const [, init] = fetchMock.mock.calls.find(([url]) => url === '/api/documents/url') ?? []
  expect(init?.method).toBe('POST')
  expect(JSON.parse(init?.body as string)).toEqual({ url: 'https://example.com/page' })
  expect(screen.getByRole('listitem')).toHaveTextContent('https://example.com/page')
})

test('a failed document shows its error and Retry posts to its retry endpoint', async () => {
  const docs = [doc({ status: 'failed', error: 'Could not parse the PDF.' })]
  const fetchMock = mockServer(docs, (method, url) => {
    if (method === 'POST' && url === `${LIST}/${UPLOAD_ID}/retry`) {
      docs[0] = doc({ status: 'pending' })
      return Response.json(docs[0], { status: 202 })
    }
  })
  renderPanel()
  await flush()
  expect(screen.getByText('Could not parse the PDF.')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Retry notes.pdf' }))
  await flush()
  expect(requestsWith(fetchMock, 'POST')).toEqual([`${LIST}/${UPLOAD_ID}/retry`])
  expect(screen.getByRole('listitem')).toHaveTextContent('pending')
})

test('Delete with confirm sends DELETE and the item disappears after reload', async () => {
  const docs = [doc()]
  const fetchMock = mockServer(docs, (method, url) => {
    if (method === 'DELETE' && url === `${LIST}/${UPLOAD_ID}`) {
      docs.length = 0
      return new Response(null, { status: 204 })
    }
  })
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
  renderPanel()
  await flush()
  fireEvent.click(screen.getByRole('button', { name: 'Delete notes.pdf' }))
  await flush()
  expect(confirm).toHaveBeenCalledWith('Delete notes.pdf?')
  expect(requestsWith(fetchMock, 'DELETE')).toEqual([`${LIST}/${UPLOAD_ID}`])
  expect(screen.queryByText('notes.pdf')).not.toBeInTheDocument()
  expect(screen.getByText('No documents yet. Upload a file or add a URL.')).toBeInTheDocument()
})

test('Delete with confirm declined sends no request', async () => {
  const fetchMock = mockServer([doc()])
  vi.spyOn(window, 'confirm').mockReturnValue(false)
  renderPanel()
  await flush()
  fireEvent.click(screen.getByRole('button', { name: 'Delete notes.pdf' }))
  await flush()
  expect(requestsWith(fetchMock, 'DELETE')).toEqual([])
  expect(screen.getByText('notes.pdf')).toBeInTheDocument()
})

test('a processing document has no Delete button', async () => {
  mockServer([doc({ status: 'processing' })])
  renderPanel()
  await flush()
  expect(screen.getByText('notes.pdf')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Delete notes.pdf' })).not.toBeInTheDocument()
})

test.each([
  [409, 'That file was already uploaded.', {}, 'That file was already uploaded.'],
  [413, 'File is too large for your tier.', {}, 'File is too large for your tier.'],
  [415, 'This file type is not allowed.', {}, 'This file type is not allowed.'],
  [422, 'The file could not be read.', {}, 'The file could not be read.'],
  [429, 'Too many uploads.', { 'Retry-After': '42' }, 'Too many uploads. Try again in 42 seconds.'],
])('upload error %i shows its message in an alert', async (status, detail, headers, message) => {
  mockServer([], (method, url) => {
    if (method === 'POST' && url === LIST) return Response.json({ code: 'error', detail }, { status, headers })
  })
  renderPanel()
  await flush()
  upload(new File(['hello'], 'notes.pdf'))
  expect(await screen.findByRole('alert')).toHaveTextContent(message)
})

test('source renders as literal text, never as HTML', async () => {
  const source = '<img src=x onerror=alert(1)>'
  mockServer([doc({ source })])
  const { container } = renderPanel()
  await flush()
  expect(screen.getByText(source)).toBeInTheDocument()
  expect(container.querySelector('img')).toBeNull()
})
