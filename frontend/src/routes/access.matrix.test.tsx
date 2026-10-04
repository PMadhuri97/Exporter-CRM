/**
 * The role matrix — R-33 Phase 0 (`docs/frontend-plan.md` §4.1, §4.3, §4.4).
 *
 * Every role × every screen, through the real router, shell and rail: whether the rail
 * offers it, and whether its URL renders it or the generic `NotFound`. Each screen is a
 * `React.lazy` stub that records being rendered; a forbidden one must never be. A lazy
 * screen is only imported when rendered (`platform/access/Gate.test.tsx` proves that
 * with a fresh one), so a screen never rendered is never downloaded and sends no
 * request — §4.3's "data for a section the role lacks is never requested".
 *
 * The expected sets are written out by hand from §4.1 and the server's route table,
 * not derived from the manifest, so a wrong manifest fails here.
 */

import { render, screen, within } from '@testing-library/react';
import { lazy } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { UserRole } from '@/lib/api/types';
import { useAuth, useCurrentUser } from '@/platform/auth';

import { AppRoutes } from './AppRouter';

const rendered = vi.hoisted(() => new Set<string>());

function Screen({ id }: { id: string }) {
  rendered.add(id);
  return <p data-testid="screen">{id}</p>;
}

/** A lazily loaded screen, as the real ones are. */
function stub(id: string) {
  return lazy(async () => ({ default: () => <Screen id={id} /> }));
}

vi.mock('@/modules/onboarding/lazyPages', () => ({
  AddExporterPage: stub('add-company'),
  CompanyImportPage: stub('import-companies'),
  DealDetailPage: stub('deal'),
  DealRequiredDocumentsPage: stub('required-documents'),
  ExporterDetailPage: stub('company'),
  ExportersListPage: stub('companies'),
  FollowUpsPage: stub('follow-ups'),
  IdentityCompletionPage: stub('identity-completion'),
  PipelinePage: stub('pipeline'),
  QualificationCriteriaPage: stub('criteria'),
  RxilIntakePage: stub('rxil-intake'),
}));
// The module table wraps this one in `lazy` itself.
vi.mock('@/pages/HomePage', () => ({ HomePage: () => <Screen id="home" /> }));
vi.mock('@/modules/settings', () => ({ SettingsRoutes: stub('settings') }));
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useAuth: vi.fn(),
  useCurrentUser: vi.fn(),
}));

const ROLES: UserRole[] = ['OPERATIONS', 'COMPLIANCE', 'ADMIN', 'DEVELOPER', 'API_USER'];
const READERS: UserRole[] = ['OPERATIONS', 'COMPLIANCE', 'ADMIN', 'DEVELOPER'];
const STAFF: UserRole[] = ['OPERATIONS', 'COMPLIANCE', 'ADMIN'];
const ADMIN: UserRole[] = ['ADMIN'];

const ID = '11111111-1111-4111-8111-111111111111';

/** [url, the screen it renders, who may open it] — §4.1. */
const SCREENS: [string, string, UserRole[]][] = [
  ['/', 'home', READERS],
  ['/companies', 'companies', READERS],
  ['/companies/new', 'add-company', STAFF],
  ['/companies/import', 'import-companies', STAFF],
  ['/companies/rxil-intake', 'rxil-intake', ADMIN],
  ['/companies/identity-completion', 'identity-completion', READERS],
  [`/companies/${ID}`, 'company', READERS],
  ['/follow-ups', 'follow-ups', READERS],
  ['/pipeline', 'pipeline', READERS],
  [`/deals/${ID}`, 'deal', READERS],
  // The old addresses redirect into the CRM, so they are the CRM's too.
  [`/exporters/${ID}`, 'company', READERS],
  ['/settings', 'settings', ROLES],
  ['/settings/qualification-criteria', 'criteria', ADMIN],
  ['/settings/deal-required-documents', 'required-documents', ADMIN],
];

