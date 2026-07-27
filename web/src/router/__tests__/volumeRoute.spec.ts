import { describe, expect, it } from 'vitest'
import router from '../index'

describe('volume demo route', () => {
  it('resolves by direct URL but is not a home navigation entry', () => {
    const resolved = router.resolve('/volume-demo')
    expect(resolved.name).toBe('volume-demo')
    expect(resolved.matched).toHaveLength(1)
  })
})
