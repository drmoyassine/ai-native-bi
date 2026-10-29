import { cva, type VariantProps } from 'class-variance-authority';
import type { ButtonHTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

// The AMS's button (DEC-038): one look across both products.
const button = cva(
  'inline-flex items-center justify-center rounded-md border border-transparent px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:opacity-90',
        ghost: 'bg-transparent hover:bg-muted',
        outline: 'border-border bg-background hover:bg-muted',
      },
    },
    defaultVariants: { variant: 'default' },
  },
);

export function Button({ className, variant, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button>) {
  return <button className={cn(button({ variant }), className)} {...props} />;
}
