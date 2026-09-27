/**
 * Tabs on Radix — roving focus, arrow keys, and the tab/tabpanel wiring a
 * screen reader needs.
 *
 * Always controlled (`value` + `onValueChange`). Radix switches on mouse-down;
 * the trigger here also switches on click. In a browser a mouse-down always
 * precedes the click, so nothing changes there, and a plain synthetic `click`
 * (a test's, or an assistive tool's) still works.
 */

import * as RadixTabs from '@radix-ui/react-tabs';
import { createContext, useContext, type ComponentPropsWithoutRef, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

type TabsVariant = 'underline' | 'pill';

const TabsContext = createContext<{
  onValueChange: (value: string) => void;
  variant: TabsVariant;
}>({ onValueChange: () => undefined, variant: 'underline' });

export function Tabs({
  value,
  onValueChange,
  variant = 'underline',
  className,
  children,
}: {
  value: string;
  onValueChange: (value: string) => void;
  /** `underline` for page sections, `pill` for filters inside a card. */
  variant?: TabsVariant;
  className?: string;
  children: ReactNode;
}) {
  return (
    <TabsContext.Provider value={{ onValueChange, variant }}>
      <RadixTabs.Root value={value} onValueChange={onValueChange} className={className}>
        {children}
      </RadixTabs.Root>
    </TabsContext.Provider>
  );
}

export function TabsList({
  className,
  ...rest
}: ComponentPropsWithoutRef<typeof RadixTabs.List>) {
  const { variant } = useContext(TabsContext);
  return (
    <RadixTabs.List
      className={cn(
        variant === 'underline'
          ? 'flex gap-1 overflow-x-auto border-b border-border'
          : 'inline-flex flex-wrap gap-1 rounded-lg bg-surface-sunken p-1',
        className,
      )}
      {...rest}
    />
  );
}

export function TabsTrigger({
  value,
  className,
  onClick,
  ...rest
}: ComponentPropsWithoutRef<typeof RadixTabs.Trigger>) {
  const { onValueChange, variant } = useContext(TabsContext);
  return (
    <RadixTabs.Trigger
      value={value}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented && !rest.disabled) onValueChange(value);
      }}
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap text-sm font-medium transition-colors',
        variant === 'underline'
          ? '-mb-px border-b-2 border-transparent px-3 py-2.5 text-ink-muted hover:text-ink data-[state=active]:border-brand-600 data-[state=active]:text-ink'
          : 'rounded-md px-3 py-1.5 text-ink-muted hover:text-ink data-[state=active]:bg-surface data-[state=active]:text-ink data-[state=active]:shadow-card',
        className,
      )}
      {...rest}
    />
  );
}

export function TabsContent({
  className,
  ...rest
}: ComponentPropsWithoutRef<typeof RadixTabs.Content>) {
  return <RadixTabs.Content className={cn('outline-none', className)} {...rest} />;
}
