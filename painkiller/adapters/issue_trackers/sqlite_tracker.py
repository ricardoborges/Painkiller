"""SQLite Issue Tracker Adapter using async SQLAlchemy."""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence, Any
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Text,
    Integer,
    Float,
    Enum as SQLEnum,
    select,
    update,
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from painkiller.core.domain.models import (
    Project,
    HarnessType,
    Task,
    TaskStatus,
    ClarificationRequest,
    ClarificationStatus,
    AnalysisSession,
    AnalysisStatus,
    AgentEvent,
    AgentEventType,
    UsageRecord,
    UsageSettings,
    UsageSource,
    IterationSession,
    SessionStatus,
    User,
    UserRole,
    DeploymentRecord,
    EnvironmentType,
    DeploymentStatus,
)
from painkiller.core.ports.issue_tracker import IssueTrackerPort
from painkiller.core.ports.usage_ledger import UsageLedgerPort
from painkiller.core.ports.user_directory import UserDirectoryPort

Base = declarative_base()


class ProjectRecord(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    repo_path = Column(String, nullable=False)
    description = Column(Text, default="")
    purpose = Column(Text, default="")
    solution_description = Column(Text, default="")
    attachments = Column(Text, default="[]")
    default_branch = Column(String, default="main")
    repo_url = Column(String, default="", nullable=True)
    owner_id = Column(String, nullable=True, index=True)
    coolify_project_uuid = Column(String, nullable=True)
    test_url = Column(String, nullable=True)
    production_url = Column(String, nullable=True)
    harness = Column(String, default="agy_superpowers", nullable=False)
    api_key = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class UserRecord(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, nullable=False, index=True)
    name = Column(String, default="")
    role = Column(SQLEnum(UserRole), default=UserRole.USER)
    google_sub = Column(String, nullable=True, unique=True, index=True)
    gitea_username = Column(String, nullable=True, unique=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class TaskRecord(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    target_files = Column(Text, default="[]")
    acceptance_criteria = Column(Text, default="[]")
    dependencies = Column(Text, default="[]")
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.BACKLOG)
    assigned_branch = Column(String, nullable=True)
    session_id = Column(String, nullable=True, index=True)
    last_comment = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    issue_number = Column(Integer, nullable=True)
    issue_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class TaskCommentRecord(Base):
    __tablename__ = "task_comments"

    id = Column(String, primary_key=True)
    task_id = Column(String, nullable=False, index=True)
    author = Column(String, nullable=False)
    comment = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class IterationSessionRecord(Base):
    __tablename__ = "iteration_sessions"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    number = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    status = Column(SQLEnum(SessionStatus), default=SessionStatus.PLANNING)
    analysis_session_id = Column(String, nullable=True)
    spec_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ClarificationRecord(Base):
    __tablename__ = "clarifications"

    id = Column(String, primary_key=True)
    task_id = Column(String, nullable=False, index=True)
    question = Column(Text, nullable=False)
    context_summary = Column(Text, nullable=False)
    status = Column(SQLEnum(ClarificationStatus), default=ClarificationStatus.PENDING)
    answer = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    answered_at = Column(DateTime, nullable=True)


class AnalysisSessionRecord(Base):
    __tablename__ = "analysis_sessions"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    status = Column(SQLEnum(AnalysisStatus), default=AnalysisStatus.STARTING)
    container_name = Column(String, nullable=True)
    claude_session_id = Column(String, nullable=True)
    exit_code = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    spec_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AnalysisEventRecord(Base):
    __tablename__ = "analysis_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False, index=True)
    event_type = Column(SQLEnum(AgentEventType), nullable=False)
    text = Column(Text, default="")
    raw = Column(Text, default="{}")
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class UsageRecordRow(Base):
    __tablename__ = "usage_records"

    id = Column(String, primary_key=True)
    source = Column(SQLEnum(UsageSource), nullable=False)
    model = Column(String, default="")
    project_id = Column(String, nullable=True, index=True)
    task_id = Column(String, nullable=True)
    session_id = Column(String, nullable=True)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    reported_cost_usd = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class SettingRecord(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(Text, default="{}")


class DeploymentRecordRow(Base):
    __tablename__ = "deployments"

    id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    task_id = Column(String, nullable=True, index=True)
    session_id = Column(String, nullable=True, index=True)
    environment = Column(SQLEnum(EnvironmentType), nullable=False)
    branch = Column(String, default="main")
    commit_sha = Column(String, nullable=True)
    status = Column(SQLEnum(DeploymentStatus), default=DeploymentStatus.PENDING)
    coolify_app_uuid = Column(String, nullable=True)
    coolify_deployment_uuid = Column(String, nullable=True)
    url = Column(String, nullable=True)
    logs = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


#: Chave da linha de `settings` que guarda orçamento e preços.
USAGE_SETTINGS_KEY = "usage"


def _budget_key(project_id: str) -> str:
    return f"usage:budget:{project_id}"


class SQLiteIssueTracker(IssueTrackerPort, UsageLedgerPort, UserDirectoryPort):
    """Asynchronous SQLite implementation of the tracker, usage ledger and user directory ports."""

    def __init__(self, db_url: str = "sqlite+aiosqlite:///painkiller.db"):
        self.engine = create_async_engine(db_url, echo=False)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    async def init_db(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(self._migrate_columns)

    @staticmethod
    def _migrate_columns(connection) -> None:
        """Add any missing columns to existing SQLite tables to handle schema evolution."""
        from sqlalchemy import inspect
        inspector = inspect(connection)
        for table_name, table in Base.metadata.tables.items():
            if not inspector.has_table(table_name):
                continue
            existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name not in existing_cols:
                    col_type = col.type.compile(connection.dialect)
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}"
                    connection.exec_driver_sql(sql)

    async def close(self) -> None:
        await self.engine.dispose()

    async def create_project(
        self,
        name: str,
        repo_path: str,
        description: str = "",
        purpose: str = "",
        solution_description: str = "",
        attachments: Optional[Sequence[str]] = None,
        default_branch: str = "main",
        repo_url: Optional[str] = None,
        owner_id: Optional[str] = None,
        harness: Optional[HarnessType] = None,
        api_key: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Project:
        proj_id = project_id or f"proj-{uuid.uuid4().hex[:8]}"
        harness_val = (harness.value if isinstance(harness, HarnessType) else harness) or HarnessType.AGY_SUPERPOWERS.value
        record = ProjectRecord(
            id=proj_id,
            name=name,
            repo_path=repo_path,
            description=description,
            purpose=purpose,
            solution_description=solution_description,
            attachments=json.dumps(list(attachments or [])),
            default_branch=default_branch,
            repo_url=repo_url or "",
            owner_id=owner_id,
            harness=harness_val,
            api_key=api_key or None,
            created_at=datetime.now(timezone.utc),
        )
        async with self.session_factory() as session:
            session.add(record)
            await session.commit()
            return self._to_project_domain(record)

    async def list_projects(self, owner_id: Optional[str] = None) -> list[Project]:
        stmt = select(ProjectRecord).order_by(ProjectRecord.created_at.desc())
        if owner_id is not None:
            stmt = stmt.where(ProjectRecord.owner_id == owner_id)
        async with self.session_factory() as session:
            res = await session.execute(stmt)
            records = res.scalars().all()
            return [self._to_project_domain(r) for r in records]

    async def get_project(self, project_id: str) -> Optional[Project]:
        async with self.session_factory() as session:
            res = await session.execute(select(ProjectRecord).where(ProjectRecord.id == project_id))
            record = res.scalar_one_or_none()
            if not record:
                return None
            return self._to_project_domain(record)

    async def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        purpose: Optional[str] = None,
        solution_description: Optional[str] = None,
        attachments: Optional[Sequence[str]] = None,
        repo_url: Optional[str] = None,
        harness: Optional[HarnessType] = None,
        api_key: Optional[str] = None,
    ) -> Project:
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        if purpose is not None:
            values["purpose"] = purpose
        if solution_description is not None:
            values["solution_description"] = solution_description
        if attachments is not None:
            values["attachments"] = json.dumps(list(attachments))
        if repo_url is not None:
            values["repo_url"] = repo_url
        if harness is not None:
            values["harness"] = harness.value if isinstance(harness, HarnessType) else harness
        if api_key is not None:
            values["api_key"] = api_key or None

        async with self.session_factory() as session:
            if values:
                await session.execute(
                    update(ProjectRecord)
                    .where(ProjectRecord.id == project_id)
                    .values(**values)
                )
                await session.commit()
            res = await session.execute(select(ProjectRecord).where(ProjectRecord.id == project_id))
            record = res.scalar_one_or_none()
            if not record:
                raise ValueError(f"Project {project_id} not found")
            return self._to_project_domain(record)

    async def delete_project(self, project_id: str) -> None:
        from sqlalchemy import delete
        async with self.session_factory() as session:
            # Delete tasks and clarifications first
            tasks_res = await session.execute(select(TaskRecord.id).where(TaskRecord.project_id == project_id))
            task_ids = tasks_res.scalars().all()
            if task_ids:
                await session.execute(delete(ClarificationRecord).where(ClarificationRecord.task_id.in_(task_ids)))
                await session.execute(delete(TaskRecord).where(TaskRecord.project_id == project_id))
            await session.execute(delete(IterationSessionRecord).where(IterationSessionRecord.project_id == project_id))
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == project_id))
            await session.execute(delete(SettingRecord).where(SettingRecord.key == _budget_key(project_id)))
            await session.commit()

    def _to_project_domain(self, record: ProjectRecord) -> Project:
        return Project(
            id=record.id,
            name=record.name,
            repo_path=record.repo_path,
            description=record.description or "",
            purpose=record.purpose or "",
            solution_description=record.solution_description or "",
            attachments=json.loads(record.attachments or "[]"),
            default_branch=record.default_branch,
            repo_url=record.repo_url or None,
            owner_id=record.owner_id or None,
            coolify_project_uuid=getattr(record, "coolify_project_uuid", None) or None,
            test_url=getattr(record, "test_url", None) or None,
            production_url=getattr(record, "production_url", None) or None,
            harness=HarnessType(getattr(record, "harness", None) or "agy_superpowers") if getattr(record, "harness", None) in [h.value for h in HarnessType] else HarnessType.AGY_SUPERPOWERS,
            api_key=getattr(record, "api_key", None) or None,
            created_at=record.created_at,
        )

    # ------------------------------------------------------------------
    # Usuários
    # ------------------------------------------------------------------

    async def create_user(
        self,
        email: str,
        name: str = "",
        google_sub: Optional[str] = None,
        gitea_username: Optional[str] = None,
    ) -> User:
        record = UserRecord(
            id=f"user-{uuid.uuid4().hex[:10]}",
            email=email,
            name=name,
            role=UserRole.USER,
            google_sub=google_sub,
            gitea_username=gitea_username,
            created_at=datetime.now(timezone.utc),
        )
        async with self.session_factory() as session:
            session.add(record)
            await session.commit()
            return self._to_user_domain(record)

    async def get_user(self, user_id: str) -> Optional[User]:
        async with self.session_factory() as session:
            res = await session.execute(select(UserRecord).where(UserRecord.id == user_id))
            record = res.scalar_one_or_none()
            return self._to_user_domain(record) if record else None

    async def get_user_by_google_sub(self, google_sub: str) -> Optional[User]:
        async with self.session_factory() as session:
            res = await session.execute(select(UserRecord).where(UserRecord.google_sub == google_sub))
            record = res.scalar_one_or_none()
            return self._to_user_domain(record) if record else None

    async def update_user(
        self,
        user_id: str,
        email: Optional[str] = None,
        name: Optional[str] = None,
        gitea_username: Optional[str] = None,
    ) -> User:
        values: dict[str, Any] = {}
        if email is not None:
            values["email"] = email
        if name is not None:
            values["name"] = name
        if gitea_username is not None:
            values["gitea_username"] = gitea_username
        async with self.session_factory() as session:
            if values:
                await session.execute(update(UserRecord).where(UserRecord.id == user_id).values(**values))
                await session.commit()
            res = await session.execute(select(UserRecord).where(UserRecord.id == user_id))
            record = res.scalar_one_or_none()
            if not record:
                raise ValueError(f"User {user_id} not found")
            return self._to_user_domain(record)

    def _to_user_domain(self, record: UserRecord) -> User:
        return User(
            id=record.id,
            email=record.email,
            name=record.name or "",
            role=record.role or UserRole.USER,
            google_sub=record.google_sub,
            gitea_username=record.gitea_username,
            created_at=record.created_at,
        )

    async def create_task(
        self,
        project_id: str,
        title: str,
        description: str,
        target_files: Optional[Sequence[str]] = None,
        acceptance_criteria: Optional[Sequence[str]] = None,
        dependencies: Optional[Sequence[str]] = None,
        session_id: Optional[str] = None,
    ) -> Task:
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        record = TaskRecord(
            id=task_id,
            project_id=project_id,
            title=title,
            description=description,
            target_files=json.dumps(list(target_files or [])),
            acceptance_criteria=json.dumps(list(acceptance_criteria or [])),
            dependencies=json.dumps(list(dependencies or [])),
            status=TaskStatus.BACKLOG,
            session_id=session_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        async with self.session_factory() as session:
            session.add(record)
            await session.commit()
            return self._to_task_domain(record)

    async def get_task(self, task_id: str) -> Optional[Task]:
        async with self.session_factory() as session:
            res = await session.execute(select(TaskRecord).where(TaskRecord.id == task_id))
            record = res.scalar_one_or_none()
            if not record:
                return None
            return self._to_task_domain(record)

    async def list_tasks(
        self,
        project_id: str,
        status: Optional[TaskStatus] = None,
        session_id: Optional[str] = None,
    ) -> list[Task]:
        async with self.session_factory() as session:
            stmt = select(TaskRecord).where(TaskRecord.project_id == project_id)
            if status:
                stmt = stmt.where(TaskRecord.status == status)
            if session_id:
                stmt = stmt.where(TaskRecord.session_id == session_id)
            stmt = stmt.order_by(TaskRecord.created_at.asc())
            res = await session.execute(stmt)
            records = res.scalars().all()
            return [self._to_task_domain(r) for r in records]

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        assigned_branch: Optional[str] = None,
        error: Optional[str] = None,
        last_comment: Optional[str] = None,
    ) -> Task:
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {"status": status, "updated_at": now}
        if assigned_branch is not None:
            values["assigned_branch"] = assigned_branch
        if error is not None:
            values["error"] = error
        if last_comment is not None:
            values["last_comment"] = last_comment

        async with self.session_factory() as session:
            await session.execute(
                update(TaskRecord)
                .where(TaskRecord.id == task_id)
                .values(**values)
            )
            await session.commit()
            res = await session.execute(select(TaskRecord).where(TaskRecord.id == task_id))
            record = res.scalar_one()
            return self._to_task_domain(record)

    async def set_task_issue(self, task_id: str, issue_number: int, issue_url: str) -> Task:
        async with self.session_factory() as session:
            await session.execute(
                update(TaskRecord)
                .where(TaskRecord.id == task_id)
                .values(issue_number=issue_number, issue_url=issue_url)
            )
            await session.commit()
            res = await session.execute(select(TaskRecord).where(TaskRecord.id == task_id))
            return self._to_task_domain(res.scalar_one())

    async def add_comment(self, task_id: str, author: str, comment: str) -> None:
        now = datetime.now(timezone.utc)
        record = TaskCommentRecord(
            id=f"comm-{uuid.uuid4().hex[:8]}",
            task_id=task_id,
            author=author,
            comment=comment,
            created_at=now,
        )
        async with self.session_factory() as session:
            session.add(record)
            await session.execute(
                update(TaskRecord)
                .where(TaskRecord.id == task_id)
                .values(last_comment=comment, updated_at=now)
            )
            await session.commit()

    async def create_clarification(
        self,
        task_id: str,
        question: str,
        context_summary: str,
    ) -> ClarificationRequest:
        clar_id = f"clar-{uuid.uuid4().hex[:8]}"
        record = ClarificationRecord(
            id=clar_id,
            task_id=task_id,
            question=question,
            context_summary=context_summary,
            status=ClarificationStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        async with self.session_factory() as session:
            session.add(record)
            await session.commit()
            return ClarificationRequest(
                id=record.id,
                task_id=record.task_id,
                question=record.question,
                context_summary=record.context_summary,
                status=record.status,
                created_at=record.created_at,
            )

    async def resolve_clarification(
        self,
        clarification_id: str,
        answer: str,
    ) -> ClarificationRequest:
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            await session.execute(
                update(ClarificationRecord)
                .where(ClarificationRecord.id == clarification_id)
                .values(answer=answer, status=ClarificationStatus.ANSWERED, answered_at=now)
            )
            await session.commit()
            res = await session.execute(
                select(ClarificationRecord).where(ClarificationRecord.id == clarification_id)
            )
            record = res.scalar_one()
            return ClarificationRequest(
                id=record.id,
                task_id=record.task_id,
                question=record.question,
                context_summary=record.context_summary,
                status=record.status,
                answer=record.answer,
                created_at=record.created_at,
                answered_at=record.answered_at,
            )

    async def get_pending_clarification(self, task_id: str) -> Optional[ClarificationRequest]:
        async with self.session_factory() as session:
            res = await session.execute(
                select(ClarificationRecord)
                .where(
                    ClarificationRecord.task_id == task_id,
                    ClarificationRecord.status == ClarificationStatus.PENDING,
                )
                .order_by(ClarificationRecord.created_at.desc())
            )
            record = res.scalars().first()
            if not record:
                return None
            return ClarificationRequest(
                id=record.id,
                task_id=record.task_id,
                question=record.question,
                context_summary=record.context_summary,
                status=record.status,
                answer=record.answer,
                created_at=record.created_at,
                answered_at=record.answered_at,
            )

    def _to_task_domain(self, record: TaskRecord) -> Task:
        return Task(
            id=record.id,
            project_id=record.project_id,
            title=record.title,
            description=record.description,
            target_files=json.loads(record.target_files or "[]"),
            acceptance_criteria=json.loads(record.acceptance_criteria or "[]"),
            dependencies=json.loads(record.dependencies or "[]"),
            status=record.status,
            assigned_branch=record.assigned_branch,
            session_id=record.session_id,
            last_comment=record.last_comment,
            error=record.error,
            issue_number=getattr(record, "issue_number", None),
            issue_url=getattr(record, "issue_url", None),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    async def save_analysis_session(self, session: AnalysisSession) -> AnalysisSession:
        async with self.session_factory() as db_session:
            res = await db_session.execute(
                select(AnalysisSessionRecord).where(AnalysisSessionRecord.id == session.id)
            )
            record = res.scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if record is None:
                record = AnalysisSessionRecord(
                    id=session.id,
                    project_id=session.project_id,
                    status=session.status,
                    container_name=session.container_name,
                    claude_session_id=session.claude_session_id,
                    exit_code=session.exit_code,
                    error=session.error,
                    spec_path=session.spec_path,
                    created_at=session.created_at or now,
                    updated_at=now,
                )
                db_session.add(record)
            else:
                record.status = session.status
                record.container_name = session.container_name
                record.claude_session_id = session.claude_session_id
                record.exit_code = session.exit_code
                record.error = session.error
                record.spec_path = session.spec_path
                record.updated_at = now
            await db_session.commit()
            await db_session.refresh(record)
            return self._to_analysis_domain(record)

    async def get_analysis_session(self, session_id: str) -> Optional[AnalysisSession]:
        async with self.session_factory() as db_session:
            res = await db_session.execute(
                select(AnalysisSessionRecord).where(AnalysisSessionRecord.id == session_id)
            )
            record = res.scalar_one_or_none()
            if not record:
                return None
            return self._to_analysis_domain(record)

    async def get_active_analysis_session(self, project_id: str) -> Optional[AnalysisSession]:
        async with self.session_factory() as db_session:
            res = await db_session.execute(
                select(AnalysisSessionRecord)
                .where(
                    AnalysisSessionRecord.project_id == project_id,
                    AnalysisSessionRecord.status.not_in(
                        [AnalysisStatus.FINISHED, AnalysisStatus.FAILED]
                    ),
                )
                .order_by(AnalysisSessionRecord.created_at.desc())
            )
            record = res.scalars().first()
            if not record:
                return None
            return self._to_analysis_domain(record)

    async def save_analysis_event(self, session_id: str, event: AgentEvent) -> None:
        async with self.session_factory() as db_session:
            record = AnalysisEventRecord(
                session_id=session_id,
                event_type=event.type,
                text=event.text,
                raw=json.dumps(event.raw, ensure_ascii=False),
                timestamp=event.timestamp or datetime.now(timezone.utc),
            )
            db_session.add(record)
            await db_session.commit()

    async def list_analysis_events(self, session_id: str) -> list[AgentEvent]:
        async with self.session_factory() as db_session:
            res = await db_session.execute(
                select(AnalysisEventRecord)
                .where(AnalysisEventRecord.session_id == session_id)
                .order_by(AnalysisEventRecord.id.asc())
            )
            records = res.scalars().all()
            return [
                AgentEvent(
                    type=r.event_type,
                    text=r.text,
                    raw=json.loads(r.raw or "{}"),
                    timestamp=r.timestamp,
                )
                for r in records
            ]

    def _to_analysis_domain(self, record: AnalysisSessionRecord) -> AnalysisSession:
        return AnalysisSession(
            id=record.id,
            project_id=record.project_id,
            status=record.status,
            container_name=record.container_name,
            claude_session_id=record.claude_session_id,
            exit_code=record.exit_code,
            error=record.error,
            spec_path=record.spec_path,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    async def record_usage(self, record: UsageRecord) -> UsageRecord:
        record_id = record.id or f"usage-{uuid.uuid4().hex[:10]}"
        row = UsageRecordRow(
            id=record_id,
            source=record.source,
            model=record.model,
            project_id=record.project_id,
            task_id=record.task_id,
            session_id=record.session_id,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            reported_cost_usd=record.reported_cost_usd,
            created_at=record.created_at,
        )
        async with self.session_factory() as db_session:
            db_session.add(row)
            await db_session.commit()
        return record.model_copy(update={"id": record_id})

    async def list_usage(
        self,
        project_id: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> list[UsageRecord]:
        async with self.session_factory() as db_session:
            stmt = select(UsageRecordRow)
            if project_id:
                stmt = stmt.where(UsageRecordRow.project_id == project_id)
            if since:
                stmt = stmt.where(UsageRecordRow.created_at >= since)
            res = await db_session.execute(stmt.order_by(UsageRecordRow.created_at.asc()))
            return [
                UsageRecord(
                    id=r.id,
                    source=r.source,
                    model=r.model or "",
                    project_id=r.project_id,
                    task_id=r.task_id,
                    session_id=r.session_id,
                    input_tokens=r.input_tokens or 0,
                    output_tokens=r.output_tokens or 0,
                    reported_cost_usd=r.reported_cost_usd,
                    created_at=r.created_at,
                )
                for r in res.scalars().all()
            ]

    async def _read_setting(self, key: str) -> Optional[str]:
        async with self.session_factory() as db_session:
            res = await db_session.execute(select(SettingRecord).where(SettingRecord.key == key))
            row = res.scalar_one_or_none()
            return row.value if row else None

    async def _write_setting(self, key: str, value: Optional[str]) -> None:
        """Upsert a setting; None deletes it."""
        async with self.session_factory() as db_session:
            res = await db_session.execute(select(SettingRecord).where(SettingRecord.key == key))
            row = res.scalar_one_or_none()
            if value is None:
                if row is not None:
                    await db_session.delete(row)
            elif row is None:
                db_session.add(SettingRecord(key=key, value=value))
            else:
                row.value = value
            await db_session.commit()

    async def get_usage_settings(self) -> UsageSettings:
        value = await self._read_setting(USAGE_SETTINGS_KEY)
        if value is None:
            return UsageSettings()
        return UsageSettings.model_validate(json.loads(value or "{}"))

    async def save_usage_settings(self, settings: UsageSettings) -> UsageSettings:
        await self._write_setting(USAGE_SETTINGS_KEY, settings.model_dump_json())
        return settings

    async def get_project_budget(self, project_id: str) -> Optional[float]:
        value = await self._read_setting(_budget_key(project_id))
        if value is None:
            return None
        return json.loads(value).get("budget_usd")

    async def save_project_budget(self, project_id: str, budget_usd: Optional[float]) -> None:
        value = None if budget_usd is None else json.dumps({"budget_usd": budget_usd})
        await self._write_setting(_budget_key(project_id), value)

    def _to_iteration_session_domain(self, record: IterationSessionRecord) -> IterationSession:
        return IterationSession(
            id=record.id,
            project_id=record.project_id,
            number=record.number,
            title=record.title,
            status=record.status,
            analysis_session_id=record.analysis_session_id,
            spec_path=record.spec_path,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    async def ensure_initial_session(self, project_id: str) -> IterationSession:
        async with self.session_factory() as session:
            stmt = select(IterationSessionRecord).where(
                IterationSessionRecord.project_id == project_id
            ).order_by(IterationSessionRecord.number.asc())
            res = await session.execute(stmt)
            records = res.scalars().all()
            if records:
                return self._to_iteration_session_domain(records[0])

            sess_id = f"sess-{uuid.uuid4().hex[:8]}"
            now = datetime.now(timezone.utc)
            record = IterationSessionRecord(
                id=sess_id,
                project_id=project_id,
                number=1,
                title="Sessão 1",
                status=SessionStatus.PLANNING,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            # Associar tarefas legadas orfas do projeto à Sessão 1
            await session.execute(
                update(TaskRecord)
                .where((TaskRecord.project_id == project_id) & (TaskRecord.session_id.is_(None)))
                .values(session_id=sess_id)
            )
            await session.commit()
            return self._to_iteration_session_domain(record)

    async def create_session(
        self,
        project_id: str,
        title: Optional[str] = None,
    ) -> IterationSession:
        async with self.session_factory() as session:
            stmt = select(IterationSessionRecord.number).where(
                IterationSessionRecord.project_id == project_id
            )
            res = await session.execute(stmt)
            numbers = res.scalars().all()
            next_num = max(numbers, default=0) + 1

            sess_id = f"sess-{uuid.uuid4().hex[:8]}"
            sess_title = title or f"Sessão {next_num}"
            now = datetime.now(timezone.utc)
            record = IterationSessionRecord(
                id=sess_id,
                project_id=project_id,
                number=next_num,
                title=sess_title,
                status=SessionStatus.PLANNING,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            await session.commit()
            return self._to_iteration_session_domain(record)

    async def list_sessions(self, project_id: str) -> list[IterationSession]:
        async with self.session_factory() as session:
            stmt = select(IterationSessionRecord).where(
                IterationSessionRecord.project_id == project_id
            ).order_by(IterationSessionRecord.number.asc())
            res = await session.execute(stmt)
            records = res.scalars().all()
            return [self._to_iteration_session_domain(r) for r in records]

    async def get_session(self, session_id: str) -> Optional[IterationSession]:
        async with self.session_factory() as session:
            res = await session.execute(
                select(IterationSessionRecord).where(IterationSessionRecord.id == session_id)
            )
            record = res.scalar_one_or_none()
            if not record:
                return None
            return self._to_iteration_session_domain(record)

    async def update_session(self, session: IterationSession) -> IterationSession:
        now = datetime.now(timezone.utc)
        async with self.session_factory() as db_session:
            await db_session.execute(
                update(IterationSessionRecord)
                .where(IterationSessionRecord.id == session.id)
                .values(
                    title=session.title,
                    status=session.status,
                    analysis_session_id=session.analysis_session_id,
                    spec_path=session.spec_path,
                    updated_at=now,
                )
            )
            await db_session.commit()
            res = await db_session.execute(
                select(IterationSessionRecord).where(IterationSessionRecord.id == session.id)
            )
            record = res.scalar_one()
            return self._to_iteration_session_domain(record)

    async def migrate_tasks_to_session(
        self,
        task_ids: Sequence[str],
        target_session_id: str,
    ) -> list[Task]:
        if not task_ids:
            return []
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            await session.execute(
                update(TaskRecord)
                .where(TaskRecord.id.in_(list(task_ids)))
                .values(session_id=target_session_id, updated_at=now)
            )
            await session.commit()
            res = await session.execute(
                select(TaskRecord).where(TaskRecord.id.in_(list(task_ids)))
            )
            records = res.scalars().all()
            return [self._to_task_domain(r) for r in records]

    # ------------------------------------------------------------------
    # Deployments
    # ------------------------------------------------------------------

    def _to_deployment_domain(self, record: DeploymentRecordRow) -> DeploymentRecord:
        return DeploymentRecord(
            id=record.id,
            project_id=record.project_id,
            task_id=record.task_id or None,
            session_id=record.session_id or None,
            environment=record.environment,
            branch=record.branch or "main",
            commit_sha=record.commit_sha or None,
            status=record.status,
            coolify_app_uuid=record.coolify_app_uuid or None,
            coolify_deployment_uuid=record.coolify_deployment_uuid or None,
            url=record.url or None,
            logs=record.logs or None,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    async def save_deployment(self, deployment: DeploymentRecord) -> DeploymentRecord:
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            res = await session.execute(
                select(DeploymentRecordRow).where(DeploymentRecordRow.id == deployment.id)
            )
            existing = res.scalar_one_or_none()
            if existing:
                await session.execute(
                    update(DeploymentRecordRow)
                    .where(DeploymentRecordRow.id == deployment.id)
                    .values(
                        status=deployment.status,
                        commit_sha=deployment.commit_sha,
                        coolify_app_uuid=deployment.coolify_app_uuid,
                        coolify_deployment_uuid=deployment.coolify_deployment_uuid,
                        url=deployment.url,
                        logs=deployment.logs,
                        updated_at=now,
                    )
                )
            else:
                row = DeploymentRecordRow(
                    id=deployment.id,
                    project_id=deployment.project_id,
                    task_id=deployment.task_id,
                    session_id=deployment.session_id,
                    environment=deployment.environment,
                    branch=deployment.branch,
                    commit_sha=deployment.commit_sha,
                    status=deployment.status,
                    coolify_app_uuid=deployment.coolify_app_uuid,
                    coolify_deployment_uuid=deployment.coolify_deployment_uuid,
                    url=deployment.url,
                    logs=deployment.logs,
                    created_at=deployment.created_at,
                    updated_at=now,
                )
                session.add(row)
            await session.commit()

            res = await session.execute(
                select(DeploymentRecordRow).where(DeploymentRecordRow.id == deployment.id)
            )
            saved = res.scalar_one()
            return self._to_deployment_domain(saved)

    async def get_deployment(self, deployment_id: str) -> Optional[DeploymentRecord]:
        async with self.session_factory() as session:
            res = await session.execute(
                select(DeploymentRecordRow).where(DeploymentRecordRow.id == deployment_id)
            )
            record = res.scalar_one_or_none()
            return self._to_deployment_domain(record) if record else None

    async def list_project_deployments(
        self, project_id: str, limit: int = 20
    ) -> list[DeploymentRecord]:
        async with self.session_factory() as session:
            res = await session.execute(
                select(DeploymentRecordRow)
                .where(DeploymentRecordRow.project_id == project_id)
                .order_by(DeploymentRecordRow.created_at.desc())
                .limit(limit)
            )
            records = res.scalars().all()
            return [self._to_deployment_domain(r) for r in records]

    async def get_latest_deployment(
        self, project_id: str, environment: EnvironmentType
    ) -> Optional[DeploymentRecord]:
        async with self.session_factory() as session:
            res = await session.execute(
                select(DeploymentRecordRow)
                .where(
                    DeploymentRecordRow.project_id == project_id,
                    DeploymentRecordRow.environment == environment,
                )
                .order_by(DeploymentRecordRow.created_at.desc())
                .limit(1)
            )
            record = res.scalar_one_or_none()
            return self._to_deployment_domain(record) if record else None

    async def update_project_deployment_urls(
        self,
        project_id: str,
        test_url: Optional[str] = None,
        production_url: Optional[str] = None,
        coolify_project_uuid: Optional[str] = None,
    ) -> Project:
        values: dict[str, Any] = {}
        if test_url is not None:
            values["test_url"] = test_url
        if production_url is not None:
            values["production_url"] = production_url
        if coolify_project_uuid is not None:
            values["coolify_project_uuid"] = coolify_project_uuid

        if values:
            async with self.session_factory() as session:
                await session.execute(
                    update(ProjectRecord)
                    .where(ProjectRecord.id == project_id)
                    .values(**values)
                )
                await session.commit()

        project = await self.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        return project

