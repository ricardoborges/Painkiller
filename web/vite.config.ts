import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    proxy: {
      // `npm run dev` fala com o uvicorn em :8000
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      // A prévia do app (iframe do backlog) vem do uvicorn, fora de /api.
      '/preview': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      // O APK do QR code, baixado pelo celular com o link assinado.
      '/apk': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
});
