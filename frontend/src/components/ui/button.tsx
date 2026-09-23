import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/utils'
// Adapted from the shadcn/ui Radix button; visual tokens belong to this project.
const buttonVariants = cva('inline-flex items-center justify-center gap-2 rounded-xl text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50', { variants: { variant: { default: 'btn-primary', outline: 'btn-outline', ghost: 'btn-ghost' }, size: { default: 'px-4 py-3', sm: 'px-3 py-2' } }, defaultVariants: { variant: 'default', size: 'default' } })
export function Button({ className, variant, size, asChild = false, ...props }: React.ComponentProps<'button'> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) { const Comp = asChild ? Slot : 'button'; return <Comp data-slot="button" className={cn(buttonVariants({ variant, size, className }))} {...props}/> }
