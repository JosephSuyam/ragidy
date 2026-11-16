import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import App from '@/App'
import { api, clearSessionState } from '@/services/api'

const me = {
  tier: 'guest',
  email: null,
  limits: { max_upload_mb: 5, upload_types: [], max_docs: 3, chat_messages_per_hour: 10 },
  document_count: 0,
  guest_expires_at: null,
}

function mockApi(post?: Response) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/me') return Response.json(me)
    if (url === '/api/auth/providers') return Response.json([{ id: 'github', name: 'GitHub' }])
    if (url === '/api/documents') return Response.json([])
    if (url === '/api/chats' && init?.method === 'GET') return Response.json([])
    if (init?.method === 'POST' && post) return post.clone()
    throw new Error(`unexpected ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
}

afterEach(() => {
  clearSessionState()
  vi.unstubAllGlobals()
  vi.useRealTimers()
  vi.restoreAllMocks()
  localStorage.clear()
  history.replaceState(null, '', '/')
})

function fill() {
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'a@b.co' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password1' } })
}

async function submit() {
  await screen.findByLabelText('Email')
  fill()
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

test.each([
  ['invalid_credentials', 401, {}, 'Wrong email or password.'],
  ['rate_limited', 429, { 'Retry-After': '42' }, 'Too many attempts. Try again in 42 seconds.'],
])('login %s shows its message', async (code, status, headers, text) => {
  mockApi(Response.json({ code, detail: 'x' }, { status, headers }))
  history.replaceState(null, '', '/login')
  render(<App />)
  await submit()
  expect(await screen.findByRole('alert')).toHaveTextContent(text)
})

test('register email_taken shows its message', async () => {
  mockApi(Response.json({ code: 'email_taken', detail: 'x' }, { status: 409 }))
  history.replaceState(null, '', '/login')
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'No account? Create one' }))
  fill()
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('already exists')
})

test('?error=oauth_failed renders the message and provider links', async () => {
  mockApi()
  history.replaceState(null, '', '/login?error=oauth_failed')
  render(<App />)
  expect(await screen.findByRole('alert')).toHaveTextContent('failed')
  await waitFor(() =>
    expect(screen.getByRole('link', { name: 'Continue with GitHub' })).toHaveAttribute('href', '/api/auth/oauth/github/start'),
  )
})

test('unknown path renders the home shell', async () => {
  mockApi()
  history.replaceState(null, '', '/nope')
  render(<App />)
  expect(await screen.findByRole('region', { name: 'Documents' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Chat' })).toBeInTheDocument()
})

const user = { ...me, tier: 'user', email: 'a@b.co' }

const releaseChats: (() => void)[] = []

// Counts only chat creations, so the mount-time GET /api/chats list load is not a write.
function chatPosts(fetchMock: ReturnType<typeof mockSession>) {
  return fetchMock.mock.calls.filter(([url, init]) => url === '/api/chats' && init?.method === 'POST')
}

type HeldMe = { armed: boolean; signal?: AbortSignal; release?: (r: Response) => void }

// While `held.armed` is set, /me requests hang and keep their signal and resolver in `held`.
function holdMe(held: HeldMe) {
  return (signal?: AbortSignal) => {
    if (!held.armed) return undefined
    return new Promise<Response>((resolve) => Object.assign(held, { signal, release: resolve }))
  }
}

function mockSession(
  current: () => unknown,
  onPost?: (url: string) => Response | Promise<Response>,
  onMe?: (signal?: AbortSignal) => Promise<Response> | undefined,
) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/me') return onMe?.(init?.signal ?? undefined) ?? Response.json(current())
    if (url === '/api/auth/providers') return Response.json([])
    if (url === '/api/documents') return Response.json([])
    if (url === '/api/chats' && init?.method === 'GET') return Response.json([])
    if (init?.method === 'POST' && url === '/api/chats') return new Promise<Response>((resolve) => releaseChats.push(() => resolve(Response.json({}, { status: 201 }))))
    if (init?.method === 'POST' && onPost) return onPost(url)
    throw new Error(`unexpected ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

test('login navigates home and refreshes the session', async () => {
  let signedIn = false
  mockSession(() => (signedIn ? user : me), () => ((signedIn = true), new Response(null, { status: 204 })))
  history.replaceState(null, '', '/login')
  render(<App />)
  await submit()
  await waitFor(() => expect(screen.getByText('a@b.co')).toBeInTheDocument())
  expect(location.pathname).toBe('/')
})

test('register navigates home and refreshes the session', async () => {
  let signedIn = false
  mockSession(() => (signedIn ? user : me), () => ((signedIn = true), Response.json({}, { status: 201 })))
  history.replaceState(null, '', '/login')
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'No account? Create one' }))
  fill()
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
  await waitFor(() => expect(screen.getByText('a@b.co')).toBeInTheDocument())
  expect(location.pathname).toBe('/')
})

