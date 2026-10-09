/**
 * The record header (frontend-plan §6.3): what the record is, its key fields, and
 * its actions — the Salesforce highlights panel, the Dynamics form header, the Fiori
 * dynamic page header.
 *
 * - The object type ("Company", "Deal") in small grey type above a 20/28 title, and
 *   one metadata line under it.
 * - Up to six key fields, label above value. A field the role may not see is not
 *   passed at all, so it is absent, never greyed.
 * - Actions, built by the caller **only** from served fields. At most three show,
 *   the first primary; the rest go under *More*. No actions, no buttons.
 * - The path, in a strip under the header.
 * - Scrolled past, it compresses to a sticky bar with the title, the badges and
 *   the actions.
 */

import * as Menu from '@radix-ui/react-dropdown-menu';
import { useEffect, useRef, useState, type ReactNode } from 'react';

import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

import { Breadcrumbs, type Crumb } from './Breadcrumbs';
import { Button } from './Button';
import { MENU_CONTENT, MENU_ITEM } from './styles';

export interface RecordField {
  label: string;
  value: ReactNode;
  /** A short explanation, shown when hovering the label. */
  hint?: string;
}

export interface RecordAction {
  label: string;
  onSelect: () => void;
  /** Drawn in the negative colour inside *More* (End, Withdraw). */
  destructive?: boolean;
  /** Pending: the button shows its own spinner. */
  loading?: boolean;
}

/** How many actions show as buttons before the rest go under *More*. */
const SHOWN = 3;

function Actions({ actions, size = 'md' }: { actions: readonly RecordAction[]; size?: 'sm' | 'md' }) {
  if (actions.length === 0) return null;
  // With more than three, two buttons and *More* keep the row at three controls.
  const shown = actions.length > SHOWN ? actions.slice(0, SHOWN - 1) : actions;
  const more = actions.length > SHOWN ? actions.slice(SHOWN - 1) : [];
  return (
    <div className="flex flex-wrap items-center gap-2">
      {shown.map((action, index) => (
        <Button
          key={action.label}
          size={size}
          // The first action is the primary one, unless it cannot be undone.
          variant={index === 0 && !action.destructive ? 'primary' : 'secondary'}
          loading={action.loading}
          onClick={action.onSelect}
        >
          {action.label}
        </Button>
      ))}
      {more.length > 0 && (
        <Menu.Root>
          <Menu.Trigger asChild>
            <Button size={size}>
              More
              <Icon.caretDown size={14} aria-hidden />
            </Button>
          </Menu.Trigger>
          <Menu.Portal>
            <Menu.Content align="end" sideOffset={4} className={MENU_CONTENT}>
              {more.map((action) => (
                <Menu.Item
                  key={action.label}
                  onSelect={action.onSelect}
                  className={cn(MENU_ITEM, action.destructive && 'text-negative')}
                >
                  {action.label}
                </Menu.Item>
              ))}
            </Menu.Content>
          </Menu.Portal>
        </Menu.Root>
      )}
    </div>
  );
}

export function RecordHeader({
  objectType,
  title,
  titleBadges,
  meta,
  fields = [],
  actions = [],
  path,
  breadcrumbs,
  className,
}: {
  objectType: string;
  title: ReactNode;
  /** Badges beside the title (a marker, "Outside pipeline"); repeated in the sticky bar. */
  titleBadges?: ReactNode;
  /** One line of facts under the title. */
  meta?: ReactNode;
  fields?: readonly RecordField[];
  actions?: readonly RecordAction[];
  /** The path strip under the header (§6.5). */
  path?: ReactNode;
  breadcrumbs?: readonly Crumb[];
  className?: string;
}) {
  const sentinel = useRef<HTMLDivElement>(null);
  const [compact, setCompact] = useState(false);

  useEffect(() => {
    const target = sentinel.current;
    if (!target || typeof IntersectionObserver === 'undefined') return;
    // The bar shows once the header's last line has scrolled out of view upwards.
    const observer = new IntersectionObserver(([entry]) => {
      if (entry) setCompact(!entry.isIntersecting && entry.boundingClientRect.top < 0);
    });
    observer.observe(target);
    return () => observer.disconnect();
  }, []);

  return (
    <>
      {/* A zero-height sticky anchor, so the hidden bar takes no space in the page. */}
      <div className="sticky top-0 z-20 h-0">
        <div
          aria-hidden={!compact}
          // `inert` keeps the hidden bar's buttons out of the tab order.
          {...(!compact ? { inert: '' } : {})}
          className={cn(
            'absolute inset-x-0 top-0 -mx-4 flex h-12 items-center justify-between gap-4 border-b border-line bg-surface px-4 shadow-float transition-opacity duration-pop sm:-mx-6 sm:px-6',
            compact ? 'opacity-100' : 'pointer-events-none opacity-0',
          )}
          data-record-header-bar
        >
          <div className="flex min-w-0 items-center gap-3">
            <span className="truncate text-heading font-semibold text-ink">{title}</span>
            {titleBadges && <span className="hidden items-center gap-1.5 md:flex">{titleBadges}</span>}
          </div>
          <Actions actions={actions} size="sm" />
        </div>
      </div>

      <header className={cn('rounded border border-line bg-surface', className)}>
        <div className="px-4 pb-4 pt-3 sm:px-6">
          {breadcrumbs && <Breadcrumbs items={breadcrumbs} className="mb-2" />}
          <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
            <div className="min-w-0">
              <p className="text-caption text-ink-3">{objectType}</p>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <h1 className="text-title font-semibold text-ink [overflow-wrap:anywhere]">{title}</h1>
                {titleBadges}
              </div>
              {meta && <p className="mt-0.5 text-secondary text-ink-2">{meta}</p>}
            </div>
            <Actions actions={actions} />
          </div>
          {fields.length > 0 && (
            <dl className="mt-4 flex flex-wrap gap-x-10 gap-y-3 border-t border-line pt-3">
              {fields.slice(0, 6).map((field) => (
                <div key={field.label} className="min-w-0">
                  <dt className="text-caption text-ink-3" title={field.hint}>
                    {field.label}
                  </dt>
                  <dd className="mt-0.5 text-body text-ink">{field.value}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
        {path && <div className="border-t border-line px-4 py-3 sm:px-6">{path}</div>}
        <div ref={sentinel} aria-hidden />
      </header>
    </>
  );
}
