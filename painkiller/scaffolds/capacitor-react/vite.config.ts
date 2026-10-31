/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  // Os arquivos vão dentro do APK, não pela rede: o tamanho do bundle não pesa no carregamento.
  build: { chunkSizeWarningLimit: 2500 },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    css: false,
    // O Ionic e o ionicons publicam ESM com imports de CSS: o Vitest precisa transformá-los.
    server: { deps: { inline: [/@ionic\//, /ionicons/] } },
  },
})