test('sign out gates writes until logout resolves, then refetches /me and sends them one at a time', async () => {
  let signedIn = true
  let finishLogout = () => {}
  const fetchMock = mockSession(
    () => (signedIn ? user : me),
    () =>
      new Promise<Response>((resolve) => {
        finishLogout = () => {
          signedIn = false
          resolve(new Response(null, { status: 204 }))
        }
      }),
  )
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
  const chatCalls = () => chatPosts(fetchMock).length

  const writes = [api.post('/chats'), api.post('/chats')]
  await new Promise((r) => setTimeout(r))
  expect(fetchMock.mock.calls.some(([url]) => url === '/api/auth/logout')).toBe(true)
  expect(chatCalls()).toBe(0)

  finishLogout()
  expect(await screen.findByRole('link', { name: 'Sign in' })).toBeInTheDocument()
  await vi.waitFor(() => expect(chatCalls()).toBe(1))
  await new Promise((r) => setTimeout(r))
  expect(chatCalls()).toBe(1)
  await vi.waitFor(() => {
    releaseChats.splice(0).forEach((release) => release())
    expect(chatCalls()).toBe(2)
  })
  await Promise.all(writes)
})

test('422 shows the joined message list', async () => {
  mockApi(Response.json({ detail: [{ msg: 'too short' }, { msg: 'bad email' }] }, { status: 422 }))
  history.replaceState(null, '', '/login')
  render(<App />)
  await submit()
  expect(await screen.findByRole('alert')).toHaveTextContent('Check your input: too short; bad email')
})

test('unreachable server shows a retry that recovers', async () => {
  let up = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/me' && up) return Response.json(me)
      throw new TypeError('network')
    }),
  )
  render(<App />)
  expect(await screen.findByText('Could not reach the server.')).toBeInTheDocument()
  up = true
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(await screen.findByRole('region', { name: 'Documents' })).toBeInTheDocument()
})

test('a cookieless guest first write refetches /me, shows the expiry and does not remount', async () => {
  let wrote = false
  const expiry = '2999-01-01T00:00:00Z'
  const fetchMock = mockSession(() => (wrote ? { ...me, guest_expires_at: expiry } : me), () => ((wrote = true), Response.json({}, { status: 201 })))
  render(<App />)
  const documents = await screen.findByRole('region', { name: 'Documents' })
  const meCalls = () => fetchMock.mock.calls.filter(([url]) => url === '/api/me').length
  expect(meCalls()).toBe(1)

  await api.post('/uploads')
  await screen.findByText(/Guest session expires/)
  expect(meCalls()).toBe(2)
  expect(screen.getByRole('region', { name: 'Documents' })).toBe(documents)
})

test('session_expired refetches /me and remounts the app', async () => {
  let call = 0
  mockSession(() => me, () => (call++ ? Response.json({}, { status: 201 }) : Response.json({ code: 'session_expired', detail: 'x' }, { status: 401 })))
  render(<App />)
  const documents = await screen.findByRole('region', { name: 'Documents' })
  await api.post('/uploads')
  await waitFor(() => expect(screen.getByRole('region', { name: 'Documents' })).not.toBe(documents))
})

