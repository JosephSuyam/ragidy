import { expect, test } from 'vitest'
import { readChatStream } from '@/services/sse'
import type { ChatStreamEvent } from '@shared/index'

const encoder = new TextEncoder()

// One chunk per network read, so a frame can be split at any byte.
const sseResponse = (...chunks: string[]) =>
  new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
    }),
  )

async function collect(res: Response): Promise<ChatStreamEvent[]> {
  const events: ChatStreamEvent[] = []
  await readChatStream(res, (e) => events.push(e))
  return events
}

test('a frame split mid-JSON across two reads parses as one event', async () => {
  const events = await collect(sseResponse('event: token\ndata: {"te', 'xt": "Hel"}\n\n'))

  expect(events).toEqual([{ event: 'token', data: { text: 'Hel' } }])
})

test('a keep-alive ": ping" comment frame is skipped', async () => {
  const events = await collect(
    sseResponse(': ping\n\nevent: token\ndata: {"text": "a"}\n\n: ping\n\n'),
  )

  expect(events).toEqual([{ event: 'token', data: { text: 'a' } }])
})

test('CRLF line endings parse the same as LF', async () => {
  const events = await collect(
    sseResponse('event: token\r\ndata: {"text": "a"}\r\n\r\nevent: done\r\ndata: {}\r\n\r\n'),
  )

  expect(events).toEqual([
    { event: 'token', data: { text: 'a' } },
    { event: 'done', data: {} },
  ])
})

test('a CRLF split between \r and \n across reads does not break the frame', async () => {
  const events = await collect(sseResponse('event: token\r', '\ndata: {"text": "a"}\r\n\r\n'))

  expect(events).toEqual([{ event: 'token', data: { text: 'a' } }])
})

test('an error event after token events keeps the order and payload', async () => {
  const events = await collect(
    sseResponse(
      'event: token\ndata: {"text": "He"}\n\n',
      'event: token\ndata: {"text": "llo"}\n\n',
      'event: error\ndata: {"code": "answer_failed", "detail": "boom"}\n\n',
    ),
  )

  expect(events).toEqual([
    { event: 'token', data: { text: 'He' } },
    { event: 'token', data: { text: 'llo' } },
    { event: 'error', data: { code: 'answer_failed', detail: 'boom' } },
  ])
})

test('token, citations, done arrive in order with parsed JSON data', async () => {
  const citation = { document_id: '6f1c2a4e-0b7d-4c1e-9a55-2d3e4f5a6b7c', source: 'notes.pdf', page: 2, snippet: 'context' }
  const events = await collect(
    sseResponse(
      'event: token\ndata: {"text": "Answer"}\n\n',
      `event: citations\ndata: ${JSON.stringify([citation])}\n\n`,
      'event: done\ndata: {}\n\n',
    ),
  )

  expect(events.map((e) => e.event)).toEqual(['token', 'citations', 'done'])
  expect(events[1]).toEqual({ event: 'citations', data: [citation] })
})

test('a stream that ends mid-frame resolves and emits no event for the partial frame', async () => {
  const events = await collect(sseResponse('event: token\ndata: {"text": "a"}\n\nevent: token\ndata: {"te'))

  expect(events).toEqual([{ event: 'token', data: { text: 'a' } }])
})

test('multi-line data fields are joined with a newline before JSON.parse', async () => {
  const events = await collect(sseResponse('event: token\ndata: {"text":\ndata: "x"}\n\n'))

  expect(events).toEqual([{ event: 'token', data: { text: 'x' } }])
})

test('a response with no body resolves with no events', async () => {
  expect(await collect(new Response(null))).toEqual([])
})

// Pinned: a data line that is not JSON rejects the whole read, so later frames in the stream are never delivered.
test('a data line that is not valid JSON rejects with SyntaxError', async () => {
  await expect(collect(sseResponse('event: token\ndata: {bad\n\nevent: done\ndata: {}\n\n'))).rejects.toThrow(SyntaxError)
})
