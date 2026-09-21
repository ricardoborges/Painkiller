"""Unit tests for project superpowers docs endpoints."""

import os
import tempfile
import pytest
from httpx import AsyncClient, ASGITransport
from painkiller.api.server import create_app
from tests.auth_helpers import admin_headers
from painkiller.core.domain.models import Project


@pytest.mark.asyncio
async def test_list_and_get_project_docs():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create mock project files
        specs_dir = os.path.join(tmpdir, "docs", "superpowers", "specs")
        os.makedirs(specs_dir, exist_ok=True)
        spec_file = os.path.join(specs_dir, "2026-09-20-auth-design.md")
        with open(spec_file, "w", encoding="utf-8") as f:
            f.write("# Auth Design Spec\n\nDetailed requirements here.")

        plans_dir = os.path.join(tmpdir, "docs", "superpowers", "plans")
        os.makedirs(plans_dir, exist_ok=True)
        plan_file = os.path.join(plans_dir, "2026-09-20-auth-plan.md")
        with open(plan_file, "w", encoding="utf-8") as f:
            f.write("# Auth Plan\n\nImplementation steps.")

        backlog_dir = os.path.join(tmpdir, ".painkiller")
        os.makedirs(backlog_dir, exist_ok=True)
        backlog_file = os.path.join(backlog_dir, "backlog.json")
        with open(backlog_file, "w", encoding="utf-8") as f:
            f.write('{"tasks": []}')

        db_path = os.path.join(tmpdir, "test.db")
        app = create_app(db_url=f"sqlite+aiosqlite:///{db_path}")

        async with app.router.lifespan_context(app):
            tracker = app.state.tracker
            project = await tracker.create_project(
                name="Test Docs Project",
                repo_path=tmpdir,
                description="Testing docs discovery",
            )

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test", headers=admin_headers()) as ac:
                # 1. List docs
                res = await ac.get(f"/api/projects/{project.id}/docs")
                assert res.status_code == 200
                docs = res.json()
                assert len(docs) == 3

                filenames = [d["filename"] for d in docs]
                assert "2026-09-20-auth-design.md" in filenames
                assert "2026-09-20-auth-plan.md" in filenames
                assert "backlog.json" in filenames

                # Categories
                cat_map = {d["filename"]: d["category"] for d in docs}
                assert cat_map["2026-09-20-auth-design.md"] == "spec"
                assert cat_map["2026-09-20-auth-plan.md"] == "plan"
                assert cat_map["backlog.json"] == "backlog"

                # 2. Get content
                res_content = await ac.get(
                    f"/api/projects/{project.id}/docs/content",
                    params={"path": "docs/superpowers/specs/2026-09-20-auth-design.md"},
                )
                assert res_content.status_code == 200
                data = res_content.json()
                assert "# Auth Design Spec" in data["content"]

                # 3. Path traversal security check
                res_bad = await ac.get(
                    f"/api/projects/{project.id}/docs/content",
                    params={"path": "../../../etc/passwd"},
                )
                assert res_bad.status_code == 403

                # 4. Non-existent file
                res_404 = await ac.get(
                    f"/api/projects/{project.id}/docs/content",
                    params={"path": "docs/superpowers/specs/nonexistent.md"},
                )
                assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_download_project_archive_zips_tracked_files_of_default_branch():
    import io
    import subprocess
    import zipfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        os.makedirs(repo)

        def git(*args):
            subprocess.run(
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                cwd=repo, check=True, capture_output=True,
            )

        git("init", "-b", "main")
        with open(os.path.join(repo, "app.py"), "w", encoding="utf-8") as f:
            f.write("print('ok')\n")
        git("add", "app.py")
        git("commit", "-m", "init")
        # Untracked: must not leak into the zip
        with open(os.path.join(repo, "segredo.txt"), "w", encoding="utf-8") as f:
            f.write("x")

        app = create_app(db_url=f"sqlite+aiosqlite:///{os.path.join(tmpdir, 'test.db')}")
        async with app.router.lifespan_context(app):
            project = await app.state.tracker.create_project(name="Meu App", repo_path=repo)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test", headers=admin_headers()) as ac:
                res = await ac.get(f"/api/projects/{project.id}/archive")
                assert res.status_code == 200
                assert res.headers["content-type"] == "application/zip"
                assert 'filename="Meu-App-main.zip"' in res.headers["content-disposition"]
                names = zipfile.ZipFile(io.BytesIO(res.content)).namelist()
                assert names == ["app.py"]

                res_bad = await ac.get(f"/api/projects/{project.id}/archive", params={"ref": "nao-existe"})
                assert res_bad.status_code == 409

                res_404 = await ac.get("/api/projects/proj-inexistente/archive")
                assert res_404.status_code == 404
