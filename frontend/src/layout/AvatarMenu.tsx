/**
 * The avatar menu (frontend-plan §7.1): who is signed in and as what role, the
 * theme (system, light, dark), My profile, and Sign out. On a narrow screen the
 * Settings rows move in here from the rail.
 */

import * as Menu from '@radix-ui/react-dropdown-menu';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { Icon } from '@/design/icons';
import type { UserRole } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { roleLabel, roleShortLabel, useAuth, useCurrentUser } from '@/platform/auth';
import { clearRecentCompanies } from '@/platform/shell';
import { applyTheme, readStoredTheme, storeTheme, THEMES, type Theme } from '@/platform/theme';
import { navRowsFor } from '@/routes/modules';

const THEME_LABEL: Record<Theme, string> = { system: 'System', light: 'Light', dark: 'Dark' };
const THEME_ICON = { system: Icon.themeSystem, light: Icon.themeLight, dark: Icon.themeDark };

const ITEM =
  'flex cursor-default select-none items-center gap-2.5 rounded-md px-2.5 py-1.5 text-body text-ink outline-none data-[highlighted]:bg-sunken';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters =
    parts.length > 1 ? `${parts[0]![0]!}${parts[parts.length - 1]![0]!}` : name.slice(0, 2);
  return letters.toUpperCase();
}

export function AvatarMenu({ role }: { role: UserRole }) {
  const user = useCurrentUser();
  const { logout } = useAuth();
  const [theme, setTheme] = useState<Theme>(readStoredTheme);
  const name = user.full_name ?? user.email;
  const settingsRows = navRowsFor(role).filter((row) => row.group === 'settings');

  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label={`Account: ${name}, ${roleLabel(user.role)}`}
        className="flex items-center gap-2 rounded-md py-1 pl-1 pr-2 transition-colors duration-quick hover:bg-sunken"
      >
        <span
          aria-hidden
          className="flex h-7 w-7 items-center justify-center rounded-full bg-sunken text-caption font-semibold text-ink-2 ring-1 ring-line-strong"
        >
          {initials(name)}
        </span>
        <span aria-hidden className="hidden text-secondary font-medium text-ink-2 sm:inline">
          {roleShortLabel(user.role)}
        </span>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content
          align="end"
          sideOffset={6}
          className="z-50 w-64 animate-float-in rounded-xl border border-line bg-raised p-1.5 shadow-float"
        >
          <div className="px-2.5 pb-2 pt-1.5">
            <p className="truncate text-body font-medium text-ink">{name}</p>
            {user.full_name && <p className="truncate text-secondary text-ink-3">{user.email}</p>}
            <p className="mt-1 text-caption text-ink-3">{roleLabel(user.role)}</p>
          </div>
          <Menu.Separator className="my-1 h-px bg-line" />
          <Menu.Label className="px-2.5 pb-1 pt-1.5 text-caption text-ink-3">Theme</Menu.Label>
          <Menu.RadioGroup
            value={theme}
            onValueChange={(value) => {
              const next = value as Theme;
              setTheme(next);
              storeTheme(next);
              applyTheme(next);
            }}
          >
            {THEMES.map((option) => {
              const Glyph = THEME_ICON[option];
              return (
                <Menu.RadioItem key={option} value={option} className={ITEM}>
                  <Glyph size={16} className="text-ink-3" aria-hidden />
                  <span className="flex-1">{THEME_LABEL[option]}</span>
                  <Menu.ItemIndicator>
                    <Icon.check size={14} aria-hidden />
                  </Menu.ItemIndicator>
                </Menu.RadioItem>
              );
            })}
          </Menu.RadioGroup>
          <Menu.Separator className="my-1 h-px bg-line" />
          <Menu.Item asChild className={ITEM}>
            <Link to="/settings">
              <Icon.person size={16} className="text-ink-3" aria-hidden />
              My profile
            </Link>
          </Menu.Item>
          {/* Narrow screens have no rail foot: its Settings rows live here instead. */}
          {settingsRows
            .filter((row) => row.to !== '/settings')
            .map((row) => {
              const Glyph = Icon[row.icon];
              return (
                <Menu.Item key={row.to} asChild className={cn(ITEM, 'lg:hidden')}>
                  <Link to={row.to}>
                    <Glyph size={16} className="text-ink-3" aria-hidden />
                    {row.label}
                  </Link>
                </Menu.Item>
              );
            })}
          <Menu.Separator className="my-1 h-px bg-line" />
          <Menu.Item
            className={ITEM}
            onSelect={() => {
              clearRecentCompanies(String(user.id));
              void logout();
            }}
          >
            <Icon.signOut size={16} className="text-ink-3" aria-hidden />
            Sign out
          </Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}
