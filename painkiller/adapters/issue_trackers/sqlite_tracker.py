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
    Enum as SQLEnum,
    select,
    update,
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from painkiller.core.domain.models import (
    Project,
    Task,
    TaskStatus,
    ClarificationRequest,
    ClarificationStatus,
    AnalysisSession,
    AnalysisStatus,
    AgentEvent,
    AgentEventType,
)
from painkiller.core.ports.issue_tracker import IssueTrackerPort

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


class SQLiteIssueTracker(IssueTrackerPort):
    """Asynchronous SQLite implementation of IssueTrackerPort."""

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
    ) -> Project:
        proj_id = f"proj-{uuid.uuid4().hex[:8]}"
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
            created_at=datetime.now(timezone.utc),
        )
        async with self.session_factory() as session:
            session.add(record)
            await session.commit()
            return self._to_project_domain(record)

    async def list_projects(self) -> list[Project]:
        async with self.session_factory() as session:
            res = await session.execute(select(ProjectRecord).order_by(ProjectRecord.created_at.desc()))
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
            await session.execute(delete(ProjectRecord).where(ProjectRecord.id == project_id))
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
    ) -> list[Task]:
        async with self.session_factory() as session:
            stmt = select(TaskRecord).where(TaskRecord.project_id == project_id)
            if status:
                stmt = stmt.where(TaskRecord.status == status)
            stmt = stmt.order_by(TaskRecord.created_at.asc())
            res = await session.execute(stmt)
            records = res.scalars().all()
            return [self._to_task_domain(r) for r in records]

    async def update_task_status(self, task_id: str, status: TaskStatus) -> Task:
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            await session.execute(
                update(TaskRecord)
                .where(TaskRecord.id == task_id)
                .values(status=status, updated_at=now)
            )
            await session.commit()
            res = await session.execute(select(TaskRecord).where(TaskRecord.id == task_id))
            record = res.scalar_one()
            return self._to_task_domain(record)

    async def add_comment(self, task_id: str, author: str, comment: str) -> None:
        # Currently recorded via logging or optional audit table
        pass

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

