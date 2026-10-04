/**
 * Small floating surfaces on Radix — a popover holds one decision (a date, a
 * reason, an approve-or-reject) next to the thing it changes, instead of a form
 * in the middle of the page (§9). Focus moves in on open and back to the trigger
 * on close; Escape closes.
 */

import * as RadixHoverCard from '@radix-ui/react-hover-card';
import * as RadixPopover from '@radix-ui/react-popover';
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from 'react';

import { cn } from '@/lib/cn';

const FLOATING =
  'z-50 rounded-xl border border-line bg-raised text-ink shadow-float outline-none animate-float-in';

export const Popover = RadixPopover.Root;
export const PopoverTrigger = RadixPopover.Trigger;
export const PopoverAnchor = RadixPopover.Anchor;
export const PopoverClose = RadixPopover.Close;

export const PopoverContent = forwardRef<
  ElementRef<typeof RadixPopover.Content>,
  ComponentPropsWithoutRef<typeof RadixPopover.Content>
>(function PopoverContent({ className, align = 'start', sideOffset = 6, ...rest }, ref) {
  return (
    <RadixPopover.Portal>
      <RadixPopover.Content
        ref={ref}
        align={align}
        sideOffset={sideOffset}
        className={cn(FLOATING, 'w-72 p-4', className)}
        {...rest}
      />
    </RadixPopover.Portal>
  );
});

export const HoverCard = RadixHoverCard.Root;
export const HoverCardTrigger = RadixHoverCard.Trigger;

/** A preview on hover or focus — never the only way to reach what it shows. */
export const HoverCardContent = forwardRef<
  ElementRef<typeof RadixHoverCard.Content>,
  ComponentPropsWithoutRef<typeof RadixHoverCard.Content>
>(function HoverCardContent({ className, align = 'start', sideOffset = 8, ...rest }, ref) {
  return (
    <RadixHoverCard.Portal>
      <RadixHoverCard.Content
        ref={ref}
        align={align}
        sideOffset={sideOffset}
        className={cn(FLOATING, 'w-80 p-4', className)}
        {...rest}
      />
    </RadixHoverCard.Portal>
  );
});
