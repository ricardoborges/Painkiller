"""Deployment Service coordinating environment provisioning with Coolify."""

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional
from painkiller.core.backend import backend_build_env, has_backend
from painkiller.core.domain.models import (
    DeploymentComponent,
    Project,
    ProjectSecret,
    SecretScope,
    Task,
    TaskStatus,
    DeploymentRecord,
    DeploymentStatus,
    EnvironmentType,
    SessionStatus,
)
from painkiller.core.i18n import project_language, tr
from painkiller.core.ports.deployment import DeploymentPort
from painkiller.core.ports.git import GitPort
from painkiller.core.ports.issue_tracker import IssueTrackerPort
from painkiller.core.secrets import redact, secret_values

logger = logging.getLogger(__name__)


class BranchUnavailableError(Exception):
    """The task's branch was deleted when its session was finalized."""


class BranchPushError(Exception):
    """The branch to deploy could not be sent to Gitea, so Coolify cannot clone it."""


class BackendMissingError(Exception):
    """A backend deploy was asked for a project without ``backend/``."""


class DeploymentNotFailedError(Exception):
    """Only a failed deploy can become a fix task."""


# O fim do log basta: é onde o Coolify e o BuildKit dizem o que quebrou.
FIX_LOG_TAIL_CHARS = 12_000


# O Coolify marca o deploy como encerrado um instante antes de gravar as
# últimas linhas (o erro do build, o "Removing the new version"). Por este
# tempo depois da última mudança, o log de um deploy encerrado ainda é relido.
LOG_SETTLE_SECONDS = 60


def _settling(record: DeploymentRecord) -> bool:
    if record.status not in (DeploymentStatus.FAILED, DeploymentStatus.HEALTHY):
        return False
    changed = record.updated_at
    if changed.tzinfo is None:
        changed = changed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - changed).total_seconds() < LOG_SETTLE_SECONDS


def _fix_marker(deployment_id: str) -> str:
    """Linha que liga a tarefa ao deploy: um segundo clique reusa a mesma tarefa."""
    return f"deploy-fix: {deployment_id}"


