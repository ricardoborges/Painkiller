# Plano de Implementação: Cadastro de Usuários, Verificação por E-mail e Configuração SMTP

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar o fluxo de registro de usuários com ativação via código/link por e-mail, login com e-mail/senha, limpeza da tela de login e configuração de servidor SMTP no painel administrativo.

**Architecture:** Modelagem em banco SQLite com hashing `scrypt` e campos de ativação no modelo de usuário; serviço de envio SMTP com fallback para console log em ambiente de desenvolvimento; endpoints REST em FastAPI para registro, ativação e teste SMTP; e tela de login em SvelteKit com transições reativas entre estados de Login, Cadastro e Verificação.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, SQLite, Pydantic, SvelteKit, TypeScript, vanilla CSS.

**Spec:** [docs/superpowers/specs/2026-09-27-user-registration-and-smtp-design.md](file:///d:/dev/github/Painkiller/docs/superpowers/specs/2026-09-27-user-registration-and-smtp-design.md)

## Global Constraints

- Code comments are in Portuguese (pt-BR); code identifiers, docstrings and URL routes / query params are in English.
- Multi-language UI in `web/src/lib/i18n/` with `pt-BR.ts` and `en-US.ts` kept in strict sync (`npm run check` passes with 0 errors).
- All `HTTPException` detail strings raised in `painkiller/api/` must have corresponding translations in `painkiller/core/i18n.py:EN_US` (`pytest tests/unit/test_i18n.py` passes).
- Platform secrets (`smtp_password`) must be encrypted in storage using `SecretBox` via `PLATFORM_SECRET_FIELDS`.

---

### Task 1: Modelos de Domínio e Persistência no SQLite

**Files:**
- Modify: `painkiller/core/domain/models.py:264-280, 418-452`
- Modify: `painkiller/adapters/issue_trackers/sqlite_tracker.py:83-93, 248-255, 452-500, 974-991`
- Test: `tests/unit/test_user_persistence.py`

**Interfaces:**
- Consumes: `UserRole`, `UserRecord`, `SecretBox`, `PlatformSettings`
- Produces: `User` com campos `is_active`, `email_verified`, `password_hash`, `verification_code`, `verification_token`, `verification_expires_at`; métodos no tracker `get_user_by_email_or_username`, `get_user_by_verification_token`; e campos SMTP em `PlatformSettings`.

- [ ] **Step 1: Escrever teste de falha para persistência de campos de usuário e SMTP**

```python
# tests/unit/test_user_persistence.py
import pytest
from datetime import datetime, timezone, timedelta
from painkiller.core.domain.models import PlatformSettings, User
from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker

@pytest.mark.asyncio
async def test_user_extended_fields(tmp_path):
    db_file = tmp_path / "test.db"
    tracker = SQLiteIssueTracker(f"sqlite+aiosqlite:///{db_file}")
    await tracker.initialize()

    # Criação de usuário com campos de registro e verificação
    user = await tracker.create_user(
        email="test@example.com",
        name="Test User",
        password_hash="scrypt$fakehash",
        is_active=False,
        email_verified=False,
        verification_code="123456",
        verification_token="token-abc-123",
        verification_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    assert user.email == "test@example.com"
    assert user.is_active is False
    assert user.email_verified is False

    # Busca por email ou username
    fetched = await tracker.get_user_by_email_or_username("test@example.com")
    assert fetched is not None
    assert fetched.id == user.id

    # Busca por token de verificação
    by_token = await tracker.get_user_by_verification_token("token-abc-123")
    assert by_token is not None
    assert by_token.id == user.id

    # Atualização de ativação
    updated = await tracker.activate_user(user.id)
    assert updated.is_active is True
    assert updated.email_verified is True
    assert updated.verification_code is None
    assert updated.verification_token is None

@pytest.mark.asyncio
async def test_platform_settings_smtp_fields(tmp_path):
    db_file = tmp_path / "test.db"
    tracker = SQLiteIssueTracker(f"sqlite+aiosqlite:///{db_file}")
    await tracker.initialize()

    settings = PlatformSettings(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="mailer",
        smtp_password="super-secret-password",
        smtp_from="noreply@example.com",
        smtp_tls=True,
    )
    await tracker.save_platform_settings(settings)

    loaded = await tracker.get_platform_settings()
    assert loaded.smtp_host == "smtp.example.com"
    assert loaded.smtp_port == 587
    assert loaded.smtp_password == "super-secret-password"
```

- [ ] **Step 2: Executar teste para verificar que falha**

Run: `pytest tests/unit/test_user_persistence.py -v`  
Expected: FAIL com `TypeError: create_user() got unexpected keyword argument` ou `AttributeError`

- [ ] **Step 3: Implementar alterações em `models.py` e `sqlite_tracker.py`**

Adicionar campos em `User` (`core/domain/models.py`):
```python
    password_hash: Optional[str] = None
    is_active: bool = True
    email_verified: bool = True
    verification_code: Optional[str] = None
    verification_token: Optional[str] = None
    verification_expires_at: Optional[datetime] = None
```
E em `PlatformSettings`:
```python
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_tls: bool = True
```
E em `sqlite_tracker.py`:
- Adicionar colunas correspondentes em `UserRecord`.
- Adicionar `"smtp_password"` em `PLATFORM_SECRET_FIELDS`.
- Implementar `get_user_by_email_or_username`, `get_user_by_verification_token` e `activate_user`.

- [ ] **Step 4: Executar testes de persistência**

Run: `pytest tests/unit/test_user_persistence.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_user_persistence.py painkiller/core/domain/models.py painkiller/adapters/issue_trackers/sqlite_tracker.py
git commit -m "feat: add user verification fields and SMTP platform settings"
```

---

### Task 2: Adaptador de E-mail (SMTP & Dev Logger)

**Files:**
- Create: `painkiller/adapters/email/smtp_sender.py`
- Modify: `painkiller/api/server.py:create_app`
- Test: `tests/unit/test_email_sender.py`

**Interfaces:**
- Consumes: `PlatformSettings`
- Produces: `EmailSender.send_verification_email(to_email, name, code, link)`, `EmailSender.test_connection(to_email)`

- [ ] **Step 1: Escrever teste de falha para EmailSender**

```python
# tests/unit/test_email_sender.py
import pytest
from unittest.mock import AsyncMock, patch
from painkiller.core.domain.models import PlatformSettings
from painkiller.adapters.email.smtp_sender import EmailSender

@pytest.mark.asyncio
async def test_email_sender_fallback_logger(caplog):
    # Sem configurações de SMTP, faz log com código e link
    sender = EmailSender(lambda: PlatformSettings())
    await sender.send_verification_email(
        to_email="test@domain.com",
        name="John Doe",
        code="654321",
        link="http://localhost:8000/api/auth/verify-link?token=xyz",
    )
    assert "654321" in caplog.text
    assert "test@domain.com" in caplog.text
    assert "verify-link?token=xyz" in caplog.text

@pytest.mark.asyncio
async def test_email_sender_smtp_dispatch():
    settings = PlatformSettings(
        smtp_host="smtp.fake.org",
        smtp_port=587,
        smtp_user="user",
        smtp_password="pw",
        smtp_from="noreply@domain.com",
    )
    sender = EmailSender(lambda: settings)
    with patch("painkiller.adapters.email.smtp_sender.send_smtp_message", new_callable=AsyncMock) as mock_send:
        await sender.send_verification_email("to@domain.com", "Name", "123456", "http://link")
        mock_send.assert_awaited_once()
```

- [ ] **Step 2: Executar teste para verificar falha**

Run: `pytest tests/unit/test_email_sender.py -v`  
Expected: FAIL com `ModuleNotFoundError: No module named 'painkiller.adapters.email'`

- [ ] **Step 3: Implementar `painkiller/adapters/email/smtp_sender.py`**

Implementar a classe `EmailSender` com envio assíncrono (usando `smtplib` via `asyncio.to_thread` para não requerer novas dependências externas não declaradas) com fallback de console formatado e seguro.

- [ ] **Step 4: Executar testes de e-mail**

Run: `pytest tests/unit/test_email_sender.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add painkiller/adapters/email/ tests/unit/test_email_sender.py painkiller/api/server.py
git commit -m "feat: add EmailSender with SMTP dispatch and local dev fallback"
```

---

### Task 3: Rotas de Autenticação (`/api/auth`) e i18n no Backend

**Files:**
- Modify: `painkiller/api/routes/auth.py`
- Modify: `painkiller/core/i18n.py`
- Test: `tests/unit/test_auth_registration.py`
- Test: `tests/unit/test_i18n.py`

**Interfaces:**
- Consumes: `EmailSender`, `tracker`, `hash_password`, `verify_password`, `issue_token`, `admin_session`
- Produces: `POST /api/auth/register`, `POST /api/auth/verify-code`, `GET /api/auth/verify-link`, `POST /api/auth/resend-code`, e atualização de `POST /api/auth/login`.

- [ ] **Step 1: Escrever teste de falha para fluxo de registro e login com usuário comum**

```python
# tests/unit/test_auth_registration.py
import pytest
from httpx import AsyncClient, ASGITransport
from painkiller.api.server import create_app

@pytest.mark.asyncio
async def test_registration_and_activation_flow():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Registrar
        resp = await client.post("/api/auth/register", json={
            "first_name": "Ana",
            "last_name": "Silva",
            "email": "ana@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!"
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["email"] == "ana@example.com"
        assert data["status"] == "pending_verification"

        # 2. Tentar login antes de ativar (deve falhar 403)
        login_fail = await client.post("/api/auth/login", json={
            "username": "ana@example.com",
            "password": "Password123!"
        })
        assert login_fail.status_code == 403
        assert "ativada" in login_fail.json()["detail"].lower()

        # Obter código do banco para teste
        tracker = app.state.tracker
        user = await tracker.get_user_by_email_or_username("ana@example.com")
        assert user is not None
        code = user.verification_code
        assert len(code) == 6

        # 3. Confirmar código
        verify_resp = await client.post("/api/auth/verify-code", json={
            "email": "ana@example.com",
            "code": code
        })
        assert verify_resp.status_code == 200
        assert "token" in verify_resp.json()

        # 4. Login após ativação
        login_ok = await client.post("/api/auth/login", json={
            "username": "ana@example.com",
            "password": "Password123!"
        })
        assert login_ok.status_code == 200
        assert "token" in login_ok.json()
```

- [ ] **Step 2: Executar teste para verificar falha**

Run: `pytest tests/unit/test_auth_registration.py -v`  
Expected: FAIL com 404 para `/api/auth/register`

- [ ] **Step 3: Implementar endpoints em `painkiller/api/routes/auth.py` e traduções em `painkiller/core/i18n.py`**

Adicionar modelos Pydantic `RegisterRequest`, `VerifyCodeRequest`, `ResendCodeRequest`.  
Implementar `register`, `verify_code`, `verify_link`, `resend_code`.  
Atualizar `login` para suportar busca de usuário por email/username além de admin break-glass.  
Adicionar todas as mensagens em `painkiller/core/i18n.py:EN_US`.

- [ ] **Step 4: Executar testes de autenticação e de i18n da API**

Run: `pytest tests/unit/test_auth_registration.py tests/unit/test_i18n.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add painkiller/api/routes/auth.py painkiller/core/i18n.py tests/unit/test_auth_registration.py
git commit -m "feat: add registration, activation endpoints and regular user login"
```

---

### Task 4: Endpoints de Configuração SMTP no Setup Admin

**Files:**
- Modify: `painkiller/api/routes/setup.py`
- Modify: `painkiller/core/i18n.py`
- Test: `tests/unit/test_setup_smtp.py`

**Interfaces:**
- Consumes: `PlatformConfig`, `EmailSender`, `require_admin`
- Produces: `PUT /api/setup/smtp`, `POST /api/setup/smtp/test`, e inclusão do status SMTP no retorno de `GET /api/setup`.

- [ ] **Step 1: Escrever teste de falha para rotas SMTP**

```python
# tests/unit/test_setup_smtp.py
import pytest
from httpx import AsyncClient, ASGITransport
from painkiller.api.server import create_app
from painkiller.api.security import issue_token, BREAK_GLASS_ID, break_glass_fingerprint

@pytest.mark.asyncio
async def test_setup_smtp_save_and_state():
    app = create_app()
    admin_token = issue_token(BREAK_GLASS_ID, pw=break_glass_fingerprint())
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Salvar configuração SMTP
        resp = await client.put("/api/setup/smtp", headers=headers, json={
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_user": "admin@gmail.com",
            "smtp_password": "mypassword123",
            "smtp_from": "no-reply@painkiller.io",
            "smtp_tls": True
        })
        assert resp.status_code == 200, resp.text
        state = resp.json()
        assert state["smtp"]["smtp_host"] == "smtp.gmail.com"
        assert state["smtp"]["smtp_password_set"] is True
```

- [ ] **Step 2: Executar teste para verificar falha**

Run: `pytest tests/unit/test_setup_smtp.py -v`  
Expected: FAIL com 404 para `/api/setup/smtp`

- [ ] **Step 3: Implementar rotas em `painkiller/api/routes/setup.py`**

Adicionar `SmtpRequest`, `SmtpTestRequest`, endpoint `save_smtp`, `test_smtp`, e expor `smtp` no dicionário `_state`. Adicionar mensagens traduzidas em `painkiller/core/i18n.py`.

- [ ] **Step 4: Executar testes de setup SMTP e i18n**

Run: `pytest tests/unit/test_setup_smtp.py tests/unit/test_i18n.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add painkiller/api/routes/setup.py painkiller/core/i18n.py tests/unit/test_setup_smtp.py
git commit -m "feat: add admin setup routes for SMTP configuration and test"
```

---

### Task 5: Tipagens, Chaves de Tradução e Cliente API no Frontend

**Files:**
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/lib/i18n/pt-BR.ts`
- Modify: `web/src/lib/i18n/en-US.ts`
- Test: `npm run check` (em `web/`)

**Interfaces:**
- Consumes: Tipos de setup e auth
- Produces: Métodos `api.register`, `api.verifyCode`, `api.resendCode`, `api.saveSmtp`, `api.testSmtp` e todas as strings de i18n correspondentes.

- [ ] **Step 1: Adicionar tipos em `web/src/lib/types.ts`**

Adicionar tipos `RegisterData`, `VerifyCodeData`, `SmtpConfig`, etc.

- [ ] **Step 2: Adicionar métodos em `web/src/lib/api.ts`**

Adicionar chamadas tipadas para os novos endpoints da API.

- [ ] **Step 3: Adicionar chaves em `pt-BR.ts` e `en-US.ts`**

Adicionar todas as chaves de tela:
- `login.createAccount`, `login.orDivider`, `login.backToLogin`
- `register.*` (nome, sobrenome, email, senhas, etc.)
- `verify.*` (código de verificação, reenviar, etc.)
- `setup.smtp*` e `adminSettings.smtp`

- [ ] **Step 4: Executar verificação de tipos**

Run: `powershell -Command "cd web; npm run check"`  
Expected: 0 errors, 0 warnings

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/types.ts web/src/lib/api.ts web/src/lib/i18n/
git commit -m "feat: add frontend types, api methods and i18n keys for registration and SMTP"
```

---

### Task 6: Atualização da Tela de Login e Fluxo de Cadastro/Verificação

**Files:**
- Modify: `web/src/routes/login/+page.svelte`
- Test: `npm run check` e teste de interface

**Interfaces:**
- Consumes: `api.register`, `api.verifyCode`, `api.resendCode`, `auth.signIn`, traduções `t`
- Produces: Tela de login com formulário de usuário/senha permanentemente visível, botão "Criar Conta", modo de formulário de cadastro, modo de confirmação de código e remoção dos textos riscados.

- [ ] **Step 1: Atualizar `web/src/routes/login/+page.svelte`**

1. Remover `<p class="help">{t('login.googleHelp')}</p>`.
2. Remover `<p class="help">{@html t('login.adminHelp')}</p>`.
3. Manter formulário de usuário e senha sempre visível:
   - Adicionar divisor visual `ou` caso Google esteja ativo.
   - Botão "Sign in" e botão "Create Account".
4. Adicionar estado reativo `mode = 'login' | 'register' | 'verify'`.
5. Implementar formulário de cadastro com Nome, Sobrenome, E-mail, Senha e Confirmação de Senha.
6. Implementar formulário de verificação com campo de código de 6 dígitos, reenvio e suporte a ativação direta se vier hash/query `token`.

- [ ] **Step 2: Executar checagem de tipos do SvelteKit**

Run: `powershell -Command "cd web; npm run check"`  
Expected: 0 errors

- [ ] **Step 3: Commit**

```bash
git add web/src/routes/login/+page.svelte
git commit -m "feat: update login screen with registration and verification flow"
```

---

### Task 7: Seção de Configuração SMTP no Painel do Administrador

**Files:**
- Create: `web/src/lib/components/setup/SmtpStep.svelte`
- Modify: `web/src/routes/admin/settings/+page.svelte`
- Test: `npm run check`

**Interfaces:**
- Consumes: `setup.state.smtp`, `api.saveSmtp`, `api.testSmtp`
- Produces: Seção visual de SMTP em `/admin/settings#smtp` com campos, validação e botão de teste.

- [ ] **Step 1: Criar `web/src/lib/components/setup/SmtpStep.svelte`**

Campos:
- Host SMTP
- Porta SMTP
- Usuário SMTP
- Senha SMTP (com placeholder indicando se já está configurada)
- Remetente (From)
- Checkbox Usar TLS
- Botão "Salvar Configurações"
- Seção de Teste de Envio: campo para e-mail destinatário e botão "Enviar E-mail de Teste"

- [ ] **Step 2: Integrar em `web/src/routes/admin/settings/+page.svelte`**

Adicionar `{ id: 'smtp', title: 'SMTP / E-mail' }` ao `SECTIONS` e renderizar `<SmtpStep />`.

- [ ] **Step 3: Executar checagem de tipos**

Run: `powershell -Command "cd web; npm run check"`  
Expected: 0 errors

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/components/setup/SmtpStep.svelte web/src/routes/admin/settings/+page.svelte
git commit -m "feat: add SMTP configuration section to admin settings"
```

---

### Task 8: Verificação Final End-to-End e Build da Aplicação

**Files:**
- Modify: `painkiller/api/static/*` (gerado por `npm run build`)
- Test: Suíte completa `pytest` e `npm run check`

- [ ] **Step 1: Rodar a suíte completa de testes no Python**

Run: `pytest`  
Expected: Todos os testes passando sem erros.

- [ ] **Step 2: Rodar build do frontend para atualizar estáticos servidos pelo FastAPI**

Run: `powershell -Command "cd web; npm run build"`  
Expected: Build concluído com sucesso gerando estáticos em `painkiller/api/static`.

- [ ] **Step 3: Commit final dos estáticos e ajustes**

```bash
git add painkiller/api/static/
git commit -m "chore: build and bundle updated web SPA into static directory"
```
