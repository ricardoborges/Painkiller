import { useEffect, useState } from 'react'
import { greetingRepository, type GreetingRepository } from '../data/greetingRepository'

export type GreetingState =
  | { status: 'loading' }
  | { status: 'ready'; message: string }
  | { status: 'error' }

/** Estado da tela inicial: a página só renderiza, a lógica fica aqui. */
export function useGreeting(repository: GreetingRepository = greetingRepository): GreetingState {
  const [state, setState] = useState<GreetingState>({ status: 'loading' })

  useEffect(() => {
    let active = true
    repository
      .load()
      .then((message) => active && setState({ status: 'ready', message }))
      .catch(() => active && setState({ status: 'error' }))
    return () => {
      active = false
    }
  }, [repository])

  return state
}
