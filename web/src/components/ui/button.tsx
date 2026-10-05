import type { ButtonHTMLAttributes } from 'react';

import { cn } from '@/lib/cn';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'icon';
export type ButtonSize = 'sm' | 'md';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

const variantClass: Record<ButtonVariant, string> = {
  primary: 'fe-btn fe-btn-primary',
  secondary: 'fe-btn fe-btn-secondary',
  ghost: 'fe-btn fe-btn-ghost',
  icon: 'fe-btn fe-btn-icon',
};

const sizeClass: Record<ButtonSize, string> = {
  sm: 'fe-btn-sm',
  md: 'fe-btn-md',
};

export function Button({
  variant = 'primary',
  size = 'sm',
  className,
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(variantClass[variant], variant !== 'icon' && sizeClass[size], className)}
      {...props}
    />
  );
}