/** [rail row, who sees it] — §7.2 on the current screens. */
const RAIL: [string, UserRole[]][] = [
  ['Home', READERS],
  ['Companies', READERS],
  ['Follow-ups', READERS],
  ['Pipeline', READERS],
  ['Settings', READERS],
  ['Qualification criteria', ADMIN],
  ['Required documents', ADMIN],
];

function signInAs(role: string) {
  const user = {
    id: 'user-1',
    email: 'someone@aner.example',
    full_name: 'Some One',
    role,
    is_active: true,
  } as unknown as ReturnType<typeof useCurrentUser>;
  vi.mocked(useCurrentUser).mockReturnValue(user);
  vi.mocked(useAuth).mockReturnValue({
    status: 'authenticated',
    user,
    login: vi.fn(),
    logout: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>);
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

/** What the page body renders, without the shell around it. */
function mainContent(): string {
  return document.querySelector('main')?.innerHTML ?? '';
}

beforeEach(() => {
  vi.clearAllMocks();
  rendered.clear();
});

describe('the route matrix: every role × every screen', () => {
  const cases = ROLES.flatMap((role) =>
    SCREENS.map(([url, id, allowed]) => [role, url, id, allowed.includes(role)] as const),
  );

  it.each(cases)('%s at %s', async (role, url, id, allowed) => {
    signInAs(role);
    if (allowed) {
      renderAt(url);
      expect(await screen.findByTestId('screen')).toHaveTextContent(id);
      expect([...rendered]).toEqual([id]);
      return;
    }

    // What an address that does not exist renders for this role, to compare against.
    const missing = renderAt('/no-such-address');
    await screen.findByRole('heading');
    const notFound = mainContent();
    missing.unmount();

    renderAt(url);
    await screen.findByRole('heading');
    if (url === '/') {
      // The root is where a user with no workspace lands.
      expect(screen.getByText(/doesn.t have access to a workspace/)).toBeInTheDocument();
    } else {
      // Indistinguishable from a page that does not exist (§4.3): same component,
      // same words. Never "Administrators only".
      expect(mainContent()).toBe(notFound);
      expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
      expect(screen.queryByText(/administrator/i)).not.toBeInTheDocument();
    }
    // Never rendered, so never imported, so nothing it would request was sent.
    expect([...rendered]).toEqual([]);
  });
});

describe('the rail', () => {
  it.each(READERS)('offers %s exactly the rows its role may follow', async (role) => {
    signInAs(role);
    renderAt('/settings');
    await screen.findByTestId('screen');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    for (const [label, who] of RAIL) {
      const row = within(nav).queryByRole('link', { name: label });
      if (who.includes(role)) expect(row).toBeInTheDocument();
      else expect(row).not.toBeInTheDocument();
    }
  });
});

describe('a user with no workspace (G1)', () => {
  // API_USER, and a role the manifest has never heard of: both fail closed.
  it.each(['API_USER', 'AUDITOR'])('%s gets no rail and no CRM words', async (role) => {
    signInAs(role);
    renderAt('/');
    expect(await screen.findByText(/doesn.t have access to a workspace/)).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();
    for (const word of ['Companies', 'Follow-ups', 'Pipeline', 'Qualification criteria']) {
      expect(screen.queryByText(word)).not.toBeInTheDocument();
    }
    expect(screen.getByRole('link', { name: 'My profile' })).toHaveAttribute('href', '/settings');
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
    expect([...rendered]).toEqual([]);
  });

  it('still reaches My profile, which every role may use', async () => {
    signInAs('API_USER');
    renderAt('/settings');
    expect(await screen.findByTestId('screen')).toHaveTextContent('settings');
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();
  });

  it('gets NotFound, not the CRM, from a CRM address', async () => {
    signInAs('AUDITOR');
    renderAt('/companies');
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    expect([...rendered]).toEqual([]);
  });
});
