// SPA puro: o FastAPI serve os assets e devolve index.html para qualquer
// rota fora de /api. Sem SSR, sem prerender.
export const ssr = false;
export const prerender = false;
export const trailingSlash = 'never';
