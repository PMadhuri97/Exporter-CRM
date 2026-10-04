/**
 * The style guide (frontend-plan §12.4) — every token and primitive, in every
 * state, light and dark side by side. Mounted at `/__design` only when
 * `import.meta.env.DEV` (see `routes/AppRouter.tsx`), so the production build
 * never contains it; it doubles as the visual review page for the TL.
 *
 * Static fixtures only: it makes no request and needs no sign-in. Floating
 * layers (popovers, sheets) portal to the page body, so they take the page's
 * theme rather than their pane's.
 */

import { useState, type ReactNode } from 'react';

import {
  Button,
  Card,
  ConfirmDialog,
  Count,
  DatePopover,
  DetailRow,
  Editable,
  EmptyLine,
  ErrorState,
  Field,
  FormError,
  InlineError,
  Input,
  Kbd,
  Panel,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Segmented,
  Select,
  Sheet,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Tag,
  Textarea,
  type TagTone,
} from '@/components';

import { OnboardingStyleGuide } from '@/modules/onboarding';

import { BrandMark } from '../BrandMark';
import { Icon, type IconName } from '../icons';

const NEUTRALS = ['paper', 'surface', 'raised', 'sunken', 'line', 'line-strong', 'ink', 'ink-2', 'ink-3', 'ink-4'];
const MEANINGS = ['positive', 'negative', 'attention', 'progress', 'idle'] as const;
const TONES: TagTone[] = ['idle', 'positive', 'negative', 'attention', 'progress', 'ink'];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line pt-4">
      <h2 className="text-lead font-semibold text-ink">{title}</h2>
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-2 sm:grid-cols-[8rem_1fr] sm:items-center">
      <span className="text-caption text-ink-3">{label}</span>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

function Swatch({ name }: { name: string }) {
  return (
    <div className="w-24">
      <div className="h-10 rounded-md border border-line" style={{ background: `rgb(var(--${name}))` }} />
      <p className="mt-1 font-mono text-[11px] text-ink-2">{name}</p>
    </div>
  );
}

function Palette() {
  return (
    <Section title="Colour">
      <Row label="Paper and ink">
        {NEUTRALS.map((name) => (
          <Swatch key={name} name={name} />
        ))}
      </Row>
      {MEANINGS.map((meaning) => (
        <Row key={meaning} label={meaning}>
          <Swatch name={meaning} />
          <Swatch name={`${meaning}-tint`} />
          <Swatch name={`${meaning}-solid`} />
        </Row>
      ))}
    </Section>
  );
}

function Type() {
  return (
    <Section title="Type">
      <p className="font-display text-display-xl text-ink">Every company, one record.</p>
      <p className="font-display text-display-lg text-ink">Bharat Precision Metals</p>
      <p className="font-display text-display-md italic text-ink">Rotterdam shipment</p>
      <p className="font-display text-display-sm text-ink">Nothing here.</p>
      <p className="text-lead text-ink">Lead 15 — 3 follow-ups overdue · 2 companies to check back on</p>
      <p className="text-body text-ink">Body 14 — the default size for everything that is read.</p>
      <p className="text-secondary text-ink-2">Secondary 13 — supporting lines, metadata.</p>
      <p className="text-caption text-ink-3">Caption 12 — labels, in sentence case.</p>
      <p className="data text-ink">PAN AAAPL1234C · GSTIN 27AAAPL1234C1ZV · DL-2026-0041 · ₹ 1,40,00,000</p>
      <p className="text-body tabular-nums text-ink-2">0123456789 · 1,111 · 9,999 (tabular figures line up)</p>
    </Section>
  );
}

function Buttons() {
  return (
    <Section title="Buttons">
      {(['md', 'sm'] as const).map((size) => (
        <Row key={size} label={size === 'md' ? '36 px' : '32 px'}>
          <Button variant="primary" size={size}>
            Hand over
          </Button>
          <Button variant="secondary" size={size}>
            Open a deal
          </Button>
          <Button variant="quiet" size={size}>
            Cancel
          </Button>
          <Button variant="destructive" size={size}>
            Withdraw
          </Button>
          <Button variant="primary" size={size} loading>
            Saving
          </Button>
          <Button variant="secondary" size={size} disabled>
            Not right now
          </Button>
        </Row>
      ))}
    </Section>
  );
}

