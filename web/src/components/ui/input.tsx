import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react';

import { cn } from '@/lib/cn';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  inputSize?: 'sm' | 'md';
}

export function Input({ className, inputSize = 'sm', ...props }: InputProps) {
  return <input className={cn('fe-input', inputSize === 'sm' && 'fe-input-sm', className)} {...props} />;
}

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {}

export function Textarea({ className, ...props }: TextareaProps) {
  return <textarea className={cn('fe-input fe-textarea', className)} {...props} />;
}
