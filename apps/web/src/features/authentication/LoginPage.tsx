import { Alert, AlertDescription } from '@/components/ui/alert'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { AuthForm } from '@/features/authentication/AuthForm'
import { OAuthButtons } from '@/features/authentication/OAuthButtons'

export function LoginPage() {
  const oauthFailed = new URLSearchParams(window.location.search).get('error') === 'oauth_failed'
  return (
    <main className="mx-auto flex min-h-svh max-w-sm flex-col justify-center gap-4 p-6">
      <Card>
        <CardHeader>
          <CardTitle>
            <h1>Sign in to Ragidy</h1>
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {oauthFailed && (
            <Alert variant="destructive" role="alert">
              <AlertDescription>Sign-in with that provider failed. Try again or use your email.</AlertDescription>
            </Alert>
          )}
          <AuthForm />
          <OAuthButtons />
        </CardContent>
      </Card>
    </main>
  )
}
