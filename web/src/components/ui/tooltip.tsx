import * as React from 'react';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import { cn } from '@/lib/utils';

function TooltipProvider({ delayDuration = 400, ...props }: React.ComponentProps<typeof TooltipPrimitive.Provider>) { return <TooltipPrimitive.Provider data-slot="tooltip-provider" delayDuration={delayDuration} {...props} />; }
function Tooltip(props: React.ComponentProps<typeof TooltipPrimitive.Root>) { return <TooltipPrimitive.Root data-slot="tooltip" {...props} />; }
function TooltipTrigger(props: React.ComponentProps<typeof TooltipPrimitive.Trigger>) { return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />; }
function TooltipContent({ className, sideOffset = 4, children, ...props }: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content data-slot="tooltip-content" sideOffset={sideOffset}
        className={cn('z-50 w-fit max-w-72 rounded-md bg-foreground px-2.5 py-1.5 text-xs text-balance text-background', className)} {...props}>
        {children}
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  );
}
// a tip on any control: <Tip label="..."><Button/></Tip>. A Toggle takes `span`: the trigger's own data-state (closed / delayed-open)
// would otherwise overwrite the toggle's data-state (on / off) and hide its pressed look.
function Tip({ label, children, side, span }: { label: React.ReactNode; children: React.ReactElement; side?: 'top' | 'bottom' | 'left' | 'right'; span?: boolean }) {
  return <Tooltip><TooltipTrigger asChild>{span ? <span className="inline-flex">{children}</span> : children}</TooltipTrigger><TooltipContent side={side}>{label}</TooltipContent></Tooltip>;
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider, Tip };
