import { useCallback, useState } from 'react'
import type { DocumentOut } from '@shared/index'
import { ChatPanel } from '@/features/chat/ChatPanel'
import { DocumentsPanel } from '@/features/sources/DocumentsPanel'
import { Header } from '@/components/layout/Header'

export function AppShell() {
  const [hasReady, setHasReady] = useState<boolean | null>(null)
  const onLoaded = useCallback((docs: DocumentOut[]) => setHasReady(docs.some((d) => d.status === 'ready')), [])
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Header />
      <main className="mx-auto grid min-h-0 w-full max-w-6xl flex-1 gap-6 p-6 md:grid-cols-[20rem_1fr] md:grid-rows-[minmax(0,1fr)]">
        <section aria-label="Documents" className="min-h-0 overflow-y-auto rounded-lg border p-4">
          <DocumentsPanel onLoaded={onLoaded} />
        </section>
        <section aria-label="Chat" className="min-h-0 rounded-lg border p-4">
          <ChatPanel hasReady={hasReady} />
        </section>
      </main>
    </div>
  )
}
