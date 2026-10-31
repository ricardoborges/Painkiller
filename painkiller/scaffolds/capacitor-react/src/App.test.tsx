import { render, screen } from '@testing-library/react'
import App from './App'

describe('App', () => {
  it('opens on the home page', async () => {
    render(<App />)

    expect(await screen.findByText('Olá, Capacitor!')).toBeInTheDocument()
  })
})
