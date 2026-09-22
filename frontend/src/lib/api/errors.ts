// Two distinct error shapes come back from the backend and both need to
// surface a readable message, not just "Request failed":
//   1. AnerBaseException's handler (app/platform/middleware/handlers.py) —
//      { error_code, detail: string, human_readable_message, ... }
//   2. FastAPI's own default RequestValidationError handler (nothing
//      registers a custom one for it) — { detail: [{ loc, msg, type }, ...] }
//      — this is exactly the shape a Pydantic `extra="forbid"` 422 returns,
//      which EXP-F1's own acceptance criterion needs surfaced correctly.
interface FieldError {
  loc: (string | number)[];
  msg: string;
  type: string;
}

interface AnerErrorBody {
  error_code?: string;
  detail?: string | FieldError[];
  human_readable_message?: string;
  correlation_id?: string | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string | null;
  readonly correlationId: string | null;

  constructor(
    status: number,
    message: string,
    errorCode: string | null = null,
    correlationId: string | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.errorCode = errorCode;
    this.correlationId = correlationId;
  }
}

function formatFieldErrors(errors: FieldError[]): string {
  return errors
    .map((e) => `${e.loc.filter((p) => p !== 'body').join('.')}: ${e.msg}`)
    .join('; ');
}

export async function parseErrorResponse(
  response: Response,
): Promise<ApiError> {
  let body: AnerErrorBody | null = null;
  try {
    body = (await response.json()) as AnerErrorBody;
  } catch {
    // Non-JSON error body (e.g. a proxy/network-level failure) — fall through.
  }

  if (body?.detail == null) {
    return new ApiError(
      response.status,
      response.statusText || 'Request failed',
    );
  }

  const message = Array.isArray(body.detail)
    ? formatFieldErrors(body.detail)
    : (body.human_readable_message ?? body.detail);

  return new ApiError(
    response.status,
    message,
    body.error_code ?? null,
    body.correlation_id ?? null,
  );
}
