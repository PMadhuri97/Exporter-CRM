import { describe, expect, it } from 'vitest';

import { parseErrorResponse } from './errors';

function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

describe('parseErrorResponse', () => {
  it('keeps a 422’s field messages by field, as well as joined', async () => {
    const error = await parseErrorResponse(
      response(422, {
        detail: [
          { loc: ['body', 'check_back_on'], msg: 'must not be in the past', type: 'value_error' },
          { loc: ['body', 'buyer', 'name'], msg: 'Field required', type: 'missing' },
        ],
      }),
    );
    expect(error.fieldErrors).toEqual({
      check_back_on: 'must not be in the past',
      'buyer.name': 'Field required',
    });
    expect(error.message).toBe('check_back_on: must not be in the past; buyer.name: Field required');
  });

  it('has no field errors for a refusal in words', async () => {
    const error = await parseErrorResponse(
      response(409, { error_code: 'X', detail: 'Moved', human_readable_message: 'Someone moved it.' }),
    );
    expect(error.fieldErrors).toBeNull();
    expect(error.message).toBe('Someone moved it.');
  });
});
