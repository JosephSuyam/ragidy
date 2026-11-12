import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    if (init?.method === 'POST' && post) return post.clone()
    throw new Error(`unexpected ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
}

afterEach(() => {
  clearSessionState()
  vi.unstubAllGlobals()
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

function mockSession(current: () => unknown, onPost?: (url: string) => Response | Promise<Response>) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/me') return Response.json(current())
    if (url === '/api/auth/providers') return Response.json([])
    if (url === '/api/documents') return Response.json([])
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
  const chatCalls = () => fetchMock.mock.calls.filter(([url]) => url === '/api/chats').length

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
  expect(fetchMock.mock.calls.filter(([url]) => url === '/api/chats')).toHaveLength(1)
  await vi.waitFor(() => {
    releaseChats.splice(0).forEach((release) => release())
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/chats')).toHaveLength(2)
  })
  await Promise.all(writes)
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
