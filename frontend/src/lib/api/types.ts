import type { components } from './schema';

// Thin aliases onto the generated OpenAPI schema — never hand-duplicated
// shapes. If the backend renames or reshapes one of these, `npm run
// generate:api` regenerates `schema.ts` and every reference here becomes a
// compile error at its actual use site, not a silent runtime mismatch.
export type UserRole = components['schemas']['UserRole'];
export type User = components['schemas']['UserResponse'];
export type TokenResponse = components['schemas']['TokenResponse'];
export type LoginRequest = components['schemas']['LoginRequest'];
export type RefreshRequest = components['schemas']['RefreshRequest'];
