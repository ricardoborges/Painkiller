"""SQLite Issue Tracker Adapter using async SQLAlchemy."""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Text,
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
)
from painkiller.core.ports.issue_tracker import IssueTrackerPort

Base = declarative_base()


class ProjectRecord(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    repo_path = Column(String, nullable=False)
    default_branch = Column(String, default="main")
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


class SQLiteIssueTracker(IssueTrackerPort):
    """Asynchronous SQLite implementation of IssueTrackerPort."""

    def __init__(self, db_url: str = "sqlite+aiosqlite:///painkiller.db"):
        self.engine = create_async_engine(db_url, echo=False)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    async def init_db(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    async def create_project(self, name: str, repo_path: str, default_branch: str = "main") -> Project:
        proj_id = f"proj-{uuid.uuid4().hex[:8]}"
        record = ProjectRecord(
            id=proj_id,
            name=name,
            repo_path=repo_path,
            default_branch=default_branch,
            created_at=datetime.now(timezone.utc),
        )
        async with self.session_factory() as session:
            session.add(record)
            await session.commit()
            return Project(
                id=record.id,
                name=record.name,
                repo_path=record.repo_path,
                default_branch=record.default_branch,
                created_at=record.created_at,
            )

    async def get_project(self, project_id: str) -> Optional[Project]:
        async with self.session_factory() as session:
            res = await session.execute(select(ProjectRecord).where(ProjectRecord.id == project_id))
            record = res.scalar_one_or_none()
            if not record:
                return None
            return Project(
                id=record.id,
                name=record.name,
                repo_path=record.repo_path,
                default_branch=record.default_branch,
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