function changeVisibility() {
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
  document.dispatchEvent(new Event('visibilitychange'))
}

test('two concurrent session_expired responses share one /me and one remount', async () => {
  const posts = { n: 0 }
  const fetchMock = mockSession(() => ({ ...me, guest_expires_at: '2999-01-01T00:00:00Z' }), () =>
    posts.n++ < 2 ? Response.json({ code: 'session_expired', detail: 'x' }, { status: 401 }) : Response.json({}, { status: 201 }),
  )
  render(<App />)
  const documents = await screen.findByRole('region', { name: 'Documents' })
  const meCalls = () => fetchMock.mock.calls.filter(([url]) => url === '/api/me').length
  const before = meCalls()
  await Promise.all([api.post('/uploads'), api.post('/uploads')])
  expect(meCalls() - before).toBe(1)
  await waitFor(() => expect(screen.getByRole('region', { name: 'Documents' })).not.toBe(documents))
})

test('visibility change with a changed owner engages the gate and remounts', async () => {
  let current: unknown = user
  const fetchMock = mockSession(() => current)
  render(<App />)
  const documents = await screen.findByRole('region', { name: 'Documents' })
  current = me
  changeVisibility()
  expect(await screen.findByRole('link', { name: 'Sign in' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Documents' })).not.toBe(documents)

  const writes = [api.post('/chats'), api.post('/chats')]
  await new Promise((r) => setTimeout(r))
  expect(chatPosts(fetchMock)).toHaveLength(1)
  await vi.waitFor(() => {
    releaseChats.splice(0).forEach((release) => release())
    expect(chatPosts(fetchMock)).toHaveLength(2)
  })
  await Promise.all(writes)
})

test('a me change during an in-flight visibility check does not abort it, and its owner change still remounts', async () => {
  let current: unknown = me
  const held: HeldMe = { armed: false }
  const fetchMock = mockSession(
    () => current,
    () => Response.json({}, { status: 201 }),
    holdMe(held),
  )
  render(<App />)
  const documents = await screen.findByRole('region', { name: 'Documents' })

  held.armed = true
  changeVisibility()
  await vi.waitFor(() => expect(held.release).toBeDefined())
  held.armed = false

  current = { ...me, guest_expires_at: '2999-01-01T00:00:00Z' }
  await api.post('/uploads')
  await screen.findByText(/Guest session expires/)
  expect(fetchMock.mock.calls.filter(([url]) => url === '/api/me')).toHaveLength(3)
  expect(held.signal?.aborted).toBe(false)
  expect(screen.getByRole('region', { name: 'Documents' })).toBe(documents)

  held.release?.(Response.json(user))
  await waitFor(() => expect(screen.getByRole('region', { name: 'Documents' })).not.toBe(documents))
})

test('a visibility check resolving with the refreshed me does not remount', async () => {
  let current: unknown = me
  const held: HeldMe = { armed: false }
  mockSession(
    () => current,
    () => Response.json({}, { status: 201 }),
    holdMe(held),
  )
  render(<App />)
  const documents = await screen.findByRole('region', { name: 'Documents' })

  held.armed = true
  changeVisibility()
  await vi.waitFor(() => expect(held.release).toBeDefined())
  held.armed = false

  const refreshed = { ...me, guest_expires_at: '2999-01-01T00:00:00Z' }
  current = refreshed
  await api.post('/uploads')
  await screen.findByText(/Guest session expires/)

  held.release?.(Response.json(refreshed))
  await new Promise((r) => setTimeout(r))
  expect(screen.getByRole('region', { name: 'Documents' })).toBe(documents)
})

test('unmounting the provider aborts an in-flight visibility check', async () => {
  const held: HeldMe = { armed: false }
  mockSession(() => user, undefined, holdMe(held))
  const { unmount } = render(<App />)
  await screen.findByRole('region', { name: 'Documents' })

  held.armed = true
  changeVisibility()
  await vi.waitFor(() => expect(held.release).toBeDefined())
  unmount()
  expect(held.signal?.aborted).toBe(true)
})

test('visibility change from guest A to guest B remounts', async () => {
  let current: unknown = { ...me, guest_expires_at: '2999-01-01T00:00:00Z' }
  const fetchMock = mockSession(() => current)
  render(<App />)
  const documents = await screen.findByRole('region', { name: 'Documents' })
  current = { ...me, guest_expires_at: '2999-01-02T00:00:00Z' }
  changeVisibility()
  await waitFor(() => expect(screen.getByRole('region', { name: 'Documents' })).not.toBe(documents))
  expect(fetchMock.mock.calls.filter(([url]) => url === '/api/me').length).toBeGreaterThanOrEqual(2)
})

test('visibility change with an unchanged owner does not remount', async () => {
  const fetchMock = mockSession(() => user)
  render(<App />)
  const documents = await screen.findByRole('region', { name: 'Documents' })
  changeVisibility()
  await vi.waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url === '/api/me')).toHaveLength(2))
  await new Promise((r) => setTimeout(r))
  expect(screen.getByRole('region', { name: 'Documents' })).toBe(documents)
})

