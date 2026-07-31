import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline'
type ButtonSize = 'sm' | 'md' | 'lg' | 'icon'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
}

const variants: Record<ButtonVariant, string> = {
  primary: 'border-accent bg-accent text-white hover:bg-[#7476f3] shadow-[0_8px_24px_rgb(99_102_241/0.2)]',
  secondary: 'border-border-lit bg-surface-2 text-text hover:border-[#39414d] hover:bg-[#191d23]',
  ghost: 'border-transparent bg-transparent text-text-dim hover:bg-surface-2 hover:text-text',
  danger: 'border-danger/40 bg-danger/10 text-[#fb7185] hover:bg-danger/20',
  outline: 'border-border-lit bg-transparent text-text hover:bg-surface-2',
}

const sizes: Record<ButtonSize, string> = {
  sm: 'h-8 gap-1.5 px-3 text-[12px]',
  md: 'h-9 gap-2 px-3.5 text-[13px]',
  lg: 'h-12 gap-2.5 px-5 text-[14px] font-semibold',
  icon: 'size-9 p-0',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'secondary', size = 'md', type = 'button', ...props }, ref) => (
    <button className={cn(
        'relative inline-flex shrink-0 cursor-pointer items-center justify-center overflow-hidden rounded-[8px] border font-medium transition-all duration-200 ease-[cubic-bezier(0.22,1,0.36,1)] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-45',
        variants[variant],
        sizes[size],
        className,
      )}
      ref={ref}
      type={type}
      {...props}
    />
  ),
)
Button.displayName = 'Button'
