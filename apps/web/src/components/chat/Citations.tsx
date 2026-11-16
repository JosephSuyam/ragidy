import type { CitationOut } from '@shared/index'

export function Citations({ citations }: { citations: CitationOut[] }) {
  if (citations.length === 0) return null
  return (
    <ul aria-label="Sources" className="mt-2 flex flex-col gap-1 border-t pt-2 text-xs text-muted-foreground">
      {citations.map((c, i) => (
        <li key={i} className="whitespace-pre-wrap">
          <span className="font-medium text-foreground">{c.source}</span>
          {c.page !== null && <span>, page {c.page}</span>}
          <span>: {c.snippet}</span>
        </li>
      ))}
    </ul>
  )
}
