import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { ChatOut, CitationOut, MeResponse, MessageOut } from '@shared/index'
import { ChatPanel } from '@/features/chat/ChatPanel'
import { SessionContext } from '@/hooks/useSession'
import { clearSessionState, setSessionState } from '@/services/api'

const CHATS = '/api/chats'
const ALPHA: ChatOut = { id: '11111111-1111-4111-8111-111111111111', title: 'Alpha', created_at: '2026-11-12T00:00:00Z' }
const BETA: ChatOut = { id: '22222222-2222-4222-8222-222222222222', title: 'Beta', created_at: '2026-11-12T00:00:00Z' }
const NEW_ID = '33333333-3333-4333-8333-333333333333'
const limits = { max_upload_mb: 5, upload_types: ['pdf', 'md'], max_docs: 3, chat_messages_per_hour: 10 }
const user: MeResponse = { tier: 'user', email: 'a@b.co', limits, document_count: 0, guest_expires_at: null }
const citation: CitationOut = {
  document_id: '44444444-4444-4444-8444-444444444444',
  source: 'notes.pdf',
  page: 3,
  snippet: 'The retention period is 30 days.',
}

type Handler = (method: string, url: string, init: RequestInit) => Response | Promise<Response> | undefined

// The handler sees every request first. Unhandled GETs get the chat list and history; anything else fails the test.
function mockServer(chats: ChatOut[], handle: Handler = () => undefined, history: Record<string, MessageOut[]> = {}) {
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    const res = await handle(method, url, init)
    if (res) return res
    if (method === 'GET' && url === CHATS) return Response.json(chats)
    const past = /^\/api\/chats\/([^/]+)\/messages$/.exec(url)
    if (method === 'GET' && past) return Response.json(history[past[1]] ?? [])
    throw new Error(`unexpected ${method} ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function requestsWith(fetchMock: ReturnType<typeof mockServer>, method: string) {
  return fetchMock.mock.calls.filter(([, init]) => (init?.method ?? 'GET') === method).map(([url]) => url)
}

function postBody(fetchMock: ReturnType<typeof mockServer>, url: string) {
  const [, init] = fetchMock.mock.calls.find(([u, i]) => u === url && i?.method === 'POST') ?? []
  return JSON.parse(init?.body as string)
}

// A stream the test feeds event by event. Aborting the request errors it, as a real fetch body does.
function openStream(signal: AbortSignal) {
  const encoder = new TextEncoder()
  let controller!: ReadableStreamDefaultController<Uint8Array>
  signal.addEventListener('abort', () => controller.error(new DOMException('The operation was aborted.', 'AbortError')))
  const body = new ReadableStream<Uint8Array>({ start: (c) => (controller = c) })
  return {
    signal,
    response: new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }),
    push: (event: string, data: unknown) => controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)),
    close: () => controller.close(),
    fail: (err: Error) => controller.error(err),
  }
}
type Stream = ReturnType<typeof openStream>

function streamHandler(streams: Stream[]): Handler {
  return (method, url, init) => {
    if (method !== 'POST' || !/^\/api\/chats\/[^/]+\/messages$/.test(url)) return undefined
    const stream = openStream(init.signal as AbortSignal)
    streams.push(stream)
    return stream.response
  }
}

// A response the test settles by hand, to keep a request pending for as long as a case needs.
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/

function renderPanel(chatLimits = limits) {
  const session = { me: { ...user, limits: chatLimits }, sessionVersion: 0, refresh: async () => {} }
  return render(
    <SessionContext.Provider value={session}>
      <ChatPanel />
    </SessionContext.Provider>,
  )
}

// Lets pending promises (fetch mocks, aborts, state updates) settle without real waits.
const flush = () => act(() => new Promise<void>((resolve) => setTimeout(resolve, 0)))

async function selectChat(title: string) {
  fireEvent.click(await screen.findByRole('button', { name: title }))
  await waitFor(() => expect(screen.queryByText('Loading messages…')).not.toBeInTheDocument())
}

function ask(text: string) {
  fireEvent.change(screen.getByLabelText('Message'), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
}

// The message body sits right after its sr-only role label.
const bubble = (role: 'You' | 'Assistant') => screen.queryByText(role)?.nextElementSibling?.textContent

beforeEach(() => {
  setSessionState(user)
})

afterEach(() => {
  clearSessionState()
  vi.unstubAllGlobals()
})

test('the chat list loads from GET /api/chats', async () => {
  mockServer([ALPHA, BETA])
  renderPanel()
  const list = await screen.findByRole('list', { name: 'Chat list' })
  expect(within(list).getAllByRole('button').map((b) => b.textContent)).toEqual(['Alpha', 'Beta'])
})

test('an empty chat list shows the empty state', async () => {
  mockServer([])
  renderPanel()
  expect(await screen.findByText('No chats yet. Ask a question to start one.')).toBeInTheDocument()
})

test('selecting a chat loads its history with citations and marks it current', async () => {
  mockServer([ALPHA, BETA], undefined, {
    [BETA.id]: [
      { role: 'user', content: 'Where is retention set?', citations: [] },
      {
        role: 'assistant',
        content: 'In the policy.',
        citations: [citation, { ...citation, source: 'faq.md', page: null, snippet: 'Short answer.' }],
      },
    ],
  })
  renderPanel()
  await selectChat('Beta')

  expect(screen.getByText('Where is retention set?')).toBeInTheDocument()
  expect(bubble('Assistant')).toBe('In the policy.')
  const [first, second] = within(screen.getByRole('list', { name: 'Sources' })).getAllByRole('listitem')
  expect(first).toHaveTextContent('notes.pdf, page 3: The retention period is 30 days.')
  expect(second).toHaveTextContent('faq.md: Short answer.')
  expect(second).not.toHaveTextContent('page')
  expect(screen.getByRole('button', { name: 'Beta' })).toHaveAttribute('aria-current', 'true')
  expect(screen.getByRole('button', { name: 'Alpha' })).not.toHaveAttribute('aria-current')
})

test('the first send titles the chat with the first 200 characters, posts to it, and selects it', async () => {
  const streams: Stream[] = []
  const stream = streamHandler(streams)
  const question = 'q'.repeat(250)
  const fetchMock = mockServer([ALPHA], (method, url, init) => {
    if (method === 'POST' && url === CHATS) {
      const { title } = JSON.parse(init.body as string)
      return Response.json({ id: NEW_ID, title, created_at: ALPHA.created_at }, { status: 201 })
    }
    return stream(method, url, init)
  })
  renderPanel()
  await screen.findByRole('button', { name: 'Alpha' })

  ask(question)
  await waitFor(() => expect(streams).toHaveLength(1))

  expect(postBody(fetchMock, CHATS)).toEqual({ title: 'q'.repeat(200) })
  expect(postBody(fetchMock, `${CHATS}/${NEW_ID}/messages`)).toEqual({ content: question })
  const list = screen.getByRole('list', { name: 'Chat list' })
  expect(within(list).getByRole('button', { name: 'q'.repeat(200) })).toHaveAttribute('aria-current', 'true')
  expect(within(list).getByRole('button', { name: 'Alpha' })).not.toHaveAttribute('aria-current')
  streams[0].push('done', {})
  streams[0].close()
})

test('the user message shows at once and tokens append as they arrive', async () => {
  const streams: Stream[] = []
  mockServer([ALPHA], streamHandler(streams), { [ALPHA.id]: [] })
  renderPanel()
  await selectChat('Alpha')

  ask('Hi there')
  expect(bubble('You')).toBe('Hi there')
  expect(bubble('Assistant')).toBe('')
  await waitFor(() => expect(streams).toHaveLength(1))

  const stream = streams[0]
  stream.push('token', { text: 'Hel' })
  await waitFor(() => expect(bubble('Assistant')).toBe('Hel'))
  stream.push('token', { text: 'lo' })
  await waitFor(() => expect(bubble('Assistant')).toBe('Hello'))
  stream.push('token', { text: ' world' })
  await waitFor(() => expect(bubble('Assistant')).toBe('Hello world'))
  stream.push('done', {})
  stream.close()
})

test('citations render after the citations event, not before', async () => {
  const streams: Stream[] = []
  mockServer([ALPHA], streamHandler(streams), { [ALPHA.id]: [] })
  renderPanel()
  await selectChat('Alpha')

  ask('Where?')
  await waitFor(() => expect(streams).toHaveLength(1))
  const stream = streams[0]
  stream.push('token', { text: 'In the policy.' })
  await waitFor(() => expect(bubble('Assistant')).toBe('In the policy.'))
  expect(screen.queryByRole('list', { name: 'Sources' })).not.toBeInTheDocument()

  stream.push('citations', [citation])
  expect(await screen.findByRole('list', { name: 'Sources' })).toHaveTextContent(
    'notes.pdf, page 3: The retention period is 30 days.',
  )
  stream.push('done', {})
  stream.close()
})

test('the composer is read-only while streaming and back to normal once the stream ends', async () => {
  const streams: Stream[] = []
  mockServer([ALPHA], streamHandler(streams), { [ALPHA.id]: [] })
  renderPanel()
  await selectChat('Alpha')

  ask('Question')
  await waitFor(() => expect(streams).toHaveLength(1))
  const box = screen.getByLabelText('Message')
  expect(box).toHaveAttribute('readonly')
  expect(box).not.toBeDisabled()
  expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()

  streams[0].push('done', {})
  streams[0].close()
  await waitFor(() => expect(box).not.toHaveAttribute('readonly'))
  fireEvent.change(box, { target: { value: 'Next' } })
  expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled()
})

test('an error event after tokens removes the partial answer, shows its detail, and keeps the question', async () => {
  const streams: Stream[] = []
  mockServer([ALPHA], streamHandler(streams), { [ALPHA.id]: [] })
  renderPanel()
  await selectChat('Alpha')

  ask('Will it fail?')
  await waitFor(() => expect(streams).toHaveLength(1))
  streams[0].push('token', { text: 'Partial' })
  await waitFor(() => expect(bubble('Assistant')).toBe('Partial'))
  streams[0].push('error', { code: 'answer_failed', detail: 'The model is unavailable. Try again.' })
  streams[0].close()

  expect(await screen.findByRole('alert')).toHaveTextContent('The model is unavailable. Try again.')
  expect(screen.queryByText('Partial')).not.toBeInTheDocument()
  expect(screen.queryByText('Assistant')).not.toBeInTheDocument()
  expect(screen.getByText('Will it fail?')).toBeInTheDocument()
})

test('a 429 before the stream shows the retry hint and rolls back the optimistic messages', async () => {
  mockServer(
    [ALPHA],
    (method, url) => {
      if (method === 'POST' && url === `${CHATS}/${ALPHA.id}/messages`) {
        return Response.json({ code: 'rate_limited', detail: 'Hourly message limit reached.' }, { status: 429, headers: { 'Retry-After': '30' } })
      }
    },
    { [ALPHA.id]: [{ role: 'user', content: 'Earlier?', citations: [] }, { role: 'assistant', content: 'Earlier answer.', citations: [] }] },
  )
  renderPanel()
  await selectChat('Alpha')

  ask('Another question')
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('Hourly message limit reached.')
  expect(alert).toHaveTextContent('30 seconds')
  expect(screen.queryByText('Another question')).not.toBeInTheDocument()
  expect(screen.getByText('Earlier answer.')).toBeInTheDocument()
  expect(screen.getAllByText(/^(You|Assistant)$/)).toHaveLength(2)
})

// Starts an answer in Alpha and returns its stream while it is still open.
async function answerInFlight() {
  const streams: Stream[] = []
  mockServer([ALPHA, BETA], streamHandler(streams), { [ALPHA.id]: [], [BETA.id]: [] })
  const ui = renderPanel()
  await selectChat('Alpha')
  ask('Q?')
  await waitFor(() => expect(streams).toHaveLength(1))
  streams[0].push('token', { text: 'Par' })
  await waitFor(() => expect(bubble('Assistant')).toBe('Par'))
  return { ...ui, stream: streams[0] }
}

test('switching chats mid-stream aborts the stream and shows no error', async () => {
  const { stream } = await answerInFlight()
  await selectChat('Beta')
  await flush()
  expect(stream.signal.aborted).toBe(true)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('New chat mid-stream aborts the stream and shows no error', async () => {
  const { stream } = await answerInFlight()
  fireEvent.click(screen.getByRole('button', { name: 'New chat' }))
  await flush()
  expect(stream.signal.aborted).toBe(true)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('unmounting mid-stream aborts the stream', async () => {
  const { stream, unmount } = await answerInFlight()
  unmount()
  await flush()
  expect(stream.signal.aborted).toBe(true)
})

test('whitespace-only input does not send, even on Enter', async () => {
  const fetchMock = mockServer([ALPHA], streamHandler([]))
  renderPanel()
  await screen.findByRole('button', { name: 'Alpha' })
  const box = screen.getByLabelText('Message')
  fireEvent.change(box, { target: { value: '   \n  ' } })
  fireEvent.keyDown(box, { key: 'Enter' })

  expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  expect(requestsWith(fetchMock, 'POST')).toEqual([])
})

test('Enter sends the trimmed message and clears the box', async () => {
  const streams: Stream[] = []
  const fetchMock = mockServer([ALPHA], streamHandler(streams), { [ALPHA.id]: [] })
  renderPanel()
  await selectChat('Alpha')
  const box = screen.getByLabelText('Message')
  fireEvent.change(box, { target: { value: '  Hi  ' } })
  fireEvent.keyDown(box, { key: 'Enter' })

  await waitFor(() => expect(streams).toHaveLength(1))
  expect(postBody(fetchMock, `${CHATS}/${ALPHA.id}/messages`)).toEqual({ content: 'Hi' })
  expect(box).toHaveValue('')
  streams[0].close()
})

test('Shift+Enter inserts a line break and does not send', async () => {
  const fetchMock = mockServer([ALPHA], streamHandler([]), { [ALPHA.id]: [] })
  renderPanel()
  await selectChat('Alpha')
  const box = screen.getByLabelText('Message')
  fireEvent.change(box, { target: { value: 'Hi' } })
  fireEvent.keyDown(box, { key: 'Enter', shiftKey: true })

  expect(requestsWith(fetchMock, 'POST')).toEqual([])
  expect(box).toHaveValue('Hi')
})

test('the message box is capped at 4000 characters', async () => {
  mockServer([ALPHA])
  renderPanel()
  await screen.findByRole('button', { name: 'Alpha' })
  expect(screen.getByLabelText('Message')).toHaveAttribute('maxlength', '4000')
})

test('the hint shows the hourly message limit from the session', async () => {
  mockServer([ALPHA])
  renderPanel({ ...limits, chat_messages_per_hour: 7 })
  expect(await screen.findByText(/Limit: 7 messages per hour/)).toBeInTheDocument()
})

test('a chat title, answer token and citation snippet with HTML render as literal text', async () => {
  const payload = '<img src=x onerror=alert(1)>'
  const streams: Stream[] = []
  mockServer([{ ...ALPHA, title: payload }], streamHandler(streams), { [ALPHA.id]: [] })
  const { container } = renderPanel()
  await selectChat(payload)

  ask('Q?')
  await waitFor(() => expect(streams).toHaveLength(1))
  streams[0].push('token', { text: payload })
  streams[0].push('citations', [{ ...citation, snippet: payload }])
  streams[0].push('done', {})
  streams[0].close()

  await waitFor(() => expect(bubble('Assistant')).toBe(payload))
  expect(screen.getByRole('list', { name: 'Sources' })).toHaveTextContent(payload)
  expect(screen.getByRole('button', { name: payload })).toBeInTheDocument()
  expect(container.querySelector('img')).toBeNull()
})

test('while a chat history loads, Send is disabled and the box is read-only until it loads', async () => {
  const streams: Stream[] = []
  const history = deferred<Response>()
  const fetchMock = mockServer([ALPHA], (method, url, init) => {
    if (method === 'GET' && url === `${CHATS}/${ALPHA.id}/messages`) return history.promise
    return streamHandler(streams)(method, url, init)
  })
  renderPanel()
  fireEvent.click(await screen.findByRole('button', { name: 'Alpha' }))
  await screen.findByText('Loading messages…')

  const box = screen.getByLabelText('Message')
  expect(box).toHaveAttribute('readonly')
  expect(box).not.toBeDisabled()
  fireEvent.change(box, { target: { value: 'Early question' } })
  expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  fireEvent.keyDown(box, { key: 'Enter' })
  expect(requestsWith(fetchMock, 'POST')).toEqual([])

  history.resolve(Response.json([]))
  await waitFor(() => expect(screen.queryByText('Loading messages…')).not.toBeInTheDocument())
  expect(box).not.toHaveAttribute('readonly')

  ask('Early question')
  await waitFor(() => expect(streams).toHaveLength(1))
  streams[0].push('token', { text: 'Early answer' })
  await waitFor(() => expect(bubble('Assistant')).toBe('Early answer'))
  streams[0].push('done', {})
  streams[0].close()
})

test('the message log is busy while the answer streams and not after', async () => {
  const streams: Stream[] = []
  mockServer([ALPHA], streamHandler(streams), { [ALPHA.id]: [] })
  renderPanel()
  await selectChat('Alpha')

  ask('Q?')
  await waitFor(() => expect(streams).toHaveLength(1))
  const log = screen.getByRole('log', { name: 'Messages' })
  expect(log).toHaveAttribute('aria-busy', 'true')
  expect(log).not.toHaveAttribute('aria-live')

  streams[0].push('done', {})
  streams[0].close()
  await waitFor(() => expect(log).toHaveAttribute('aria-busy', 'false'))
})

test('a stream that closes without done shows an alert, keeps the question, and drops the partial answer', async () => {
  const streams: Stream[] = []
  mockServer([ALPHA], streamHandler(streams), { [ALPHA.id]: [] })
  renderPanel()
  await selectChat('Alpha')

  ask('Cut off?')
  await waitFor(() => expect(streams).toHaveLength(1))
  streams[0].push('token', { text: 'Partial' })
  await waitFor(() => expect(bubble('Assistant')).toBe('Partial'))
  streams[0].close()

  expect(await screen.findByRole('alert')).toHaveTextContent('The answer was interrupted. Try again.')
  expect(screen.queryByText('Partial')).not.toBeInTheDocument()
  expect(screen.queryByText('Assistant')).not.toBeInTheDocument()
  expect(screen.getByText('Cut off?')).toBeInTheDocument()
})

test('a network error mid-answer keeps the question, drops the partial answer, and shows an alert', async () => {
  const streams: Stream[] = []
  mockServer([ALPHA], streamHandler(streams), { [ALPHA.id]: [] })
  renderPanel()
  await selectChat('Alpha')

  ask('Network?')
  await waitFor(() => expect(streams).toHaveLength(1))
  streams[0].push('token', { text: 'Some' })
  await waitFor(() => expect(bubble('Assistant')).toBe('Some'))
  streams[0].fail(new TypeError('network error'))

  expect(await screen.findByRole('alert')).toHaveTextContent('The answer was interrupted. Try again.')
  expect(screen.queryByText('Some')).not.toBeInTheDocument()
  expect(screen.queryByText('Assistant')).not.toBeInTheDocument()
  expect(screen.getByText('Network?')).toBeInTheDocument()
})

test('an event after error is ignored, so the question text does not change', async () => {
  const streams: Stream[] = []
  mockServer([ALPHA], streamHandler(streams), { [ALPHA.id]: [] })
  renderPanel()
  await selectChat('Alpha')

  ask('Stay put')
  await waitFor(() => expect(streams).toHaveLength(1))
  streams[0].push('error', { code: 'answer_failed', detail: 'The model is unavailable. Try again.' })
  streams[0].push('token', { text: ' late' })
  streams[0].close()

  expect(await screen.findByRole('alert')).toHaveTextContent('The model is unavailable. Try again.')
  await flush()
  expect(bubble('You')).toBe('Stay put')
  expect(screen.queryByText('Assistant')).not.toBeInTheDocument()
})

test('New chat during the create POST keeps the new chat listed, unselected, and sends nothing', async () => {
  const created = deferred<Response>()
  const fetchMock = mockServer([ALPHA], (method, url) => {
    if (method === 'POST' && url === CHATS) return created.promise
  })
  renderPanel()
  await screen.findByRole('button', { name: 'Alpha' })

  ask('First question')
  await waitFor(() => expect(requestsWith(fetchMock, 'POST')).toEqual([CHATS]))
  fireEvent.click(screen.getByRole('button', { name: 'New chat' }))
  created.resolve(Response.json({ id: NEW_ID, title: 'First question', created_at: ALPHA.created_at }, { status: 201 }))

  const added = await screen.findByRole('button', { name: 'First question' })
  expect(added).not.toHaveAttribute('aria-current')
  expect(requestsWith(fetchMock, 'POST')).toEqual([CHATS])
})

test('a chat list that loads after the first send keeps the chat created locally', async () => {
  const streams: Stream[] = []
  const list = deferred<Response>()
  mockServer([ALPHA], (method, url, init) => {
    if (method === 'GET' && url === CHATS) return list.promise
    if (method === 'POST' && url === CHATS) {
      return Response.json({ id: NEW_ID, title: 'Hello', created_at: ALPHA.created_at }, { status: 201 })
    }
    return streamHandler(streams)(method, url, init)
  })
  renderPanel()

  ask('Hello')
  await waitFor(() => expect(streams).toHaveLength(1))
  expect(screen.getByRole('button', { name: 'Hello' })).toHaveAttribute('aria-current', 'true')

  list.resolve(Response.json([ALPHA]))
  expect(await screen.findByRole('button', { name: 'Alpha' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Hello' })).toHaveAttribute('aria-current', 'true')
  streams[0].push('done', {})
  streams[0].close()
})

test('a failed chat list shows an alert, and Reload fetches the chats', async () => {
  let down = true
  mockServer([ALPHA], (method, url) => {
    if (method === 'GET' && url === CHATS && down) {
      return Response.json({ code: 'internal', detail: 'Chats are unavailable.' }, { status: 500 })
    }
  })
  renderPanel()

  expect(await screen.findByRole('alert')).toHaveTextContent('Chats are unavailable.')
  expect(screen.queryByRole('list', { name: 'Chat list' })).not.toBeInTheDocument()

  down = false
  fireEvent.click(screen.getByRole('button', { name: 'Reload' }))
  expect(await screen.findByRole('button', { name: 'Alpha' })).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('a chat without a title is listed as Untitled chat', async () => {
  mockServer([{ ...ALPHA, title: null }])
  renderPanel()
  expect(await screen.findByRole('button', { name: 'Untitled chat' })).toBeInTheDocument()
})

test('a title cut at 200 characters keeps an emoji whole, with no lone surrogate', async () => {
  const streams: Stream[] = []
  const question = 'a'.repeat(199) + '😀' + 'bbbbb'
  const fetchMock = mockServer([ALPHA], (method, url, init) => {
    if (method === 'POST' && url === CHATS) {
      const { title } = JSON.parse(init.body as string)
      return Response.json({ id: NEW_ID, title, created_at: ALPHA.created_at }, { status: 201 })
    }
    return streamHandler(streams)(method, url, init)
  })
  renderPanel()
  await screen.findByRole('button', { name: 'Alpha' })

  ask(question)
  await waitFor(() => expect(streams).toHaveLength(1))
  const { title } = postBody(fetchMock, CHATS)
  expect(Array.from(title)).toHaveLength(200)
  expect(title).toBe('a'.repeat(199) + '😀')
  expect(title).not.toMatch(LONE_SURROGATE)
  expect(screen.getByRole('button', { name: title })).toHaveAttribute('aria-current', 'true')

  streams[0].push('done', {})
  streams[0].close()
})
