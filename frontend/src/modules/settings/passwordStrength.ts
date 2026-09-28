/**
 * Password strength, as five independent checks.
 *
 * Two of these five — an uppercase letter and a digit — are what the *backend*
 * actually enforces (`validate_password_strength` in
 * `app/api/rest/auth/schemas.py`), along with a minimum length of 8. The other
 * two (lowercase, symbol) are advice, not policy. `meetsPolicy` below is
 * therefore the honest gate for enabling a submit button: a meter that refused
 * a password the server would happily accept would be inventing a rule, and
 * one that accepted a password the server rejects would just produce a 422.
 */

export interface PasswordStrength {
  /** 0–5, one point per satisfied check. */
  score: number;
  label: 'Too short' | 'Weak' | 'Fair' | 'Good' | 'Strong';
  /** True when the backend's own rule is satisfied. */
  meetsPolicy: boolean;
  /** Human-readable list of what the backend still requires. */
  missing: string[];
}

const MIN_LENGTH = 8;

export function assessPassword(password: string): PasswordStrength {
  const hasLength = password.length >= MIN_LENGTH;
  const hasUpper = /[A-Z]/.test(password);
  const hasLower = /[a-z]/.test(password);
  const hasDigit = /\d/.test(password);
  const hasSymbol = /[^A-Za-z0-9]/.test(password);

  const score = [hasLength, hasUpper, hasLower, hasDigit, hasSymbol].filter(
    Boolean,
  ).length;

  const missing: string[] = [];
  if (!hasLength) missing.push(`at least ${MIN_LENGTH} characters`);
  if (!hasUpper) missing.push('an uppercase letter');
  if (!hasDigit) missing.push('a digit');

  const meetsPolicy = missing.length === 0;

  let label: PasswordStrength['label'];
  if (!hasLength) label = 'Too short';
  else if (score <= 2) label = 'Weak';
  else if (score === 3) label = 'Fair';
  else if (score === 4) label = 'Good';
  else label = 'Strong';

  return { score, label, meetsPolicy, missing };
}
