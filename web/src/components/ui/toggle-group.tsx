import * as React from 'react';
import * as ToggleGroupPrimitive from '@radix-ui/react-toggle-group';
import { type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';
import { toggleVariants } from '@/components/ui/toggle';

const Ctx = React.createContext<VariantProps<typeof toggleVariants>>({ size: 'default', variant: 'default' });

function ToggleGroup({ className, variant, size, children, ...props }: React.ComponentProps<typeof ToggleGroupPrimitive.Root> & VariantProps<typeof toggleVariants>) {
  return (
    <ToggleGroupPrimitive.Root data-slot="toggle-group" data-variant={variant} data-size={size}
      className={cn('group/toggle-group flex w-fit items-center rounded-md', variant === 'outline' && 'shadow-xs', className)} {...props}>
      <Ctx.Provider value={{ variant, size }}>{children}</Ctx.Provider>
    </ToggleGroupPrimitive.Root>
  );
}
function ToggleGroupItem({ className, children, variant, size, ...props }: React.ComponentProps<typeof ToggleGroupPrimitive.Item> & VariantProps<typeof toggleVariants>) {
  const c = React.useContext(Ctx);
  return (
    <ToggleGroupPrimitive.Item data-slot="toggle-group-item"
      className={cn(toggleVariants({ variant: c.variant || variant, size: c.size || size }), 'min-w-0 flex-1 shrink-0 rounded-none shadow-none first:rounded-l-md last:rounded-r-md focus:z-10 focus-visible:z-10 data-[variant=outline]:border-l-0 data-[variant=outline]:first:border-l', className)}
      data-variant={c.variant || variant} {...props}>
      {children}
    </ToggleGroupPrimitive.Item>
  );
}

export { ToggleGroup, ToggleGroupItem };
