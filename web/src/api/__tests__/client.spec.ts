import { describe, expect, it, vi } from 'vitest'
import { purgeCase } from '../client'

describe('purgeCase', () => {
  it('sends the exact-name confirmation as a JSON request body', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ operation_id: 'op-1', state: 'cleaned' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await purgeCase('case-1', '电阻率1')

    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/cases/case-1/purge',
      expect.objectContaining({
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({ confirmation_name: '电阻率1' }),
      }),
    )
    fetchSpy.mockRestore()
  })
})