class DeploymentService:
    """Orchestrates testing and production deployment requests."""

    def __init__(
        self,
        tracker: IssueTrackerPort,
        deployment: DeploymentPort,
        git: Optional[GitPort] = None,
        prepare: Optional[Callable[[], Awaitable[Any]]] = None,
    ):
        self.tracker = tracker
        self.deployment = deployment
        self.git = git
        # Garante a infraestrutura do deploy (o Gitea na rede do Coolify) antes
        # de cada disparo; falhas são só registradas pelo próprio hook.
        self.prepare = prepare

    async def trigger_deploy(
        self,
        project_id: str,
        environment: EnvironmentType,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        component: DeploymentComponent = DeploymentComponent.APP,
    ) -> DeploymentRecord:
        """Trigger deployment of test or production environment of the app or its backend."""
        project = await self.tracker.get_project(project_id)
        if not project:
            raise ValueError(f"Projeto {project_id} não encontrado")
        if component == DeploymentComponent.BACKEND and not has_backend(project.repo_path):
            raise BackendMissingError("O projeto não tem backend.")

        # Resolução da branch:
        # Para TESTE:
        # A branch da tarefa indicada ou, sem ela, a da última tarefa concluída.
        # Só a conclusão faz push da feature/ para o Gitea: uma tarefa em
        # execução (ou órfã após um restart) tem a branch só no disco, e o
        # Coolify falha com "Remote branch ... not found". Por isso uma tarefa
        # indicada que não esteja concluída cai na escolha automática. Sem
        # tarefa concluída, a branch padrão.
        # Para PRODUÇÃO:
        # Sempre usa a default_branch (main).
        # Uma sessão finalizada teve as branches apagadas: só a sessão aberta
        # tem o que testar por tarefa.
        branch = project.default_branch or "main"
        if environment == EnvironmentType.TEST:
            task = await self.tracker.get_task(task_id) if task_id else None
            if task and await self._session_finalized(task.session_id):
                raise BranchUnavailableError(
                    "A sessão desta tarefa foi finalizada e as branches dela foram apagadas "
                    "após o merge. Só as tarefas da sessão atual podem ser testadas."
                )
            if task and task.status == TaskStatus.COMPLETED:
                branch = task.assigned_branch or f"feature/{task.id}"
            else:
                task_id = None
                tasks = await self.tracker.list_tasks(project_id, session_id=session_id)
                completed = [
                    t for t in tasks
                    if t.status == TaskStatus.COMPLETED and not await self._session_finalized(t.session_id)
                ]
                if completed:
                    chosen_task = completed[-1]
                    branch = chosen_task.assigned_branch or f"feature/{chosen_task.id}"
                    task_id = chosen_task.id

        await self._publish_branch(project, branch)
        if self.prepare is not None:
            await self.prepare()

        extra = {}
        env_vars = await self._deploy_env(project, environment, component)
        if env_vars:
            extra["env_vars"] = env_vars
        record = await self.deployment.deploy_environment(
            project=project,
            environment=environment,
            branch=branch,
            task_id=task_id,
            session_id=session_id,
            component=component,
            **extra,
        )

        # Salva o registro inicial no banco
        saved = await self.tracker.save_deployment(record)

        # As URLs do projeto são as do app; as do backend ficam nos registros.
        if saved.url and component == DeploymentComponent.APP:
            if environment == EnvironmentType.TEST:
                await self.tracker.update_project_deployment_urls(project_id, test_url=saved.url)
            elif environment == EnvironmentType.PRODUCTION:
                await self.tracker.update_project_deployment_urls(project_id, production_url=saved.url)

        return saved

    async def _deploy_env(
        self, project: Project, environment: EnvironmentType, component: DeploymentComponent
    ) -> dict[str, str]:
        """Variables set on the Coolify application before its build.

        O backend recebe os segredos do servidor; o app web, os VITE_* e o
        endereço do backend do mesmo ambiente — o build do Vite os embute.
        """
        if component == DeploymentComponent.BACKEND:
            return await secret_values(self.tracker, project.id, SecretScope.SERVER)
        return {
            **await secret_values(self.tracker, project.id, SecretScope.APP),
            **backend_build_env(project, self.deployment, environment),
        }

    async def _redact(self, record: DeploymentRecord) -> DeploymentRecord:
        """Hide the project's secret values in a log read back from Coolify."""
        if record.logs:
            values = (await secret_values(self.tracker, record.project_id)).values()
            record.logs = redact(record.logs, values)
        return record

    async def remove_secret(self, project: Project, secret: ProjectSecret) -> None:
        """Drop a deleted secret from the Coolify applications it was pushed to.

        Sem isto a variável continuaria no Coolify e voltaria no próximo build.
        Falhas só são registradas: o segredo já saiu do Painkiller.
        """
        component = (
            DeploymentComponent.BACKEND if secret.scope == SecretScope.SERVER else DeploymentComponent.APP
        )
        for environment in (EnvironmentType.TEST, EnvironmentType.PRODUCTION):
            try:
                await self.deployment.remove_env(project, environment, component, secret.name)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"{secret.name} não foi removido do Coolify ({environment.value}): {e}")

    async def _publish_branch(self, project: Project, branch: str) -> None:
        """Push the branch to Gitea before Coolify clones it.

        O push da conclusão da tarefa pode ter falhado (Gitea reiniciando), e
        aí o Coolify falha com "Remote branch ... not found" — ou, na branch
        padrão, publica um commit antigo sem avisar. Empurrar aqui corrige os
        dois casos; sem nada novo, o push não faz nada.
        """
        if self.git is None or not project.repo_url:
            return
        try:
            code, out = await self.git.push(project.repo_path, branch)
        except Exception as e:
            code, out = 1, str(e)
        if code != 0:
            logger.warning(f"Push de {branch} antes do deploy falhou: {out}")
            raise BranchPushError(
                f"Não foi possível enviar a branch {branch} ao Gitea antes do deploy: {out[-500:]}"
            )

    async def _session_finalized(self, session_id: Optional[str]) -> bool:
        if not session_id:
            return False
        session = await self.tracker.get_session(session_id)
        return bool(session and session.status == SessionStatus.COMPLETED)

    async def get_deployment(self, deployment_id: str) -> Optional[DeploymentRecord]:
        """Fetch deployment record and refresh status from Coolify if still pending/building."""
        record = await self.tracker.get_deployment(deployment_id)
        if not record:
            return None

        if record.status in (DeploymentStatus.PENDING, DeploymentStatus.BUILDING) or _settling(record):
            # O adapter altera o registro no lugar: compara com uma cópia, ou
            # nada mudaria nunca e o banco ficaria parado.
            updated = await self._redact(await self.deployment.get_deployment_status(record.model_copy()))
            if updated.status != record.status or updated.logs != record.logs:
                record = await self.tracker.save_deployment(updated)

        return record

    async def create_fix_task(self, deployment_id: str) -> Task:
        """Turn a failed deploy into a task the agent can run to fix the build.

        A tarefa entra na sessão aberta mais recente; com todas encerradas (o
        caso comum de um deploy de produção), abre uma nova. Chamar de novo
        para o mesmo deploy devolve a tarefa já criada, se ainda não concluída.
        """
        record = await self.tracker.get_deployment(deployment_id)
        if not record:
            raise ValueError("Deploy não encontrado")
        if record.status != DeploymentStatus.FAILED:
            raise DeploymentNotFailedError("Só um deploy que falhou pode virar tarefa de correção")
        project = await self.tracker.get_project(record.project_id)
        if not project:
            raise ValueError(f"Projeto {record.project_id} não encontrado")

        sessions = await self.tracker.list_sessions(project.id)
        open_sessions = [s for s in sessions if s.status != SessionStatus.COMPLETED]
        session = open_sessions[-1] if open_sessions else await self.tracker.create_session(project.id)

        marker = _fix_marker(record.id)
        for existing in await self.tracker.list_tasks(project.id, session_id=session.id):
            if existing.status != TaskStatus.COMPLETED and marker in existing.description:
                return existing

        lang = project_language(project)
        env = tr("teste" if record.environment == EnvironmentType.TEST else "produção", lang)
        tail = (record.logs or "")[-FIX_LOG_TAIL_CHARS:].replace("```", "'''")
        parts = [
            tr(
                "O deploy de {env} da branch {branch} falhou no Coolify. Descubra a causa no "
                "log abaixo e corrija o código para que a imagem seja construída e a "
                "aplicação suba.",
                lang, env=env, branch=record.branch,
            ),
        ]
        if record.component == DeploymentComponent.BACKEND:
            parts.append(tr(
                "Quem falhou foi o backend: a imagem é construída a partir de backend/Dockerfile, "
                "com backend/ como contexto.",
                lang,
            ))
        description = "\n\n".join([
            *parts,
            tr(
                "Não há Docker no seu ambiente: reproduza localmente os passos do Dockerfile "
                "que falharam (por exemplo, a instalação de dependências e o build) e só "
                "conclua quando eles passarem.",
                lang,
            ),
            tr("Fim do log do deploy:", lang) + f"\n\n```\n{tail}\n```",
            marker,
        ])
        return await self.tracker.create_task(
            project_id=project.id,
            title=tr("Corrigir o deploy de {env}", lang, env=env),
            description=description,
            acceptance_criteria=[
                tr("Os passos do Dockerfile que falharam no deploy executam sem erro localmente.", lang),
                tr("Os testes existentes continuam passando.", lang),
            ],
            session_id=session.id,
        )

    async def list_project_deployments(self, project_id: str, limit: int = 20) -> list[DeploymentRecord]:
        return await self.tracker.list_project_deployments(project_id, limit=limit)

    async def get_project_environment_status(self, project_id: str) -> dict[str, Any]:
        """Return status and URLs of test and production, plus the backend's when it exists."""
        project = await self.tracker.get_project(project_id)
        if not project:
            raise ValueError(f"Projeto {project_id} não encontrado")

        status: dict[str, Any] = {
            "project_id": project_id,
            "test": await self._environment(project_id, EnvironmentType.TEST, project.test_url),
            "production": await self._environment(
                project_id, EnvironmentType.PRODUCTION, project.production_url
            ),
            "backend": None,
        }
        if has_backend(project.repo_path):
            backend = DeploymentComponent.BACKEND
            status["backend"] = {
                "test": await self._environment(project_id, EnvironmentType.TEST, None, backend),
                "production": await self._environment(project_id, EnvironmentType.PRODUCTION, None, backend),
            }
        return status

    async def _environment(
        self,
        project_id: str,
        environment: EnvironmentType,
        fallback_url: Optional[str],
        component: DeploymentComponent = DeploymentComponent.APP,
    ) -> dict[str, Any]:
        latest = await self.tracker.get_latest_deployment(project_id, environment, component)
        # Atualiza status se estava em building
        if latest and latest.status in (DeploymentStatus.PENDING, DeploymentStatus.BUILDING):
            latest = await self._redact(await self.deployment.get_deployment_status(latest))
            await self.tracker.save_deployment(latest)
        return {
            "url": (latest.url if latest else None) or fallback_url,
            "status": latest.status if latest else None,
            "branch": latest.branch if latest else None,
            "updated_at": latest.updated_at if latest else None,
            "deployment_id": latest.id if latest else None,
        }
