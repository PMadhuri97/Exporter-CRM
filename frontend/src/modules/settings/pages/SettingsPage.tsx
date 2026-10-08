/**
 * Settings (frontend-plan §8.9): one frame, a section per address — `/settings/profile`
 * (where `/settings` lands), `/settings/users`, `/settings/roles`. The frame lists only
 * the sections this person may open, and an address they may not open shows the same
 * NotFound as an address that does not exist.
 *
 * Users and Roles are gated on the server's permissions (`users:view`, `roles:view`),
 * not on `role === 'ADMIN'`: that is the point of role management — granting
 * `users:view` to another role makes the section appear for them with no code change.
 * A section is absent rather than disabled: a disabled link still announces that the
 * screen exists and they are not allowed, the leak the masking design rejects for the
 * reveal icon. Qualification criteria and Required documents are their own modules
 * (the module table gates them), drawn inside this frame (`SettingsFrame` is exported
 * for them), so every settings section has the same left list.
 */

import type { ReactNode } from 'react';
import { Navigate, NavLink, Route, Routes } from 'react-router-dom';

import { NotFound, PageHeader, Skeleton } from '@/components';
import { cn } from '@/lib/cn';
import { useCan } from '@/platform/access';
import { useCrumbs } from '@/platform/shell';

import { MyProfileTab } from '../components/MyProfileTab';
import { RolesTab } from '../components/RolesTab';
import { UsersTab } from '../components/UsersTab';
import { usePermissions } from '../usePermissions';

export type SettingsSection =
  | 'profile'
  | 'users'
  | 'roles'
  | 'criteria'
  | 'requiredDocuments'
  | 'paymentTerms';
type Section = SettingsSection;

const SECTION_LABEL: Record<Section, string> = {
  profile: 'My profile',
  users: 'Users',
  roles: 'Roles',
  criteria: 'Qualification criteria',
  requiredDocuments: 'Required documents',
  paymentTerms: 'Payment terms',
};

function SectionLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          'relative block whitespace-nowrap rounded px-3 py-1.5 text-body transition-colors duration-quick',
          isActive ? 'font-semibold text-accent lg:bg-accent-tint' : 'text-ink-2 hover:bg-sunken hover:text-ink',
          // The current section carries a blue bar under it while the list runs
          // across the page, and a tint with a bar on its left down the side.
          isActive &&
            'after:absolute after:inset-x-3 after:-bottom-px after:h-0.5 after:bg-accent-solid lg:after:inset-x-auto lg:after:inset-y-1 lg:after:left-0 lg:after:h-auto lg:after:w-[3px]',
        )
      }
    >
      {children}
    </NavLink>
  );
}

/**
 * One group of the side list: who can sign in and what they may do ("Access"), apart
 * from how the CRM itself behaves ("System configuration"). The heading shows down the
 * side; across a narrow page the separator between the groups does the same job.
 */
function SectionGroup({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <div role="group" aria-labelledby={id} className="flex gap-1 lg:flex-col lg:gap-0.5">
      <p
        id={id}
        className="hidden px-3 pb-1 pt-1 text-caption font-semibold uppercase tracking-wide text-ink-2 lg:block"
      >
        {title}
      </p>
      {children}
    </div>
  );
}

export function SettingsFrame({ section, children }: { section: Section; children: ReactNode }) {
  const { can, isLoading, roleName } = usePermissions();
  const canViewUsers = can('users', 'view');
  const canViewRoles = can('roles', 'view');
  const canSetCriteria = useCan('settings.criteria');
  const canSetRequiredDocuments = useCan('settings.requiredDocuments');
  const canSetPaymentTerms = useCan('settings.paymentTerms');
  useCrumbs([{ label: 'Settings', to: '/settings' }, { label: SECTION_LABEL[section] }]);

  return (
    <div>
      <PageHeader
        title="Settings"
        description={roleName !== null && !isLoading ? `Signed in as ${roleName}.` : undefined}
      />
      <div className="grid gap-4 lg:grid-cols-[13rem_minmax(0,1fr)]">
        {/* A permission still loading renders no admin section speculatively: the
            links appear once the answer is in. */}
        <nav
          aria-label="Settings sections"
          className="flex gap-1 overflow-x-auto rounded border border-line bg-surface p-1 lg:sticky lg:top-0 lg:h-fit lg:flex-col lg:gap-0.5 lg:overflow-visible lg:p-2"
        >
          <SectionGroup id="settings-access" title="Access">
            <SectionLink to="/settings/profile">My profile</SectionLink>
            {canViewUsers && <SectionLink to="/settings/users">Users</SectionLink>}
            {canViewRoles && <SectionLink to="/settings/roles">Roles</SectionLink>}
          </SectionGroup>
          {(canSetCriteria || canSetRequiredDocuments || canSetPaymentTerms) && (
            <>
              <span
                role="separator"
                className="mx-1 w-px shrink-0 self-stretch bg-line lg:mx-1 lg:my-2 lg:h-px lg:w-auto"
              />
              <SectionGroup id="settings-system" title="System configuration">
                {canSetCriteria && (
                  <SectionLink to="/settings/qualification-criteria">Qualification criteria</SectionLink>
                )}
                {canSetRequiredDocuments && (
                  <SectionLink to="/settings/deal-required-documents">Required documents</SectionLink>
                )}
                {canSetPaymentTerms && (
                  <SectionLink to="/settings/payment-terms">Payment terms</SectionLink>
                )}
              </SectionGroup>
            </>
          )}
        </nav>
        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}

/**
 * A section behind a server permission. While the answer is loading nothing is
 * claimed either way — no section, and no "not here" that would flash before it.
 */
function PermittedSection({ section }: { section: 'users' | 'roles' }) {
  const { can, isLoading } = usePermissions();
  if (isLoading) {
    return (
      <div className="space-y-3" aria-hidden>
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-40" />
      </div>
    );
  }
  if (!can(section, 'view')) return <NotFound />;
  return (
    <SettingsFrame section={section}>
      {section === 'users' ? <UsersTab /> : <RolesTab />}
    </SettingsFrame>
  );
}

export function SettingsPage() {
  return (
    <Routes>
      <Route index element={<Navigate to="profile" replace />} />
      <Route
        path="profile"
        element={
          <SettingsFrame section="profile">
            <MyProfileTab />
          </SettingsFrame>
        }
      />
      <Route path="users" element={<PermittedSection section="users" />} />
      <Route path="roles" element={<PermittedSection section="roles" />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
