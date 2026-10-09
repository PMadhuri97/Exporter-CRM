/** Structured sanctions screening: the lists, a company's screenings and the worklists. */

import { apiRequest } from '@/lib/api/client';

import type {
  AddSanctionsListRequest,
  CompanySanctions,
  PendingTrueMatchList,
  RecordSanctionsRunRequest,
  RescreenDueList,
  ReviseSanctionsListRequest,
  SanctionsDisposition,
  SanctionsList,
  SanctionsLists,
  SanctionsRun,
  SanctionsRunList,
} from '../types';

export function listSanctionsLists(): Promise<SanctionsLists> {
  return apiRequest<SanctionsLists>('/onboarding/settings/sanctions-lists');
}

export function addSanctionsList(body: AddSanctionsListRequest): Promise<SanctionsList> {
  return apiRequest<SanctionsList>('/onboarding/settings/sanctions-lists', { method: 'POST', body });
}

/** Writes the next version; a newer version date puts screened companies on Re-screen due. */
export function reviseSanctionsList(code: string, body: ReviseSanctionsListRequest): Promise<SanctionsList> {
  return apiRequest<SanctionsList>(`/onboarding/settings/sanctions-lists/${code}`, { method: 'PATCH', body });
}

export function getCompanySanctions(companyId: string): Promise<CompanySanctions> {
  return apiRequest<CompanySanctions>(`/onboarding/exporters/${companyId}/sanctions`);
}

export function listCompanySanctionsRuns(companyId: string): Promise<SanctionsRunList> {
  return apiRequest<SanctionsRunList>(`/onboarding/exporters/${companyId}/sanctions/runs`);
}

export function recordSanctionsRun(companyId: string, body: RecordSanctionsRunRequest): Promise<SanctionsRun> {
  return apiRequest<SanctionsRun>(`/onboarding/exporters/${companyId}/sanctions/runs`, { method: 'POST', body });
}

export function decideSanctionsHit(
  hitId: string,
  disposition: Exclude<SanctionsDisposition, 'TRUE_MATCH_PROPOSED'>,
  reason: string | null,
): Promise<SanctionsRun> {
  return apiRequest<SanctionsRun>(`/onboarding/sanctions/hits/${hitId}/decision`, {
    method: 'POST',
    body: { disposition, reason },
  });
}

export function confirmTrueMatch(hitId: string): Promise<SanctionsRun> {
  return apiRequest<SanctionsRun>(`/onboarding/sanctions/hits/${hitId}/confirm`, { method: 'POST' });
}

export function rejectTrueMatch(hitId: string, reason: string): Promise<SanctionsRun> {
  return apiRequest<SanctionsRun>(`/onboarding/sanctions/hits/${hitId}/reject`, {
    method: 'POST',
    body: { reason },
  });
}

export function listPendingTrueMatches(): Promise<PendingTrueMatchList> {
  return apiRequest<PendingTrueMatchList>('/onboarding/sanctions/true-matches');
}

export function listRescreenDue(): Promise<RescreenDueList> {
  return apiRequest<RescreenDueList>('/onboarding/sanctions/rescreen-due');
}
