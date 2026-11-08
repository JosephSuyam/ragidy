import { beforeEach, expect, test, vi } from 'vitest'

const me = (guest_expires_at: string | null) => ({
  tier: 'guest' as const,
  email: null,
  limits: { max_upload_mb: 5, upload_types: [], max_docs: 3, chat_messages_per_hour: 10 },
  document_count: 0,
  guest_expires_at,
})
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })

beforeEach(() => {
  vi.resetModules()
  vi.unstubAllGlobals()
})

const open = me('2999-01-01T00:00:00Z')

function deferredFetch() {
  const pending: { path: string; resolve: (r: Response) => void }[] = []
  const fetchMock = vi.fn(
    (url: string) => new Promise<Response>((resolve) => pending.push({ path: url, resolve })),
  )
  vi.stubGlobal('fetch', fetchMock)
  return { pending, fetchMock }
}
const tick = () => new Promise((r) => setTimeout(r))

test('gate holds a second write until the first resolves while there is no session', async () => {
  const { api, setSessionState } = await import('@/services/api')
  setSessionState(me(null))
  const { pending, fetchMock } = deferredFetch()

  const first = api.post('/chats')
  const second = api.post('/chats')
  await tick()
  expect(fetchMock).toHaveBeenCalledTimes(1)

  pending[0].resolve(json({ id: 1 }, 201))
  await vi.waitFor(() => expect(pending).toHaveLength(2))
  expect(pending[1].path).toBe('/api/me')
  pending[1].resolve(json(open))
  await first
  await vi.waitFor(() => expect(pending).toHaveLength(3))
  expect(pending[2].path).toBe('/api/chats')
  pending[2].resolve(json({ id: 2 }, 201))
  await second
})

test('after a successful first write the gate is open: parallel writes go out together', async () => {
  const { api, setSessionState } = await import('@/services/api')
  setSessionState(me(null))
  const fetchMock = vi.fn(async (url: string) => (url === '/api/me' ? json(open) : json({ id: 1 }, 201)))
  vi.stubGlobal('fetch', fetchMock)

  await api.post('/chats')
  const { pending } = deferredFetch()
  const a = api.post('/chats')
  const b = api.post('/chats')
  await tick()
  expect(pending).toHaveLength(2)
  pending.forEach((p) => p.resolve(json({ id: 2 }, 201)))
  await Promise.all([a, b])
})

test('a failed first write lets exactly one waiter go next, then the rest run after it succeeds', async () => {
  const { api, setSessionState } = await import('@/services/api')
  setSessionState(me(null))
  const { pending } = deferredFetch()

  const first = api.post('/chats')
  const second = api.post('/chats')
  const third = api.post('/chats')
  const fourth = api.post('/chats')
  const settled = Promise.allSettled([first])
  await tick()
  pending[0].resolve(json({ code: 'rate_limited', detail: 'x' }, 429))
  await settled
  await vi.waitFor(() => expect(pending).toHaveLength(2))
  await tick()
  expect(pending).toHaveLength(2)

  pending[1].resolve(json({ id: 2 }, 201))
  await vi.waitFor(() => expect(pending).toHaveLength(3))
  expect(pending[2].path).toBe('/api/me')
  pending[2].resolve(json(open))
  await second
  await vi.waitFor(() => expect(pending).toHaveLength(5))
  pending.slice(3).forEach((p) => p.resolve(json({ id: 3 }, 201)))
  await Promise.all([third, fourth])
})

test('a guest session past guest_expires_at engages the gate again', async () => {
  vi.useFakeTimers({ toFake: ['Date'] })
  try {
    vi.setSystemTime(new Date('2030-01-01T00:00:00Z'))
    const { api, setSessionState } = await import('@/services/api')
    setSessionState(me('2030-01-01T00:10:00Z'))
    const { pending } = deferredFetch()

    const a = api.post('/chats')
    const b = api.post('/chats')
    await tick()
    expect(pending).toHaveLength(2)
    pending.forEach((p) => p.resolve(json({ id: 1 }, 201)))
    await Promise.all([a, b])

    vi.setSystemTime(new Date('2030-01-01T00:11:00Z'))
    pending.length = 0
    const c = api.post('/chats')
    const d = api.post('/chats')
    await tick()
    expect(pending).toHaveLength(1)
    pending[0].resolve(json({ id: 2 }, 201))
    await vi.waitFor(() => expect(pending).toHaveLength(2))
    pending[1].resolve(json(open))
    await c
    await vi.waitFor(() => expect(pending).toHaveLength(3))
    pending[2].resolve(json({ id: 3 }, 201))
    await d
  } finally {
    vi.useRealTimers()
  }
})

test('the session_expired retry waits behind the writer that holds the gate', async () => {
  const { api, setSessionState, clearSessionState } = await import('@/services/api')
  setSessionState(open)
  const { pending } = deferredFetch()

  const a = api.post('/a')
  await tick()
  clearSessionState()
  const b = api.post('/b') // gate holder
  await tick()
  pending[0].resolve(json({ code: 'session_expired', detail: 'x' }, 401))
  await vi.waitFor(() => expect(pending).toHaveLength(3))
  pending[2].resolve(json(me(null))) // /me: cookie gone
  await tick()
  expect(pending.map((p) => p.path)).toEqual(['/api/a', '/api/b', '/api/me'])

  pending[1].resolve(json({ ok: 1 }, 201))
  await vi.waitFor(() => expect(pending).toHaveLength(4))
  expect(pending[3].path).toBe('/api/me')
  pending[3].resolve(json(open))
  await b
  await vi.waitFor(() => expect(pending).toHaveLength(5))
  expect(pending[4].path).toBe('/api/a')
  pending[4].resolve(json({ ok: 2 }, 201))
  await a
})

test('401 session_expired refetches /me and retries once', async () => {
  const { api } = await import('@/services/api')
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(json({ code: 'session_expired', detail: 'x' }, 401))
    .mockResolvedValueOnce(json(me('2030-01-01T00:00:00Z')))
    .mockResolvedValueOnce(json({ id: 1 }, 201))
  vi.stubGlobal('fetch', fetchMock)

  await expect(api.post('/chats')).resolves.toEqual({ id: 1 })
  expect(fetchMock.mock.calls.map(([url, init]) => [url, init.method])).toEqual([
    ['/api/chats', 'POST'],
    ['/api/me', 'GET'],
    ['/api/chats', 'POST'],
  ])
})

test('a second session_expired surfaces', async () => {
  const { api, ApiError } = await import('@/services/api')
  const expired = () => json({ code: 'session_expired', detail: 'x' }, 401)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(expired()).mockResolvedValueOnce(json(me(null))).mockResolvedValueOnce(expired()))
  await expect(api.post('/chats')).rejects.toBeInstanceOf(ApiError)
})
