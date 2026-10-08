/** Words for how two companies in a group are related. */

import type { SetParentCompanyRequest } from '../types';

export const GROUP_RELATIONSHIP_LABEL: Record<NonNullable<SetParentCompanyRequest['relationship']>, string> = {
  SUBSIDIARY: 'Subsidiary',
  BRANCH_OFFICE: 'Branch office',
  GROUP_COMPANY: 'Group company',
  JOINT_VENTURE: 'Joint venture',
};
