import { useState } from 'react';

import { useCurrentUser } from '@/platform/auth';

import { MyProfileTab } from '../components/MyProfileTab';
import { UsersTab } from '../components/UsersTab';

type Tab = 'profile' | 'users';

export function SettingsPage() {
  const user = useCurrentUser();
  // Managing other accounts is ADMIN-only on the server. A non-admin gets no
  // Users tab at all rather than a disabled one: a disabled tab still tells
  // them the screen exists and they are not allowed, which is the same leak the
  // masking design rejects for the reveal icon.
  const canManageUsers = user.role === 'ADMIN';
  const [tab, setTab] = useState<Tab>('profile');

  const tabs: { value: Tab; label: string }[] = [
    { value: 'profile', label: 'My profile' },
    ...(canManageUsers ? [{ value: 'users' as Tab, label: 'Users' }] : []),
  ];

  return (
    <div>
      <div className="mb-5">
        <h1 className="text-lg font-semibold text-ink">Settings</h1>
        <p className="text-sm text-ink-muted">
          {canManageUsers
            ? 'Your details, and the accounts that can sign in.'
            : 'Your details and sessions.'}
        </p>
      </div>

      {tabs.length > 1 && (
        <div className="mb-4 flex gap-1 border-b border-border">
          {tabs.map((entry) => (
            <button
              key={entry.value}
              type="button"
              onClick={() => setTab(entry.value)}
              aria-current={tab === entry.value}
              className={`border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                tab === entry.value
                  ? 'border-brand-500 text-brand-600'
                  : 'border-transparent text-ink-muted hover:text-ink'
              }`}
            >
              {entry.label}
            </button>
          ))}
        </div>
      )}

      {tab === 'users' && canManageUsers ? <UsersTab /> : <MyProfileTab />}
    </div>
  );
}