const EXPIRY_KEY = 'ragidy.guestExpiresAt'
const EXPIRED_TEXT = 'Your guest session expired. Its documents and chats were deleted.'
const PAST = '2001-01-01T00:00:00Z'
const FUTURE = '2999-01-01T00:00:00Z'

const guest = (guest_expires_at: string | null) => ({ ...me, guest_expires_at })

const noticeRegion = () => screen.getByRole('status', { name: 'Notices' })

function meCalls(fetchMock: ReturnType<typeof mockSession>) {
  return fetchMock.mock.calls.filter(([url]) => url === '/api/me').length
}

async function renderHome(current: () => unknown) {
  const fetchMock = mockSession(current)
  render(<App />)
  await screen.findByRole('region', { name: 'Documents' })
  return fetchMock
}

test('a stored lapsed guest expiry shows the expired notice once and clears the key', async () => {
  localStorage.setItem(EXPIRY_KEY, PAST)
  await renderHome(() => guest(null))
  expect(await screen.findByText(EXPIRED_TEXT)).toBeInTheDocument()
  expect(screen.getAllByText(EXPIRED_TEXT)).toHaveLength(1)
  expect(localStorage.getItem(EXPIRY_KEY)).toBeNull()
})

test('a stored future guest expiry with no new expiry shows no notice', async () => {
  localStorage.setItem(EXPIRY_KEY, FUTURE)
  await renderHome(() => guest(null))
  expect(screen.queryByText(EXPIRED_TEXT)).not.toBeInTheDocument()
})

test('a user session clears the stored guest expiry and shows no notice', async () => {
  localStorage.setItem(EXPIRY_KEY, PAST)
  await renderHome(() => user)
  expect(screen.queryByText(EXPIRED_TEXT)).not.toBeInTheDocument()
  expect(localStorage.getItem(EXPIRY_KEY)).toBeNull()
})

test('a guest with an expiry stores it and shows no notice', async () => {
  await renderHome(() => guest(FUTURE))
  expect(localStorage.getItem(EXPIRY_KEY)).toBe(FUTURE)
  expect(screen.queryByText(EXPIRED_TEXT)).not.toBeInTheDocument()
})

test('a visibility check after the stored guest expiry lapsed shows the notice', async () => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2030-06-01T00:00:00Z'))
  let current: unknown = guest('2030-06-01T12:00:00Z')
  mockSession(() => current)
  render(<App />)
  await screen.findByRole('region', { name: 'Documents' })
  expect(localStorage.getItem(EXPIRY_KEY)).toBe('2030-06-01T12:00:00Z')

  vi.setSystemTime(new Date('2030-07-01T00:00:00Z'))
  current = guest(null)
  changeVisibility()
  expect(await screen.findByText(EXPIRED_TEXT)).toBeInTheDocument()
})

