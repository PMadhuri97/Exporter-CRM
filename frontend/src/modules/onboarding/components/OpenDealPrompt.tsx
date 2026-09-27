/**
 * Seam S2 — the "open a deal" prompt on the Conversation panel.
 *
 * **Owner: Developer 3A.** Mounted by `ConversationPanel.tsx` whenever the gauge
 * reads `READY_NOW`. Architecture §3.3: "`READY_NOW` … The screen offers to open a
 * deal; opening a deal also sets this."
 *
 * **This file exists so that `ConversationPanel.tsx` does not have to change
 * again.** The panel is written once, in Phase 1, and closed (phase agreement
 * §6.3). Everything about the prompt that is still open lives here, in one small
 * file, so whoever lands the button next — Developer 3A once 3B's deal route
 * merges, or Phase 2 — changes this file and nothing else.
 *
 * **Today it renders the note and no button.** Developer 3B's deal route does not
 * exist yet (migration 0018, L3-05). A button calling a route that is not there is
 * a broken screen, and this project's stated principle is never to show navigation
 * to something that renders nothing — see `layout/Sidebar.tsx`'s docstring, where
 * unbuilt screens are a disabled row with a "Soon" badge rather than a dead link.
 * So the prompt says what is true: this company is ready, and opening deals is
 * coming.
 *
 * **What the button will look like when it lands.** Not a guess to be designed
 * later: 3B publishes the create-a-deal request function and hook in
 * `api/deals.ts` / `hooks/deals.ts`, and this file imports them **through the
 * barrel** (`../api`, `../hooks`) — never from 3B's file directly — and defines no
 * deal request function and no deal type of its own (prompt §4.2). Opening the deal
 * is also what moves the gauge, on the server, through
 * `ConversationService.mark_ready_now_for_opened_deal` (seam S1): this component
 * must never set the conversation itself, and the company is already `READY_NOW`
 * by the time it is rendered anyway.
 */

import { Handshake } from 'lucide-react';

interface OpenDealPromptProps {
  /** The company this prompt is for. Unused while there is no button — kept in the
   * signature because the create-a-deal call will need it, and because a prop
   * appearing later would be a change to `ConversationPanel.tsx`, which is
   * closed. */
  customerId: string;
  /** DEVELOPER reads the CRM and writes nothing, so it gets no action. Passed in
   * rather than read from the session here for the same reason the panel takes it:
   * one source of that answer per screen. */
  isStaff: boolean;
}

export function OpenDealPrompt({ customerId, isStaff }: OpenDealPromptProps) {
  return (
    <div
      className="flex items-start gap-3 rounded-lg border border-brand-200 bg-brand-50 p-4"
      data-extension="open-deal-prompt"
      data-customer-id={customerId}
    >
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-100 text-brand-900">
        <Handshake size={16} />
      </div>
      <div className="min-w-0">
        <p className="text-sm font-medium text-brand-900">
          This exporter has something they want financed
        </p>
        <p className="mt-0.5 text-sm text-brand-900/80">
          {isStaff
            ? 'Opening a deal is not built yet. When it is, you will be able to start one from here.'
            : 'Opening a deal is not built yet.'}
        </p>
      </div>
    </div>
  );
}