function Tags() {
  return (
    <Section title="Tags">
      <Row label="Tones">
        {TONES.map((tone) => (
          <Tag key={tone} tone={tone}>
            {tone}
          </Tag>
        ))}
      </Row>
      <Row label="With a dot">
        {TONES.map((tone) => (
          <Tag key={tone} tone={tone} dot>
            {tone}
          </Tag>
        ))}
      </Row>
      <Row label="Awaiting approval">
        <span className="inline-flex items-center rounded-sm border border-dashed border-ink px-1.5 py-0.5 text-caption font-medium text-ink">
          Awaiting approval
        </span>
      </Row>
      <Row label="Critical (the one filled mark)">
        <span className="hatch inline-flex items-center gap-1.5 rounded-sm bg-negative-solid px-1.5 py-0.5 text-caption font-bold text-white">
          ! Critical risk
        </span>
      </Row>
    </Section>
  );
}

function Controls() {
  const [lens, setLens] = useState<'all' | 'leads' | 'prospects' | 'customers'>('all');
  const [result, setResult] = useState<'PASS' | 'FAIL' | 'UNKNOWN'>('PASS');
  const [date, setDate] = useState<string | null>('2026-11-12');
  const [industry, setIndustry] = useState<string | null>('Precision engineering');
  const [country, setCountry] = useState<string | null>('IN');
  const [tab, setTab] = useState('overview');

  return (
    <Section title="Controls">
      <Row label="Segmented">
        <Segmented
          label="Journey"
          value={lens}
          onValueChange={setLens}
          options={[
            { value: 'all', label: 'All' },
            { value: 'leads', label: 'Leads', count: 48 },
            { value: 'prospects', label: 'Prospects', count: 21 },
            { value: 'customers', label: 'Customers', count: '200+' },
          ]}
        />
        <Segmented
          label="Result"
          size="sm"
          value={result}
          onValueChange={setResult}
          options={[
            { value: 'PASS', label: 'Pass' },
            { value: 'FAIL', label: 'Fail' },
            { value: 'UNKNOWN', label: 'Unknown' },
          ]}
        />
      </Row>
      <Row label="Date popover">
        <DatePopover label="Check back on" value={date} onChange={setDate} verb="Park until then" />
        <DatePopover label="Due" value={null} onChange={setDate} />
      </Row>
      <Row label="Editable">
        <dl className="w-full max-w-md">
          <DetailRow label="Industry">
            <Editable label="Industry" value={industry} onSave={setIndustry} />
          </DetailRow>
          <DetailRow label="Country">
            <Editable
              label="Country"
              kind="select"
              value={country}
              onSave={setCountry}
              options={[
                { value: 'IN', label: 'India' },
                { value: 'NL', label: 'Netherlands' },
                { value: 'DE', label: 'Germany' },
              ]}
              display={country === 'IN' ? 'India' : country === 'NL' ? 'Netherlands' : 'Germany'}
            />
          </DetailRow>
          <DetailRow label="Refused">
            <Editable
              label="Year founded"
              kind="number"
              value="2009"
              onSave={() => Promise.reject(new Error('Year founded cannot be in the future.'))}
            />
          </DetailRow>
          <DetailRow label="Read only">
            <Editable label="Industry" value="Seafood" onSave={() => undefined} readOnly />
          </DetailRow>
        </dl>
      </Row>
      <Row label="Tabs">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="overview">Profile</TabsTrigger>
            <TabsTrigger value="qualification">Qualification</TabsTrigger>
            <TabsTrigger value="history">Ledger</TabsTrigger>
          </TabsList>
          {['overview', 'qualification', 'history'].map((key) => (
            <TabsContent key={key} value={key} className="pt-3 text-secondary text-ink-2">
              The {key} chapter.
            </TabsContent>
          ))}
        </Tabs>
      </Row>
    </Section>
  );
}

function Fields() {
  return (
    <Section title="Fields">
      <div className="grid max-w-2xl gap-4 sm:grid-cols-2">
        <Field label="Company name" htmlFor="sg-name" required>
          <Input id="sg-name" placeholder="Lakshmi Polymers Pvt Ltd" />
        </Field>
        <Field label="Source" htmlFor="sg-source" hint="Where the lead came from.">
          <Select id="sg-source" defaultValue="SALES">
            <option value="SALES">Sales</option>
            <option value="REFERRAL">Referral</option>
          </Select>
        </Field>
        <Field label="PAN" htmlFor="sg-pan" error="This PAN belongs to another company.">
          <Input id="sg-pan" defaultValue="AAAPL1234C" aria-invalid />
        </Field>
        <Field label="Disabled" htmlFor="sg-disabled">
          <Input id="sg-disabled" disabled value="Not editable here" readOnly />
        </Field>
        <Field label="Reason" htmlFor="sg-reason" className="sm:col-span-2">
          <Textarea id="sg-reason" rows={2} placeholder="Why this decision" />
        </Field>
      </div>
      <FormError>Couldn&apos;t hand over: the seller&apos;s background check is not clear.</FormError>
    </Section>
  );
}

