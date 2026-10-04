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
 * (the module table gates them); the frame links to them for the role that has them.
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

type Section = 'profile' | 'users' | 'roles';

const SECTION_LABEL: Record<Section, string> = {
  profile: 'My profile',
  users: 'Users',
  roles: 'Roles',
};

function SectionLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          'relative block whitespace-nowrap rounded-md px-3 py-1.5 text-body transition-colors duration-quick',
          isActive ? 'font-medium text-ink lg:bg-sunken' : 'text-ink-2 hover:text-ink',
          // The active section carries an ink bar under it while the list runs
          // across the page; down the side, the sunken fill marks it instead.
          isActive &&
            'after:absolute after:inset-x-3 after:-bottom-px after:h-0.5 after:bg-ink lg:after:hidden',
        )
      }
    >
      {children}
    </NavLink>
  );
}

function SettingsFrame({ section, children }: { section: Section; children: ReactNode }) {
  const { can, isLoading, roleName } = usePermissions();
  const canViewUsers = can('users', 'view');
  const canViewRoles = can('roles', 'view');
  const canSetCriteria = useCan('settings.criteria');
  const canSetRequiredDocuments = useCan('settings.requiredDocuments');
  useCrumbs([{ label: 'Settings', to: '/settings' }, { label: SECTION_LABEL[section] }]);

  return (
    <div>
      <PageHeader
        title="Settings"
        description={
          <>
            {canViewUsers || canViewRoles
              ? 'Your details, the accounts that can sign in, and what each role may do.'
              : 'Your details and sessions.'}
            {roleName !== null && !isLoading && (
              <span className="text-ink-3"> Signed in as {roleName}.</span>
            )}
          </>
        }
      />
      <div className="grid gap-8 lg:grid-cols-[13rem_minmax(0,1fr)]">
        {/* A permission still loading renders no admin section speculatively: the
            links appear once the answer is in. */}
        <nav
          aria-label="Settings sections"
          className="-mx-1 flex gap-1 overflow-x-auto border-b border-line px-1 lg:sticky lg:top-0 lg:mx-0 lg:h-fit lg:flex-col lg:gap-0.5 lg:overflow-visible lg:border-b-0 lg:px-0"
        >
          <SectionLink to="/settings/profile">My profile</SectionLink>
          {canViewUsers && <SectionLink to="/settings/users">Users</SectionLink>}
          {canViewRoles && <SectionLink to="/settings/roles">Roles</SectionLink>}
          {(canSetCriteria || canSetRequiredDocuments) && (
            <p className="hidden px-3 pb-1 pt-4 text-caption font-medium text-ink-3 lg:block">
              Rules
            </p>
          )}
          {canSetCriteria && (
            <SectionLink to="/settings/qualification-criteria">Qualification criteria</SectionLink>
          )}
          {canSetRequiredDocuments && (
            <SectionLink to="/settings/deal-required-documents">Required documents</SectionLink>
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
