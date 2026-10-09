/** Parent and child companies. */

import { apiRequest } from '@/lib/api/client';

import type { CompanyGroup, GroupSuggestionList, SetParentCompanyRequest } from '../types';

export function getCompanyGroup(companyId: string): Promise<CompanyGroup> {
  return apiRequest<CompanyGroup>(`/onboarding/exporters/${companyId}/group`);
}

export function setParentCompany(companyId: string, body: SetParentCompanyRequest): Promise<CompanyGroup> {
  return apiRequest<CompanyGroup>(`/onboarding/exporters/${companyId}/parent`, { method: 'PUT', body });
}

export function listGroupSuggestions(companyId: string): Promise<GroupSuggestionList> {
  return apiRequest<GroupSuggestionList>(`/onboarding/exporters/${companyId}/group/suggestions`);
}
