import { useRef } from 'react'
import { ExpiredNotice } from '@/components/layout/ExpiredNotice'
import { SessionProvider } from '@/hooks/SessionProvider'
import { useSession } from '@/hooks/useSession'
import { Router } from '@/routes'

function Content() {
  const { sessionVersion, guestExpired, dismissExpired } = useSession()
  const pageRef = useRef<HTMLDivElement>(null)
  return (
    <>
      <ExpiredNotice
        expired={guestExpired}
        onDismiss={() => {
          dismissExpired()
          pageRef.current?.focus()
        }}
      />
      <div ref={pageRef} tabIndex={-1} className="outline-none">
        <Router key={sessionVersion} />
      </div>
    </>
  )
}

export default function App() {
  return (
    <SessionProvider>
      <Content />
    </SessionProvider>
  )
}
