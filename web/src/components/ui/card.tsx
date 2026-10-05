import type { HTMLAttributes } from 'react';

import { cn } from '@/lib/cn';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Hover lift + shadow expand (Fluent reveal). */
  interactive?: boolean;
  /** Acrylic surface for key panels only. */
  acrylic?: boolean;
}

export function Card({ interactive, acrylic, className, ...props }: CardProps) {
  return (
    <div
      className={cn(
        'fe-card',
        interactive && 'fe-card-interactive',
        acrylic && 'fe-card-acrylic',
        className,
      )}
      {...props}
    />
  );
}