test('a first write that gets a new guest expiry after the stored one lapsed shows the notice', async () => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2030-06-01T00:00:00Z'))
  const firstExpiry = '2030-06-01T00:10:00Z'
  let wrote = false
  mockSession(() => (wrote ? guest(FUTURE) : guest(firstExpiry)), () => ((wrote = true), Response.json({}, { status: 201 })))
  render(<App />)
  await screen.findByRole('region', { name: 'Documents' })
  expect(localStorage.getItem(EXPIRY_KEY)).toBe(firstExpiry)
  expect(noticeRegion()).not.toHaveTextContent(EXPIRED_TEXT)

  vi.setSystemTime(new Date('2030-06-01T00:20:00Z'))
  await api.post('/uploads')
  await waitFor(() => expect(noticeRegion()).toHaveTextContent(EXPIRED_TEXT))
  expect(localStorage.getItem(EXPIRY_KEY)).toBe(FUTURE)
})

test('dismissing the expired notice hides it, moves focus to the page, and a later check does not show it again', async () => {
  localStorage.setItem(EXPIRY_KEY, PAST)
  const fetchMock = await renderHome(() => guest(null))
  fireEvent.click(await within(noticeRegion()).findByRole('button', { name: 'Dismiss' }))
  expect(screen.queryByText(EXPIRED_TEXT)).not.toBeInTheDocument()

  const page = document.activeElement
  expect(page).not.toBe(document.body)
  expect(page).toHaveAttribute('tabindex', '-1')
  expect(page).toContainElement(screen.getByRole('region', { name: 'Chat' }))

  const checks = meCalls(fetchMock)
  changeVisibility()
  await vi.waitFor(() => expect(meCalls(fetchMock)).toBe(checks + 1))
  await new Promise((r) => setTimeout(r))
  expect(noticeRegion()).not.toHaveTextContent(EXPIRED_TEXT)
  expect(localStorage.getItem(EXPIRY_KEY)).toBeNull()
})

test('a null-expiry guest before the stored expiry lapsed keeps the key, then shows the notice once it lapses', async () => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2030-06-01T00:00:00Z'))
  const stored = '2030-06-01T00:02:00Z'
  localStorage.setItem(EXPIRY_KEY, stored)
  const fetchMock = await renderHome(() => guest(null))
  expect(localStorage.getItem(EXPIRY_KEY)).toBe(stored)
  expect(noticeRegion()).not.toHaveTextContent(EXPIRED_TEXT)

  vi.setSystemTime(new Date('2030-06-01T00:05:00Z'))
  const checks = meCalls(fetchMock)
  changeVisibility()
  await waitFor(() => expect(noticeRegion()).toHaveTextContent(EXPIRED_TEXT))
  expect(meCalls(fetchMock)).toBe(checks + 1)
  expect(localStorage.getItem(EXPIRY_KEY)).toBeNull()
})

test('the expired notice shows on the login page without alert role', async () => {
  localStorage.setItem(EXPIRY_KEY, PAST)
  mockSession(() => guest(null))
  history.replaceState(null, '', '/login')
  render(<App />)
  await screen.findByLabelText('Email')
  await waitFor(() => expect(noticeRegion()).toHaveTextContent(EXPIRED_TEXT))
  expect(within(noticeRegion()).queryByRole('alert')).not.toBeInTheDocument()
})

test('unreadable storage renders the app without the notice', async () => {
  localStorage.setItem(EXPIRY_KEY, PAST)
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('storage denied')
  })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('storage denied')
  })
  await renderHome(() => guest(null))
  expect(screen.getByRole('region', { name: 'Chat' })).toBeInTheDocument()
  expect(screen.queryByText(EXPIRED_TEXT)).not.toBeInTheDocument()
})
