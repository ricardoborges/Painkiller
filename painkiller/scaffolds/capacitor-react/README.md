# My App

App Android em React + Ionic, empacotado com Capacitor.

- `src/` — o app (React 19 + Ionic React 9, rotas com react-router 6).
- `android/` — projeto nativo gerado pelo Capacitor; só mude quando precisar de algo nativo.

```bash
npm install
npm run dev            # navegador, http://localhost:5173
npm test               # Vitest + Testing Library
npm run build          # gera dist/
npm run android:build  # build web + cap sync + APK de debug (android/app/build/outputs/apk)
```
