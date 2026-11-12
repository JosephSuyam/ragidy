import { DocumentsPanel } from '@/features/sources/DocumentsPanel'
import { Header } from '@/components/layout/Header'

export function AppShell() {
  return (
    <div className="flex min-h-svh flex-col">
      <Header />
      <main className="mx-auto grid w-full max-w-6xl flex-1 gap-6 p-6 md:grid-cols-[20rem_1fr]">
        <section aria-label="Documents" className="rounded-lg border p-4">
          <DocumentsPanel />
        </section>
        <section aria-label="Chat" className="rounded-lg border p-4" />
      </main>
    </div>
  )
}
