/**
 * The user menu at the right of the app header (frontend-plan §6.1): who is signed in
 * and as what role, the theme (Light / Dark), My profile, and Sign out.
 */

import * as Menu from '@radix-ui/react-dropdown-menu';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { MENU_CONTENT, MENU_ITEM } from '@/components';
import { Icon } from '@/design/icons';
import { roleLabel, roleShortLabel, useAuth, useCurrentUser } from '@/platform/auth';
import { clearRecentCompanies } from '@/platform/shell';
import { applyTheme, readStoredTheme, storeTheme, THEMES, type Theme } from '@/platform/theme';

const THEME_LABEL: Record<Theme, string> = { light: 'Light', dark: 'Dark' };
const THEME_ICON = { light: Icon.themeLight, dark: Icon.themeDark };

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters =
    parts.length > 1 ? `${parts[0]![0]!}${parts[parts.length - 1]![0]!}` : name.slice(0, 2);
  return letters.toUpperCase();
}

export function UserMenu() {
  const user = useCurrentUser();
  const { logout } = useAuth();
  const [theme, setTheme] = useState<Theme>(readStoredTheme);
  const name = user.full_name ?? user.email;

  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label={`Account: ${name}, ${roleLabel(user.role)}`}
        className="flex h-8 items-center gap-2 rounded px-1.5 transition-colors duration-quick hover:bg-sunken"
      >
        <span aria-hidden className="hidden text-secondary font-semibold text-ink-2 sm:inline">
          {roleShortLabel(user.role)}
        </span>
        <span
          aria-hidden
          className="flex h-7 w-7 items-center justify-center rounded-full bg-accent-tint text-caption font-semibold text-accent"
        >
          {initials(name)}
        </span>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content align="end" sideOffset={6} className={`${MENU_CONTENT} w-64`}>
          <div className="px-2.5 pb-2 pt-1.5">
            <p className="truncate text-body font-semibold text-ink">{name}</p>
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
                <Menu.RadioItem key={option} value={option} className={MENU_ITEM}>
                  <Glyph size={16} className="text-ink-3" aria-hidden />
                  <span className="flex-1">{THEME_LABEL[option]}</span>
                  <Menu.ItemIndicator>
                    <Icon.check size={16} className="text-accent" aria-hidden />
                  </Menu.ItemIndicator>
                </Menu.RadioItem>
              );
            })}
          </Menu.RadioGroup>
          <Menu.Separator className="my-1 h-px bg-line" />
          <Menu.Item asChild className={MENU_ITEM}>
            <Link to="/settings">
              <Icon.person size={16} className="text-ink-3" aria-hidden />
              My profile
            </Link>
          </Menu.Item>
          <Menu.Item
            className={MENU_ITEM}
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
