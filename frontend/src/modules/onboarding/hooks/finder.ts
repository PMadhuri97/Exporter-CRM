/**
 * Finding a company from the command bar (frontend-plan §7.5).
 *
 * By name for every reader. By a **full** PAN, GSTIN or IEC only for a role that
 * may see identifiers (`identifiers.reveal`): the API refuses an identifier search
 * from a masked role (decision 12), so for those roles an identifier-shaped query
 * sends nothing at all and the bar shows a hint towards the match flow instead
 * (Add company / Choose buyer). Reads only — the list is `GET /exporters`.
 */

import { useQuery } from '@tanstack/react-query';

import { useCan } from '@/platform/access';

import { searchExporterProfiles } from '../api';
import type { ExporterSearchParams } from '../types';

export type IdentifierKind = 'pan' | 'gstin' | 'iec';

const PAN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const GSTIN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$/;
const IEC = /^[0-9]{10}$/;

/** Which identifier `text` is shaped like, if any. */
export function identifierKind(text: string): IdentifierKind | null {
  const value = text.trim().toUpperCase();
  if (PAN.test(value)) return 'pan';
  if (GSTIN.test(value)) return 'gstin';
  if (IEC.test(value)) return 'iec';
  return null;
}

const LIMIT = 8;

export function useCompanyFinder(query: string) {
  const canReveal = useCan('identifiers.reveal');
  const text = query.trim();
  const kind = identifierKind(text);
  // A masked role never sends an identifier: the bar explains instead.
  const identifierHidden = kind !== null && !canReveal;
  const params: ExporterSearchParams =
    kind && canReveal ? { [kind]: text.toUpperCase(), limit: LIMIT } : { name: text, limit: LIMIT };
  const enabled = !identifierHidden && text.length >= 2;

  const result = useQuery({
    queryKey: ['exporterProfiles', 'finder', params],
    queryFn: () => searchExporterProfiles(params),
    enabled,
    staleTime: 30_000,
  });

  return {
    companies: enabled ? (result.data?.profiles ?? []) : [],
    searching: enabled && result.isFetching,
    failed: enabled && result.isError,
    searchedBy: enabled ? (kind && canReveal ? kind : 'name') : null,
    identifierHidden,
  } as const;
}
