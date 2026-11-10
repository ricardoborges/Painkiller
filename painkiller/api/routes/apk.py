"""APK builds: trigger, follow and download the project's Android package.

Além do download com sessão, cada build pronto pode gerar um link assinado
(``/apk/{id}/{build}/{key}/{arquivo}.apk``) para o QR code: quem baixa é o
navegador do celular, que não tem o token do Painkiller.
"""

import io
import zipfile
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from painkiller.api.security import issue_apk_key, require_project, verify_apk_key, visible_project
from painkiller.core.apk import KEY_ALIAS, KEYSTORE_FILE, KEYSTORE_PASSWORD_FILE, aab_path, apk_path
from painkiller.core.domain.models import ApkBuild, ApkBuildStatus, ApkVariant
from painkiller.engine.apk_builds import ApkBuildBusyError, NotAndroidProjectError, ReleaseBackendError

router = APIRouter(
    prefix="/api/projects/{project_id}/apk-builds",
    tags=["apk"],
    dependencies=[Depends(require_project)],
)


public_router = APIRouter(prefix="/apk", tags=["apk"], include_in_schema=False)

APK_MEDIA_TYPE = "application/vnd.android.package-archive"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class StartApkBuildRequest(BaseModel):
    variant: ApkVariant = ApkVariant.DEBUG


@router.post("", response_model=ApkBuild)
async def start_apk_build(project_id: str, body: StartApkBuildRequest, request: Request):
    """Start building the APK of the default branch; returns at once, poll the build."""
    project = await visible_project(request, project_id)
    try:
        return await request.app.state.apk_builds.start(project, body.variant)
    except (ApkBuildBusyError, ReleaseBackendError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    except NotAndroidProjectError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=list[ApkBuild])
async def list_apk_builds(project_id: str, request: Request, limit: int = 20):
    project = await visible_project(request, project_id)
    return await request.app.state.apk_builds.list_builds(project, limit=min(max(limit, 1), 100))


KEY_README = """Chave de assinatura do app "{name}" / Signing key of the app "{name}"

release.jks   keystore (PKCS12)
password.txt  senha do keystore e da chave / keystore and key password
alias         {alias}

Guarde este arquivo em lugar seguro e nunca o publique. Sem esta chave não é
possível publicar atualizações do app; com ela, qualquer pessoa pode publicar
em nome dele.

Keep this file somewhere safe and never publish it. Without this key the app
cannot be updated; with it, anyone can publish on its behalf.
"""


# Antes de /{build_id}: senão "signing-key" seria lido como o id de um build.
@router.get("/signing-key")
async def export_signing_key(project_id: str, request: Request):
    """Backup of the project's release keystore and password, as a zip.

    A chave vive num volume do Docker desta máquina: sem uma cópia, perder a
    máquina é perder a possibilidade de atualizar o app na loja.
    """
    project = await visible_project(request, project_id)
    files = await request.app.state.sandbox.export_signing_key(project.id)
    if not files:
        raise HTTPException(
            status_code=404,
            detail="Este projeto ainda não tem chave de assinatura: ela é criada no primeiro APK de produção.",
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(KEYSTORE_FILE, files[KEYSTORE_FILE])
        archive.writestr("password.txt", files[KEYSTORE_PASSWORD_FILE])
        archive.writestr("LEIA-ME.txt", KEY_README.format(name=project.name, alias=KEY_ALIAS))
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{_slug(project)}-signing-key.zip"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{build_id}", response_model=ApkBuild)
async def get_apk_build(project_id: str, build_id: str, request: Request):
    project = await visible_project(request, project_id)
    build = await request.app.state.apk_builds.get_build(project, build_id)
    if build is None:
        raise HTTPException(status_code=404, detail="Build do APK não encontrado")
    return build


def _slug(project) -> str:
    # ASCII: o nome vai num cabeçalho Content-Disposition.
    slug = "".join(c if c.isascii() and (c.isalnum() or c in "-_") else "-" for c in project.name)
    return slug.strip("-") or project.id


def _filename(project, build, extension: str = "apk") -> str:
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in project.name).strip("-") or project.id
    stamp = build.commit_sha or build.created_at.strftime("%Y%m%d-%H%M")
    return f"{slug}-{build.variant.value}-{stamp}.{extension}"


async def _ready_build(request: Request, project, build_id: str):
    build = await request.app.state.apk_builds.get_build(project, build_id)
    if build is None or build.status != ApkBuildStatus.SUCCESS:
        raise HTTPException(status_code=404, detail="Build do APK não encontrado")
    if not build.available:
        raise HTTPException(status_code=410, detail="O arquivo deste APK já foi removido; gere outro.")
    return build


@router.get("/{build_id}/download")
async def download_apk(project_id: str, build_id: str, request: Request):
    project = await visible_project(request, project_id)
    build = await _ready_build(request, project, build_id)
    return FileResponse(
        apk_path(project.repo_path, build.id),
        media_type=APK_MEDIA_TYPE,
        filename=_filename(project, build),
    )


@router.get("/{build_id}/download-aab")
async def download_aab(project_id: str, build_id: str, request: Request):
    """The release's signed App Bundle, the format the Play Store takes."""
    project = await visible_project(request, project_id)
    build = await _ready_build(request, project, build_id)
    if not build.aab_available:
        raise HTTPException(status_code=404, detail="Este build não tem pacote AAB; gere o APK de produção de novo.")
    return FileResponse(
        aab_path(project.repo_path, build.id),
        media_type="application/octet-stream",
        filename=_filename(project, build, "aab"),
    )


@router.get("/{build_id}/link")
async def apk_link(project_id: str, build_id: str, request: Request):
    """Signed, short-lived download URL for the QR code, on the platform's public URL."""
    project = await visible_project(request, project_id)
    build = await _ready_build(request, project, build_id)
    key, expires = issue_apk_key(project.id, build.id)
    base = request.app.state.platform.public_url()
    url = f"{base}/apk/{project.id}/{build.id}/{key}/{quote(_filename(project, build))}"
    host = (urlsplit(base).hostname or "").lower()
    return {
        "url": url,
        "expires_at": datetime.fromtimestamp(expires, tz=timezone.utc).isoformat(),
        # Um endereço local não abre no celular: a UI avisa em vez de mostrar um QR inútil.
        "local": host in LOCAL_HOSTS or host.startswith("127."),
    }


@public_router.get("/{project_id}/{build_id}/{key}/{filename}")
async def public_download_apk(project_id: str, build_id: str, key: str, filename: str, request: Request):
    if not verify_apk_key(project_id, build_id, key):
        raise HTTPException(status_code=404, detail="Not Found")
    project = await request.app.state.tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Not Found")
    build = await _ready_build(request, project, build_id)
    return FileResponse(
        apk_path(project.repo_path, build.id),
        media_type=APK_MEDIA_TYPE,
        filename=_filename(project, build),
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
