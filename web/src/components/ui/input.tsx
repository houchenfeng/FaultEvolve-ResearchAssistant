import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react';

import { cn } from '@/lib/cn';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  inputSize?: 'sm' | 'md';
}

export function Input({ className, inputSize = 'sm', ...props }: InputProps) {
  return <input className={cn('fe-input', inputSize === 'sm' && 'fe-input-sm', className)} {...props} />;
}

// `type` 而不是 `interface ... {}`：空接口与父类型等价，ESLint 的
// no-empty-object-type 会直接报错。行为完全一样，纯粹是写法问题。
export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

export function Textarea({ className, ...props }: TextareaProps) {
  return <textarea className={cn('fe-input fe-textarea', className)} {...props} />;
}
