import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChatOut, MessageOut } from '@shared/index'
import { Composer } from '@/components/chat/Composer'
import { MessageList } from '@/components/chat/MessageList'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { useSession } from '@/hooks/useSession'
import { api, errorMessage } from '@/services/api'
import { readChatStream } from '@/services/sse'

const TITLE_MAX_CHARS = 200
const INTERRUPTED = 'The answer was interrupted. Try again.'

export function ChatPanel() {
  const { me } = useSession()
  const [chats, setChats] = useState<ChatOut[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [messages, setMessages] = useState<MessageOut[]>([])
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const listLoad = useRef<AbortController | null>(null)
  const messagesLoad = useRef<AbortController | null>(null)
  const stream = useRef<AbortController | null>(null)

  const loadChats = useCallback(() => {
    listLoad.current?.abort()
    const c = new AbortController()
    listLoad.current = c
    return api.get<ChatOut[]>('/chats', c.signal).then(
      (next) => {
        // Keep chats created locally while this request was in flight (newest first).
        setChats((local) => [...(local ?? []).filter((l) => !next.some((n) => n.id === l.id)), ...next])
      },
      (err: unknown) => {
        if (c.signal.aborted) return
        setListError(errorMessage(err))
      },
    )
  }, [])

  useEffect(() => {
    void loadChats()
    return () => {
      listLoad.current?.abort()
      messagesLoad.current?.abort()
      stream.current?.abort()
    }
  }, [loadChats])

  // Switching chat, starting a new one, or sending ends the previous load and stream.
  const cancelWork = () => {
    messagesLoad.current?.abort()
    stream.current?.abort()
    stream.current = null
    setStreaming(false)
    setError(null)
  }

  const select = (id: string) => {
    if (id === selected) return
    cancelWork()
    setSelected(id)
    setMessages([])
    setLoadingMessages(true)
    const c = new AbortController()
    messagesLoad.current = c
    void api.get<MessageOut[]>(`/chats/${id}/messages`, c.signal).then(
      (next) => {
        setMessages(next)
        setLoadingMessages(false)
      },
      (err: unknown) => {
        if (c.signal.aborted) return
        setLoadingMessages(false)
        setError(errorMessage(err))
      },
    )
  }

  const newChat = () => {
    cancelWork()
    setSelected(null)
    setMessages([])
    setLoadingMessages(false)
  }

  const send = (content: string) => {
    cancelWork()
    const c = new AbortController()
    stream.current = c
    setStreaming(true)
    const before = messages
    setMessages([...before, { role: 'user', content, citations: [] }, { role: 'assistant', content: '', citations: [] }])
    const patchAssistant = (patch: (m: MessageOut) => MessageOut) =>
      setMessages((all) => all.map((m, i) => (i === all.length - 1 ? patch(m) : m)))

    let started = false
    let ended = false
    const run = async () => {
      let chatId = selected
      if (!chatId) {
        const title = Array.from(content).slice(0, TITLE_MAX_CHARS).join('')
        const chat = await api.post<ChatOut>('/chats', { title })
        setChats((list) => [chat, ...(list ?? [])])
        if (c.signal.aborted) return
        setSelected(chat.id)
        chatId = chat.id
      }
      const res = await api.stream(`/chats/${chatId}/messages`, { content }, c.signal)
      started = true
      await readChatStream(res, (e) => {
        if (c.signal.aborted || ended) return
        if (e.event === 'token') patchAssistant((m) => ({ ...m, content: m.content + e.data.text }))
        else if (e.event === 'citations') patchAssistant((m) => ({ ...m, citations: e.data }))
        else if (e.event === 'done') ended = true
        else if (e.event === 'error') {
          ended = true
          setMessages((all) => all.slice(0, -1))
          setError(e.data.detail)
        }
      })
      if (!ended && !c.signal.aborted) throw new Error(INTERRUPTED)
    }

    void run()
      .catch((err: unknown) => {
        if (c.signal.aborted) return
        // Once the stream opened the server stored the question, so keep it and drop only the answer.
        setMessages(started ? (all) => all.slice(0, -1) : before)
        setError(started ? INTERRUPTED : errorMessage(err))
      })
      .finally(() => {
        if (stream.current === c) {
          stream.current = null
          setStreaming(false)
        }
      })
  }

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-medium">Chats</h2>
          <Button type="button" size="sm" variant="outline" onClick={newChat}>
            New chat
          </Button>
        </div>
        {chats === null ? (
          listError ? (
            <Alert variant="destructive">
              <AlertDescription>{listError}</AlertDescription>
              <Button type="button" size="sm" variant="outline" onClick={() => {
                  setListError(null)
                  void loadChats()
                }}>
                Reload
              </Button>
            </Alert>
          ) : (
            <p role="status">Loading chats…</p>
          )
        ) : chats.length === 0 ? (
          <p className="text-sm text-muted-foreground">No chats yet. Ask a question to start one.</p>
        ) : (
          <ul aria-label="Chat list" className="flex flex-wrap gap-2">
            {chats.map((chat) => (
              <li key={chat.id}>
                <Button
                  type="button"
                  size="sm"
                  variant={chat.id === selected ? 'secondary' : 'ghost'}
                  aria-current={chat.id === selected ? 'true' : undefined}
                  onClick={() => select(chat.id)}
                  className="max-w-56"
                >
                  <span className="truncate">{chat.title ?? 'Untitled chat'}</span>
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="flex-1">
        {loadingMessages ? (
          <p role="status">Loading messages…</p>
        ) : messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">Ask a question about your documents.</p>
        ) : (
          <MessageList messages={messages} streaming={streaming} />
        )}
      </div>
      <Composer disabled={streaming || loadingMessages} hourlyLimit={me.limits.chat_messages_per_hour} onSend={send} />
    </div>
  )
}
