import { Button } from '@/components/ui/button'

export default function App() {
  return (
    <main className="mx-auto flex min-h-svh max-w-2xl flex-col items-center justify-center gap-4 p-6">
      <h1 className="text-3xl font-semibold tracking-tight">Ragidy</h1>
      <p className="text-muted-foreground">Chat with your files and links.</p>
      <Button disabled>Upload a document</Button>
    </main>
  )
}
