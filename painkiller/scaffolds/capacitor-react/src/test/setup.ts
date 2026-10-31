import '@testing-library/jest-dom/vitest'
import { setupIonicReact } from '@ionic/react'

setupIonicReact({ mode: 'md' })

// O jsdom não implementa matchMedia, que o Ionic consulta.
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: () => {},
  removeListener: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
  dispatchEvent: () => false,
})) as typeof window.matchMedia
