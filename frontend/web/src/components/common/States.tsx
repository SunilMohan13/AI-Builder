export function LoadingState({ message = 'Loading intelligence...' }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-16">
      <div className="h-1 w-48 overflow-hidden rounded-full bg-border">
        <div className="h-full w-1/2 animate-pulse rounded-full bg-intel" />
      </div>
      <p className="text-sm text-text-secondary">{message}</p>
    </div>
  )
}

export function EmptyState({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
      <p className="text-lg font-medium text-text-primary">{title}</p>
      <p className="max-w-md text-sm text-text-secondary">{description}</p>
    </div>
  )
}
