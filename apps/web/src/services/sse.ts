import type { ChatStreamEvent } from '@shared/index'

function parseFrame(frame: string): ChatStreamEvent | null {
  let event = 'message'
  const data: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
  }
  // Comment-only frames (`: ping` keep-alives) carry no data.
  return data.length ? ({ event, data: JSON.parse(data.join('\n')) } as ChatStreamEvent) : null
}

export async function readChatStream(res: Response, onEvent: (e: ChatStreamEvent) => void): Promise<void> {
  if (!res.body) return
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    const raw = buffer + decoder.decode(value, { stream: !done })
    // A trailing `\r` may be half of a `\r\n` split across reads: hold it back.
    const held = !done && raw.endsWith('\r') ? '\r' : ''
    const frames = raw.slice(0, raw.length - held.length).replace(/\r\n?/g, '\n').split('\n\n')
    // An unterminated final frame is discarded, per the SSE spec.
    const rest = frames.pop() ?? ''
    buffer = done ? '' : rest + held
    for (const frame of frames) {
      const parsed = parseFrame(frame)
      if (parsed) onEvent(parsed)
    }
    if (done) return
  }
}
