import type { MessageOut } from '@shared/index'
import { Citations } from '@/components/chat/Citations'
import { cn } from '@/lib/utils'

export function MessageList({ messages, streaming }: { messages: MessageOut[]; streaming: boolean }) {
  return (
    <div role="log" aria-label="Messages" aria-busy={streaming} className="flex flex-col gap-3">
      {messages.map((m, i) => (
        // The list is append-only and messages carry no id, so the index is a stable key.
        <div
          key={i}
          className={cn(
            'max-w-[85%] rounded-lg border px-3 py-2 text-sm',
            m.role === 'user' ? 'self-end bg-muted' : 'self-start',
          )}
        >
          <p className="sr-only">{m.role === 'user' ? 'You' : 'Assistant'}</p>
          <p className="whitespace-pre-wrap">{m.content}</p>
          <Citations citations={m.citations} />
        </div>
      ))}
    </div>
  )
}
