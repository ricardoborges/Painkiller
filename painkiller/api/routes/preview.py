"""The app preview: the latest completed web build of a project, for the phone frame in the backlog.

Duas rotas: ``GET /api/projects/{id}/preview`` (com sessão) diz se há prévia e
devolve a URL dela; ``/preview/{id}/{key}/...`` serve os arquivos sem
cabeçalhos, porque quem pede é um iframe, autorizado pela chave assinada da URL.

O app é código do agente: ele roda isolado. Toda resposta leva
``Content-Security-Policy: sandbox`` sem ``allow-same-origin``, então o app
ganha uma origem opaca e não alcança o localStorage (e o token) do Painkiller,
nem aberto direto numa aba. Por isso os módulos do Vite, pedidos com CORS a
partir dessa origem opaca, precisam de ``Access-Control-Allow-Origin: *``.
"""

import html
import mimetypes
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response

from painkiller.api.security import issue_preview_key, require_project, verify_preview_key
from painkiller.core.preview import preview_dir, read_preview
from painkiller.core.test_plan import is_capacitor_project

router = APIRouter(prefix="/api/projects", tags=["preview"])
public_router = APIRouter(prefix="/preview", tags=["preview"], include_in_schema=False)

PREVIEW_HEADERS = {
    "Content-Security-Policy": "sandbox allow-scripts allow-forms allow-modals allow-popups",
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
}

# Roda antes do app. O roteador do app (BrowserRouter) lê o caminho da página:
# sob /preview/{id}/{key}/ nenhuma rota casaria, então a URL vira "/" — o
# <base> mantém os arquivos relativos apontando para cá. Na origem opaca o
# localStorage lança exceção; um substituto em memória evita que o app quebre.
BOOT_SCRIPT = """
(function () {
  try { history.replaceState(null, '', '/'); } catch (e) {}
  function memory() {
    var data = {};
    return {
      get length() { return Object.keys(data).length; },
      key: function (i) { var k = Object.keys(data)[i]; return k === undefined ? null : k; },
      getItem: function (k) { return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null; },
      setItem: function (k, v) { data[k] = String(v); },
      removeItem: function (k) { delete data[k]; },
      clear: function () { data = {}; }
    };
  }
  ['localStorage', 'sessionStorage'].forEach(function (name) {
    try { window[name].getItem('_'); }
    catch (e) {
      try { Object.defineProperty(window, name, { value: memory(), configurable: true }); } catch (e2) {}
    }
  });
})();
"""


@router.get("/{project_id}/preview", dependencies=[Depends(require_project)])
async def get_preview(project_id: str, request: Request):
    project = await request.app.state.tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    meta = read_preview(project.repo_path)
    data = {
        # Só um app web (Capacitor) tem o que mostrar; o Kotlin nativo, não.
        "supported": is_capacitor_project(project.repo_path),
        "available": meta is not None,
        "url": None,
        "task_id": None,
        "task_title": None,
        "built_at": None,
    }
    if meta is not None:
        built_at = meta.get("built_at") or ""
        data.update(
            url=f"/preview/{project_id}/{issue_preview_key(project_id)}/?v={quote(built_at)}",
            task_id=meta.get("task_id"),
            task_title=meta.get("task_title"),
            built_at=built_at or None,
        )
    return data


def _index_html(index: Path, base: str) -> str:
    source = index.read_text(encoding="utf-8", errors="replace")
    head = f'<base href="{html.escape(base)}"><script>{BOOT_SCRIPT}</script>'
    marker = source.lower().find("<head>")
    if marker == -1:
        return head + source
    cut = marker + len("<head>")
    return source[:cut] + head + source[cut:]


@public_router.get("/{project_id}/{key}/{resource:path}")
async def serve_preview(project_id: str, key: str, resource: str, request: Request):
    if not verify_preview_key(project_id, key):
        raise HTTPException(status_code=404, detail="Not Found")
    project = await request.app.state.tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Not Found")
    root = Path(preview_dir(project.repo_path)).resolve()
    index = root / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Not Found")

    if resource and resource != "index.html":
        candidate = (root / resource).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise HTTPException(status_code=404, detail="Not Found")
        media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        return FileResponse(candidate, media_type=media_type, headers=PREVIEW_HEADERS)

    base = f"{request.scope.get('root_path', '')}/preview/{project_id}/{key}/"
    return Response(_index_html(index, base), media_type="text/html", headers=PREVIEW_HEADERS)
