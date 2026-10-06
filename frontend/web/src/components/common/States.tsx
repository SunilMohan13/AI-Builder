import { cn } from '../../utils/cn'

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded bg-border/60', className)} />
}

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

export function ErrorState({
  title,
  description,
  action,
  onAction,
}: {
  title: string
  description: string
  action?: string
  onAction?: () => void
}) {
  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
      <p className="font-medium text-amber-300">{title}</p>
      <p className="mt-1 text-sm text-text-secondary">{description}</p>
      {action && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="mt-3 text-sm text-intel hover:underline"
        >
          {action}
        </button>
      )}
    </div>
  )
}
