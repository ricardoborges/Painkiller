import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    // SPA: FastAPI serves the built assets and falls back to index.html
    // for any non-/api route. See painkiller/api/server.py.
    adapter: adapter({
      pages: '../painkiller/api/static',
      assets: '../painkiller/api/static',
      fallback: 'index.html',
      precompress: false,
      strict: false
    })
  }
};

export default config;
