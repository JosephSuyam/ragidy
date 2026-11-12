import type { ApiErrorBody, MeResponse, ValidationErrorBody } from '@shared/index'

export class ApiError extends Error {
  status: number
  code: string
  detail: string
  retryAfter?: number

  constructor(status: number, code: string, detail: string, retryAfter?: number) {
    super(detail)
    this.status = status
    this.code = code
    this.detail = detail
    this.retryAfter = retryAfter
  }
}

// Epoch ms until which the cookie is trusted: Infinity for a user, 0 for none.
let sessionExpiry = 0
let firstWrite: Promise<unknown> | null = null
let expiredRefresh: Promise<void> | null = null
let onSessionChange: ((me: MeResponse, remount: boolean) => void) | undefined

// The browser drops a guest cookie by its own clock: stop trusting it early to absorb client clock skew.
const GUEST_EXPIRY_MARGIN_MS = 60_000

const hasSession = () => Date.now() < sessionExpiry

export function setSessionState(me: MeResponse) {
  sessionExpiry = me.tier === 'user' ? Infinity : me.guest_expires_at ? Date.parse(me.guest_expires_at) - GUEST_EXPIRY_MARGIN_MS : 0
}

export function clearSessionState() {
  sessionExpiry = 0
}

export function setSessionHandler(handler?: (me: MeResponse, remount: boolean) => void) {
  onSessionChange = handler
}

async function toError(res: Response) {
  const retry = Number.parseInt(res.headers.get('Retry-After') ?? '', 10)
  const body: unknown = await res.json().catch(() => null)
  if (Array.isArray((body as ValidationErrorBody | null)?.detail)) {
    const detail = (body as ValidationErrorBody).detail.map((e) => e.msg).join('; ')
    return new ApiError(res.status, 'validation_error', detail)
  }
  const { code, detail } = (body ?? {}) as Partial<ApiErrorBody>
  return new ApiError(res.status, code ?? 'unknown', detail ?? res.statusText, Number.isNaN(retry) ? undefined : retry)
}

async function send(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<Response> {
  const multipart = body instanceof FormData
  const res = await fetch(`/api${path}`, {
    method,
    signal,
    // Multipart: the browser sets Content-Type with its boundary.
    headers: body === undefined || multipart ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : multipart ? body : JSON.stringify(body),
  })
  if (!res.ok) throw await toError(res)
  return res
}

const parse = <T>(res: Response) => (res.status === 204 ? undefined : res.json()) as Promise<T>

// remount: the owner changed, so state held by mounted views is stale.
async function refreshMe(signal: AbortSignal | undefined, remount: boolean) {
  const me = await send('GET', '/me', undefined, signal).then(parse<MeResponse>)
  setSessionState(me)
  onSessionChange?.(me, remount)
}

// Concurrent session_expired retries share one /me and one remount.
function refreshAfterExpiry(signal: AbortSignal | undefined) {
  expiredRefresh ??= refreshMe(signal, true).finally(() => {
    expiredRefresh = null
  })
  return expiredRefresh
}

async function attempt(method: string, path: string, body: unknown, signal: AbortSignal | undefined, retried: boolean, holding: boolean): Promise<Response> {
  try {
    return await send(method, path, body, signal)
  } catch (err) {
    if (retried || !(err instanceof ApiError) || err.code !== 'session_expired') throw err
    await refreshAfterExpiry(signal)
    return request(method, path, body, signal, true, holding)
  }
}

async function request(
  method: string,
  path: string,
  body?: unknown,
  signal?: AbortSignal,
  retried = false,
  holding = false,
): Promise<Response> {
  if (method === 'GET' || holding) return attempt(method, path, body, signal, retried, holding)
  // Concurrent cookieless writes each create an orphan guest: send the first alone.
  while (!hasSession() && firstWrite) await firstWrite.catch(() => undefined)
  if (hasSession()) return attempt(method, path, body, signal, retried, false)
  // The new guest's expiry is unknown: fetch it once so later writes gate correctly.
  const run = attempt(method, path, body, signal, retried, true).then(async (result) => {
    if (!hasSession()) await refreshMe(signal, false).catch(() => undefined)
    return result
  })
  firstWrite = run
  try {
    return await run
  } finally {
    if (firstWrite === run) firstWrite = null
  }
}

export function errorMessage(err: unknown) {
  if (!(err instanceof ApiError)) return 'Something went wrong. Try again.'
  return err.retryAfter ? `${err.detail} Try again in ${err.retryAfter} seconds.` : err.detail
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request('GET', path, undefined, signal).then(parse<T>),
  post: <T>(path: string, body?: unknown, signal?: AbortSignal) => request('POST', path, body, signal).then(parse<T>),
  stream: (path: string, body: unknown, signal: AbortSignal) => request('POST', path, body, signal),
  delete: <T>(path: string, signal?: AbortSignal) => request('DELETE', path, undefined, signal).then(parse<T>),
}
