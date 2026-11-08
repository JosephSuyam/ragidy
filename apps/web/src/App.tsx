import { SessionProvider } from '@/hooks/SessionProvider'
import { useSession } from '@/hooks/useSession'
import { Router } from '@/routes'

function Content() {
  const { sessionVersion } = useSession()
  return <Router key={sessionVersion} />
}

export default function App() {
  return (
    <SessionProvider>
      <Content />
    </SessionProvider>
  )
}
