import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

export function ExpiredNotice({ expired, onDismiss }: { expired: boolean; onDismiss: () => void }) {
  return (
    <section aria-label="Notices" role="status">
      {expired && (
        <Alert role="none" className="flex items-center justify-between gap-3 rounded-none border-x-0 border-t-0">
          <AlertDescription>Your guest session expired. Its documents and chats were deleted.</AlertDescription>
          <Button variant="outline" size="sm" onClick={onDismiss}>
            Dismiss
          </Button>
        </Alert>
      )}
    </section>
  )
}
