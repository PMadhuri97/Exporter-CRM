import { useState } from 'react';

import { MyProfileTab } from '../components/MyProfileTab';
import { RolesTab } from '../components/RolesTab';
import { UsersTab } from '../components/UsersTab';
import { usePermissions } from '../usePermissions';

type Tab = 'profile' | 'users' | 'roles';

export function SettingsPage() {
  // Gated on permissions, not on `role === 'ADMIN'`: that is the point of role
  // management. Granting users:view to another role makes this tab appear for
  // them with no code change. A tab the user cannot use is absent rather than
  // disabled — a disabled tab still announces that the screen exists and they
  // are not allowed, the same leak the masking design rejects for the reveal icon.
  const { can, isLoading, roleName } = usePermissions();
  const canViewUsers = can('users', 'view');
  const canViewRoles = can('roles', 'view');
  const [tab, setTab] = useState<Tab>('profile');

  const tabs: { value: Tab; label: string }[] = [
    { value: 'profile', label: 'My profile' },
    ...(canViewUsers ? [{ value: 'users' as Tab, label: 'Users' }] : []),
    ...(canViewRoles ? [{ value: 'roles' as Tab, label: 'Roles' }] : []),
  ];

  // A permission that is still loading must not render an admin tab
  // speculatively, so the extra tabs appear only once the answer is in.
  const activeTab =
    (tab === 'users' && !canViewUsers) || (tab === 'roles' && !canViewRoles)
      ? 'profile'
      : tab;

  return (
    <div>
      <div className="mb-5">
        <h1 className="text-lg font-semibold text-ink">Settings</h1>
        <p className="text-sm text-ink-muted">
          {canViewUsers || canViewRoles
            ? 'Your details, the accounts that can sign in, and what each role may do.'
            : 'Your details and sessions.'}
          {roleName !== null && !isLoading && (
            <span className="text-ink-faint"> Signed in as {roleName}.</span>
          )}
        </p>
      </div>

      {tabs.length > 1 && (
        <div className="mb-4 flex gap-1 border-b border-border">
          {tabs.map((entry) => (
            <button
              key={entry.value}
              type="button"
              onClick={() => setTab(entry.value)}
              aria-current={activeTab === entry.value}
              className={`border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                activeTab === entry.value
                  ? 'border-brand-500 text-brand-600'
                  : 'border-transparent text-ink-muted hover:text-ink'
              }`}
            >
              {entry.label}
            </button>
          ))}
        </div>
      )}

      {activeTab === 'users' && <UsersTab />}
      {activeTab === 'roles' && <RolesTab />}
      {activeTab === 'profile' && <MyProfileTab />}
    </div>
  );
}
