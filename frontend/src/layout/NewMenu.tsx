/**
 * *+ New* in the app header (frontend-plan §6.1): the quick-create entries the role
 * has — New company, New deal, Import companies, and RXIL intake for Admin. Absent when the
 * role may create nothing (§4.1), never a disabled button.
 */

import * as Menu from '@radix-ui/react-dropdown-menu';
import { Link } from 'react-router-dom';

import { buttonClasses, MENU_CONTENT, MENU_ITEM } from '@/components';
import { Icon, type IconName } from '@/design/icons';
import { paths } from '@/modules/onboarding';
import { useCan, type Capability } from '@/platform/access';

const ENTRIES: { label: string; to: string; icon: IconName; requires: Capability }[] = [
  { label: 'New company', to: paths.newCompany, icon: 'company', requires: 'company.create' },
  { label: 'New deal', to: paths.newDeal, icon: 'deal', requires: 'crm.write' },
  { label: 'Import companies', to: paths.importCompanies, icon: 'upload', requires: 'company.import' },
  { label: 'RXIL intake', to: paths.rxilIntake, icon: 'receipt', requires: 'company.rxilIntake' },
];

export function NewMenu() {
  const allowed = {
    'company.create': useCan('company.create'),
    'crm.write': useCan('crm.write'),
    'company.import': useCan('company.import'),
    'company.rxilIntake': useCan('company.rxilIntake'),
  } as Partial<Record<Capability, boolean>>;
  const entries = ENTRIES.filter((entry) => allowed[entry.requires]);
  if (entries.length === 0) return null;

  return (
    <Menu.Root>
      <Menu.Trigger className={buttonClasses({ variant: 'primary', className: 'px-2.5' })}>
        <Icon.add size={16} aria-hidden />
        <span className="hidden sm:inline">New</span>
        <span className="sr-only sm:hidden">New</span>
        <Icon.caretDown size={14} aria-hidden />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content align="end" sideOffset={6} className={MENU_CONTENT}>
          {entries.map((entry) => {
            const Glyph = Icon[entry.icon];
            return (
              <Menu.Item key={entry.to} asChild className={MENU_ITEM}>
                <Link to={entry.to}>
                  <Glyph size={16} className="text-ink-3" aria-hidden />
                  {entry.label}
                </Link>
              </Menu.Item>
            );
          })}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}
