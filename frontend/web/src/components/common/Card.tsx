import type { ReactNode } from 'react'
import { cn } from '../../utils/cn'

export function Card({
  children,
  className,
  hover = false,
}: {
  children: ReactNode
  className?: string
  hover?: boolean
}) {
  return (
    <div
      className={cn(
        'rounded-lg border border-border bg-bg-panel/80 backdrop-blur-sm',
        hover && 'transition-colors hover:border-border-subtle hover:bg-bg-elevated/90',
        className,
      )}
    >
      {children}
    </div>
  )
}

export function CardHeader({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('border-b border-border px-4 py-3', className)}>{children}</div>
  )
}

export function CardBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('p-4', className)}>{children}</div>
}