function Surfaces() {
  const [dialog, setDialog] = useState(false);
  const [sheet, setSheet] = useState(false);
  return (
    <Section title="Surfaces">
      <Row label="Floating">
        <Popover>
          <PopoverTrigger asChild>
            <Button>Open a popover</Button>
          </PopoverTrigger>
          <PopoverContent>
            <p className="text-body font-medium text-ink">Approve this Clear?</p>
            <p className="mt-1 text-secondary text-ink-2">Proposed by R. Mehta at 11:02.</p>
            <div className="mt-3 flex justify-end gap-2">
              <Button size="sm" variant="quiet">
                Cancel
              </Button>
              <Button size="sm" variant="primary">
                Approve
              </Button>
            </div>
          </PopoverContent>
        </Popover>
        <Button onClick={() => setDialog(true)}>Open a dialog</Button>
        <Button onClick={() => setSheet(true)}>Open a sheet</Button>
        <ConfirmDialog
          open={dialog}
          onOpenChange={setDialog}
          title="Hand over this deal?"
          description="This cannot be undone. The receipt is sealed at this moment."
          confirmLabel="Hand over"
          onConfirm={() => setDialog(false)}
        />
        <Sheet
          open={sheet}
          onOpenChange={setSheet}
          title="Log a call"
          footer={
            <Button variant="primary" onClick={() => setSheet(false)}>
              Log it
            </Button>
          }
        >
          <Field label="Subject" htmlFor="sg-subject">
            <Input id="sg-subject" placeholder="Called about bank statements" />
          </Field>
        </Sheet>
      </Row>
      <Card className="max-w-md p-4">
        <p className="text-body font-medium text-ink">A card: hairline, no shadow</p>
        <p className="mt-1 text-secondary text-ink-2">For one object — a receipt, a party, a composer.</p>
      </Card>
      <Panel title="A section" description="Heading, whitespace and one hairline — no box." actions={<Button size="sm">Act</Button>}>
        <p className="text-body text-ink-2">Sections stack like chapters of one page.</p>
      </Panel>
    </Section>
  );
}

function States() {
  return (
    <Section title="States">
      <Row label="Counts">
        <Count value={48} />
        <Count value={21} size="lg" />
        <Count value={200} cap={200} />
      </Row>
      <Row label="Empty">
        <EmptyLine action={<Button size="sm">Log a call</Button>}>No activity yet.</EmptyLine>
      </Row>
      <Row label="Inline error">
        <InlineError onRetry={() => undefined}>Couldn&apos;t load the ledger: the server did not answer.</InlineError>
      </Row>
      <Row label="Section error">
        <ErrorState title="Couldn't load this company" onRetry={() => undefined}>
          The server said: company not found.
        </ErrorState>
      </Row>
      <Row label="Loading">
        <div className="w-full max-w-md space-y-2">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-5/6" />
        </div>
      </Row>
      <Row label="Keys">
        <Kbd>⌘</Kbd>
        <Kbd>K</Kbd>
        <span className="text-secondary text-ink-3">then</span>
        <Kbd>g</Kbd>
        <Kbd>c</Kbd>
      </Row>
    </Section>
  );
}

function Icons() {
  const names = Object.keys(Icon) as IconName[];
  return (
    <Section title="Icons">
      <div className="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-2">
        {names.map((name) => {
          const Glyph = Icon[name];
          return (
            <div key={name} className="flex items-center gap-2 text-ink-2">
              <Glyph size={18} aria-hidden />
              <span className="truncate font-mono text-[11px]">{name}</span>
            </div>
          );
        })}
      </div>
    </Section>
  );
}

function Pane({ theme }: { theme: 'light' | 'dark' }) {
  return (
    <div
      data-theme={theme}
      data-testid={`styleguide-${theme}`}
      className="min-w-0 space-y-8 bg-paper p-6 text-body text-ink sm:p-8"
    >
      <header className="flex items-center justify-between gap-4">
        <BrandMark />
        <span className="text-caption text-ink-3">{theme === 'light' ? 'Light' : 'Dark'}</span>
      </header>
      <Palette />
      <Type />
      <Buttons />
      <Tags />
      <Controls />
      <Fields />
      <Surfaces />
      <States />
      <Icons />
      <OnboardingStyleGuide />
    </div>
  );
}

export function StyleGuidePage() {
  return (
    <main className="min-h-screen bg-paper">
      <h1 className="sr-only">Style guide</h1>
      <div className="grid xl:grid-cols-2">
        <Pane theme="light" />
        <Pane theme="dark" />
      </div>
    </main>
  );
}
