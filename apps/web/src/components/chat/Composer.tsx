import { useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

// Matches CONTENT_MAX_CHARS in apps/api/app/schemas/chats.py.
const CONTENT_MAX_CHARS = 4000

type Props = { disabled: boolean; hourlyLimit: number; onSend: (content: string) => void }

export function Composer({ disabled, hourlyLimit, onSend }: Props) {
  const [text, setText] = useState('')

  const submit = () => {
    const content = text.trim()
    if (!content || disabled) return
    setText('')
    onSend(content)
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    submit()
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <Label htmlFor="chat-message">Message</Label>
      <Textarea
        id="chat-message"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        maxLength={CONTENT_MAX_CHARS}
        readOnly={disabled}
        placeholder="Ask about your documents"
      />
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Enter to send, Shift+Enter for a new line. Limit: {hourlyLimit} messages per hour.
        </p>
        <Button type="submit" disabled={disabled || !text.trim()}>
          Send
        </Button>
      </div>
    </form>
  )
}
