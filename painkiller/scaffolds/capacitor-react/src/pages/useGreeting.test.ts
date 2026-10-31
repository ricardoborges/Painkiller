import { renderHook, waitFor } from '@testing-library/react'
import { useGreeting } from './useGreeting'

describe('useGreeting', () => {
  it('exposes the message loaded by the repository', async () => {
    const repository = { load: async () => 'Oi' }
    const { result } = renderHook(() => useGreeting(repository))

    expect(result.current).toEqual({ status: 'loading' })
    await waitFor(() => expect(result.current).toEqual({ status: 'ready', message: 'Oi' }))
  })

  it('reports an error when loading fails', async () => {
    const failing = { load: () => Promise.reject(new Error('offline')) }
    const { result } = renderHook(() => useGreeting(failing))

    await waitFor(() => expect(result.current).toEqual({ status: 'error' }))
  })
})
