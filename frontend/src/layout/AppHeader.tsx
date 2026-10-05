/**
 * The app header (frontend-plan §6.1, §7.2), 48px: the wordmark (to Home), search,
 * *+ New* when the role may create, and the user menu. Under 1024px a menu button
 * opens the navigation drawer. Breadcrumbs are not here: each page carries its own,
 * as enterprise apps do.
 */

import { Link } from 'react-router-dom';

import { BrandMark } from '@/design/BrandMark';
import { Icon } from '@/design/icons';
import type { UserRole } from '@/lib/api/types';

import { HeaderSearch } from './HeaderSearch';
import { NewMenu } from './NewMenu';
import { UserMenu } from './UserMenu';

export function AppHeader({
  role,
  searchOpen,
  onSearchOpenChange,
  onOpenNav,
}: {
  role: UserRole;
  searchOpen: boolean;
  onSearchOpenChange: (open: boolean) => void;
  onOpenNav: () => void;
}) {
  return (
    <header className="relative z-30 flex h-12 shrink-0 items-center gap-3 border-b border-line bg-surface px-3 sm:gap-4 sm:px-4">
      <button
        type="button"
        onClick={onOpenNav}
        aria-label="Open the navigation"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded text-ink-2 transition-colors duration-quick hover:bg-sunken hover:text-ink lg:hidden"
      >
        <Icon.menu size={20} aria-hidden />
      </button>
      <Link to="/" aria-label="Home" className="shrink-0 rounded">
        <span className="hidden md:inline-flex">
          <BrandMark />
        </span>
        <span className="md:hidden">
          <BrandMark wordmark={false} />
        </span>
      </Link>
      <div className="flex min-w-0 flex-1 justify-center px-1 md:px-4">
        <HeaderSearch role={role} open={searchOpen} onOpenChange={onSearchOpenChange} />
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <NewMenu />
        <UserMenu />
      </div>
    </header>
  );
}
