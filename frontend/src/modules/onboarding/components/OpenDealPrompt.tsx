/**
 * Seam S2 — the "open a deal" prompt on the Conversation panel.
 *
 * **Owner: Developer 3A.** Mounted by `ConversationPanel.tsx` whenever the gauge
 * reads `READY_NOW`. Architecture §3.3: "`READY_NOW` … The screen offers to open a
 * deal; opening a deal also sets this."
 *
 * The form is Developer 3B's `OpenDealForm` — the same one the Deals tab uses —
 * reached through the components barrel, never re-implemented here. Opening the
 * deal is what moves the gauge, on the server (seam S1): this component never
 * sets the conversation itself. On success it goes to the new deal's page, where
 * the buyer and the paperwork are added.
 */

import { Handshake, Plus } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Button } from '@/components';

import { paths } from '../paths';
import { OpenDealForm } from './OpenDealForm';

interface OpenDealPromptProps {
  /** The company this prompt is for. */
  customerId: string;
  /** DEVELOPER reads the CRM and writes nothing, so it gets no action. Passed in
   * rather than read from the session here: one source of that answer per screen. */
  isStaff: boolean;
}

export function OpenDealPrompt({ customerId, isStaff }: OpenDealPromptProps) {
  const navigate = useNavigate();
  const [opening, setOpening] = useState(false);

  if (opening) {
    return (
      <OpenDealForm
        customerId={customerId}
        onClose={() => setOpening(false)}
        onOpened={(deal) => navigate(paths.deal(deal.id))}
      />
    );
  }

  return (
    <div
      className="flex flex-wrap items-start gap-3 rounded-lg border border-brand-200 bg-brand-50 p-4"
      data-extension="open-deal-prompt"
    >
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-100 text-brand-700">
        <Handshake size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-brand-900">
          This company has something they want financed
        </p>
        <p className="mt-0.5 text-sm text-brand-900/80">
          {isStaff
            ? 'Open a deal to record what they want financed, then add the buyer and the paperwork.'
            : 'A staff member can open a deal for it.'}
        </p>
      </div>
      {isStaff && (
        <Button size="sm" variant="primary" onClick={() => setOpening(true)}>
          <Plus size={14} />
          Open a deal
        </Button>
      )}
    </div>
  );
}
