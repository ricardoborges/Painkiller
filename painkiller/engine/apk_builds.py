"""On-demand APK builds: debug from the backlog, release (signed) from the dashboard.

O build leva minutos (npm, Gradle, primeiro download do SDK no cache), então
roda em segundo plano: ``start`` grava o registro como BUILDING e devolve na
hora; a UI acompanha por polling. Os jobs vivem só neste processo — um
registro BUILDING sem job (a API reiniciou) vira FAILED na primeira leitura.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from painkiller.core.apk import KEEP_BUILDS, apk_path, is_android_project, parse_commit, prune_builds
from painkiller.core.backend import API_URL_ENV, backend_build_env, has_backend
from painkiller.core.domain.models import (
    ApkBuild,
    ApkBuildStatus,
    ApkVariant,
    DeploymentComponent,
    DeploymentStatus,
    EnvironmentType,
    Project,
    SecretScope,
)
from painkiller.core.i18n import project_language, tr, use_locale
from painkiller.core.ports.deployment import DeploymentPort
from painkiller.core.ports.issue_tracker import IssueTrackerPort
from painkiller.core.ports.sandbox import SandboxPort
from painkiller.core.secrets import redact, secret_values

logger = logging.getLogger(__name__)

#: Cauda do log guardada no registro; a saída do Gradle passa fácil de 1 MB.
LOG_TAIL_CHARS = 20_000


class ApkBuildBusyError(Exception):
    """A build of this project is already running."""


class NotAndroidProjectError(Exception):
    """The repository has no Gradle or Capacitor build."""


class ReleaseBackendError(Exception):
    """A release of an app with a backend needs that backend live in production, over https."""


class ApkBuildService:
    def __init__(
        self,
        tracker: IssueTrackerPort,
        sandbox: SandboxPort,
        timeout_seconds: Optional[int] = None,
        deployment: Optional[DeploymentPort] = None,
    ):
        self.tracker = tracker
        self.sandbox = sandbox
        # Endereço do backend que o app recebe no build (VITE_API_URL).
        self.deployment = deployment
        self.timeout_seconds = timeout_seconds or int(os.environ.get("PAINKILLER_APK_TIMEOUT", "2400"))
        self._jobs: dict[str, asyncio.Task] = {}

    async def start(self, project: Project, variant: ApkVariant) -> ApkBuild:
        # Um por projeto: dois Gradle no mesmo cache brigam pelo lock e pela RAM.
        for build_id, job in self._jobs.items():
            if not job.done():
                build = await self.tracker.get_apk_build(build_id)
                if build and build.project_id == project.id:
                    raise ApkBuildBusyError("Já há um APK sendo gerado para este projeto.")
        if not is_android_project(project.repo_path):
            raise NotAndroidProjectError("O repositório não tem um build Android (Gradle ou Capacitor).")
        env = await self._build_env(project, variant)

        build = await self.tracker.save_apk_build(ApkBuild(
            id=f"apk-{uuid.uuid4().hex[:10]}",
            project_id=project.id,
            variant=variant,
            branch=project.default_branch or "main",
        ))
        job = asyncio.create_task(self._run(project, build, env))
        self._jobs[build.id] = job
        job.add_done_callback(lambda _: self._jobs.pop(build.id, None))
        return build

    async def _build_env(self, project: Project, variant: ApkVariant) -> dict[str, str]:
        """The app's VITE_* secrets plus the backend address: test for debug, production for release.

        Um release vai para a loja e não tem como ser corrigido no aparelho: ele
        só sai com um backend de produção no ar e em https (a WebView roda em
        https://localhost e bloqueia http; o debug libera, o release não).
        """
        secrets = await secret_values(self.tracker, project.id, SecretScope.APP)
        if variant != ApkVariant.RELEASE:
            return {**secrets, **backend_build_env(project, self.deployment, EnvironmentType.TEST)}
        if not has_backend(project.repo_path):
            return secrets
        latest = await self.tracker.get_latest_deployment(
            project.id, EnvironmentType.PRODUCTION, DeploymentComponent.BACKEND
        )
        if latest is None or latest.status != DeploymentStatus.HEALTHY or not latest.url:
            raise ReleaseBackendError(
                "Publique o backend em produção antes de gerar o APK de produção: o app "
                "precisa de um backend no ar para funcionar."
            )
        if not latest.url.lower().startswith("https://"):
            raise ReleaseBackendError(
                "O backend de produção está em http: o APK de produção só fala com https. "
                "Configure o domínio do Coolify com https:// (Admin → Configurações) e "
                "publique o backend de novo."
            )
        return {**secrets, API_URL_ENV: latest.url}

    async def _run(self, project: Project, build: ApkBuild, env: Optional[dict[str, str]] = None) -> None:
        # Fora de qualquer requisição: o erro gravado sai no idioma do projeto.
        with use_locale(project_language(project)):
            try:
                code, logs = await self.sandbox.build_apk(
                    project_id=project.id,
                    repo_path=project.repo_path,
                    build_id=build.id,
                    variant=build.variant.value,
                    branch=build.branch,
                    app_name=project.name,
                    harness=project.harness,
                    timeout_seconds=self.timeout_seconds,
                    extra_env=env or None,
                )
            except Exception as e:  # noqa: BLE001 — o registro não pode ficar BUILDING
                logger.exception("APK build %s crashed", build.id)
                code, logs = 1, str(e)

            path = apk_path(project.repo_path, build.id)
            build.commit_sha = parse_commit(logs)
            secrets = [v for k, v in (env or {}).items() if k != API_URL_ENV]
            # Antes do corte: um valor partido ao meio pela cauda escaparia.
            build.logs = (redact(logs, secrets) or "")[-LOG_TAIL_CHARS:]
            build.finished_at = datetime.now(timezone.utc)
            if code == 0 and os.path.isfile(path):
                build.status = ApkBuildStatus.SUCCESS
                build.size_bytes = os.path.getsize(path)
            else:
                build.status = ApkBuildStatus.FAILED
                build.error = (
                    tr("O build do APK excedeu o tempo limite.")
                    if code == 137
                    else tr("O build do APK falhou (código {code}).", code=code)
                )
            try:
                await self.tracker.save_apk_build(build)
            except Exception:  # noqa: BLE001
                logger.exception("APK build %s could not be saved", build.id)
            await self._prune(project)

    async def _prune(self, project: Project) -> None:
        """Keep the newest builds on disk, and always the latest good release."""
        builds = await self.tracker.list_apk_builds(project.id, limit=500)
        keep = {b.id for b in builds[:KEEP_BUILDS]}
        keep |= {b.id for b in builds if b.status == ApkBuildStatus.BUILDING}
        release = next(
            (b for b in builds if b.variant == ApkVariant.RELEASE and b.status == ApkBuildStatus.SUCCESS),
            None,
        )
        if release:
            keep.add(release.id)
        await asyncio.get_running_loop().run_in_executor(None, prune_builds, project.repo_path, keep)

    async def _settle(self, project: Project, build: ApkBuild) -> ApkBuild:
        """Mark an orphaned BUILDING record as failed and fill ``available``."""
        if build.status == ApkBuildStatus.BUILDING and build.id not in self._jobs:
            build.status = ApkBuildStatus.FAILED
            with use_locale(project_language(project)):
                build.error = tr("Build interrompido: a API foi reiniciada.")
            build.finished_at = datetime.now(timezone.utc)
            build = await self.tracker.save_apk_build(build)
        build.available = build.status == ApkBuildStatus.SUCCESS and os.path.isfile(
            apk_path(project.repo_path, build.id)
        )
        return build

    async def list_builds(self, project: Project, limit: int = 20) -> list[ApkBuild]:
        builds = await self.tracker.list_apk_builds(project.id, limit=limit)
        return [await self._settle(project, b) for b in builds]

    async def get_build(self, project: Project, build_id: str) -> Optional[ApkBuild]:
        build = await self.tracker.get_apk_build(build_id)
        if build is None or build.project_id != project.id:
            return None
        return await self._settle(project, build)

    async def drain(self) -> None:
        """Wait for running builds (tests)."""
        while self._jobs:
            await asyncio.gather(*list(self._jobs.values()), return_exceptions=True)
