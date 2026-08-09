import { beforeEach, describe, expect, it } from 'vitest'
import {
  PRESENTATION_CHAPTERS,
  usePresentationStore,
  resetPresentationStore,
} from '../presentation'

describe('presentation store', () => {
  beforeEach(() => {
    resetPresentationStore()
  })

  it('defines the six stable chapter ids in order', () => {
    expect(PRESENTATION_CHAPTERS.map((c) => c.id)).toEqual([
      'overview',
      'resistivity',
      'microseismic',
      'gas',
      'custom-data',
      'innovation-boundaries',
    ])
  })

  it('next/previous respect chapter bounds', () => {
    const store = usePresentationStore()
    store.enter()
    expect(store.currentId.value).toBe('overview')
    store.prev()
    expect(store.currentId.value).toBe('overview')
    store.next()
    expect(store.currentId.value).toBe('resistivity')
    for (let i = 0; i < 10; i++) store.next()
    expect(store.currentId.value).toBe('innovation-boundaries')
    store.next()
    expect(store.currentId.value).toBe('innovation-boundaries')
  })

  it('direct chapter selection and exit work', () => {
    const store = usePresentationStore()
    store.enter()
    store.goTo('gas')
    expect(store.currentId.value).toBe('gas')
    store.goTo('nonexistent')
    expect(store.currentId.value).toBe('gas')
    store.exit()
    expect(store.active.value).toBe(false)
  })
})
