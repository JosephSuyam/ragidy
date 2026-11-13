import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { DocumentOut, MeResponse } from '@shared/index'
import { AppShell } from '@/components/layout/AppShell'
import { SessionContext } from '@/hooks/useSession'
import { clearSessionState, setSessionState } from '@/services/api'

const DOCS = '/api/documents'
const CHATS = '/api/chats'
const NOTE = 'No ready documents yet. Upload a file or add a URL, then ask.'
const limits = { max_upload_mb: 5, upload_types: ['pdf', 'md'], max_docs: 3, chat_messages_per_hour: 10 }
const me: MeResponse = { tier: 'user', email: 'a@b.co', limits, document_count: 0, guest_expires_at: null }

function doc(over: Partial<DocumentOut> = {}): DocumentOut {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    source: 'notes.pdf',
    status: 'ready',
    error: null,
    attempts: 1,
    created_at: '2026-11-12T00:00:00Z',
    ...over,
  }
}

// The shell mounts both panels. The document list is live so a poll can change it; the chat list stays empty.
function mockServer(docs: DocumentOut[]) {
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    if (method === 'GET' && url === DOCS) return Response.json(docs)
    if (method === 'GET' && url === CHATS) return Response.json([])
    throw new Error(`unexpected ${method} ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const documentGets = (fetchMock: ReturnType<typeof mockServer>) =>
  fetchMock.mock.calls.filter(([url, init]) => url === DOCS && (init?.method ?? 'GET') === 'GET').length

function renderShell() {
  const session = { me, sessionVersion: 0, refresh: async () => {}, guestExpired: false, dismissExpired: () => undefined }
  return render(
    <SessionContext.Provider value={session}>
      <AppShell />
    </SessionContext.Provider>,
  )
}

// Lets pending promises (fetch mocks, state updates) settle without real waits.
const flush = () => act(() => new Promise<void>((resolve) => setTimeout(resolve, 0)))

beforeEach(() => {
  setSessionState(me)
})

afterEach(() => {
  clearSessionState()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

test('with no ready document the hint shows, and it goes once a poll reports one ready', async () => {
  const docs = [doc({ status: 'pending' })]
  const fetchMock = mockServer(docs)
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  renderShell()
  await flush()
  expect(screen.getByRole('note')).toHaveTextContent(NOTE)

  docs[0] = doc({ status: 'ready' })
  await act(async () => vi.advanceTimersByTime(3000))
  await flush()

  expect(screen.queryByRole('note')).not.toBeInTheDocument()
  // The initial load and one poll only: a changed hasReady must not refetch the list.
  expect(documentGets(fetchMock)).toBe(2)
})

test('an empty document list shows the hint', async () => {
  mockServer([])
  renderShell()
  expect(await screen.findByRole('note')).toHaveTextContent(NOTE)
})

test('a ready document means no hint', async () => {
  mockServer([doc()])
  renderShell()
  expect(await screen.findByText('notes.pdf')).toBeInTheDocument()
  expect(screen.queryByRole('note')).not.toBeInTheDocument()
})
