# Especificação de Design: Cadastro de Usuários, Verificação por E-mail e Configuração SMTP

**Data:** 2026-09-27  
**Status:** Aprovado para Planejamento  

---

## 1. Visão Geral

Esta especificação define o fluxo completo de cadastro de usuários com ativação via verificação por e-mail (código de 6 dígitos ou link direto), login com usuário/e-mail e senha para contas cadastradas, limpeza dos textos legados na tela de login e a adição de uma seção de configuração SMTP no painel administrativo do Painkiller.

---

## 2. Requisitos e Regras de Negócio

### 2.1 Tela de Login (`/login`)
1. **Permanência do Formulário**: O formulário com campos de usuário/e-mail e senha deve ficar **sempre visível**, independente de o Google estar configurado ou não.
2. **Remoção dos Textos Riscados**:
   - Remover o texto de ajuda sob o botão do Google: `login.googleHelp` (*"No primeiro acesso a conta é criada, junto com um usuário no Gitea que só enxerga os seus repositórios."*).
   - Remover o texto de ajuda de emergência sob o botão de login: `login.adminHelp` (*"A conta de administrador, criada no primeiro acesso à plataforma..."*).
3. **Divisor e Ações**:
   - Um divisor sutil (`ou`) entre o botão do Google e os campos de usuário/senha.
   - Dois botões no formulário:
     - **Entrar / Sign in** (ação primária).
     - **Criar Conta / Create Account** (ação secundária, alternando a visão para o formulário de cadastro).
4. **Identificador de Login**:
   - O campo aceita tanto o **E-mail** quanto o **Nome de Usuário** cadastrado (ou `admin` para o break-glass).

### 2.2 Fluxo de Cadastro (`mode = 'register'`)
1. **Campos do Formulário**:
   - Nome (First name)
   - Sobrenome (Last name)
   - E-mail
   - Senha (mínimo de 8 caracteres)
   - Confirmação de Senha
2. **Ações**:
   - Botão de envio: **Cadastrar**
   - Link/botão de retorno: **Já tem uma conta? Entrar**
3. **Comportamento no Envio**:
   - Validações: campos obrigatórios, senhas coincidentes, formato de e-mail válido.
   - Envio para `POST /api/auth/register`.
   - Se o e-mail já estiver cadastrado e ativo: informa que o e-mail já existe.
   - Se o e-mail estiver cadastrado mas ainda não ativado: atualiza os dados, gera novo código/token e reenvia.
   - Ao receber confirmação de sucesso da API, a tela avança para o estado de **Verificação** (`mode = 'verify'`).

### 2.3 Fluxo de Ativação / Verificação (`mode = 'verify'`)
1. **Regra de Ativação**: A conta **não é ativada** no cadastro; ela fica com `is_active = False` até a confirmação do código ou clique no link. Tentativas de login antes da ativação retornam aviso de conta pendente de ativação.
2. **Interface de Verificação**:
   - Exibe mensagem com o e-mail de destino.
   - Campo para digitação do **código de 6 dígitos**.
   - Botão **Confirmar Código**.
   - Botão **Reenviar Código** (com cooldown visual para evitar requisições repetidas).
   - Aviso de que o usuário também pode clicar no link enviado por e-mail.
3. **Ativação por Código**:
   - Requisição para `POST /api/auth/verify-code` enviando `{ email, code }`.
   - Com código válido e dentro do prazo de validade (24 horas), o usuário é marcado como `is_active = True`, `email_verified = True`, o código é invalidado, a conta no Gitea é provisionada (se configurada) e a sessão é autenticada automaticamente redirecionando para `/projects`.
4. **Ativação por Link**:
   - Rota `GET /api/auth/verify-link?token=...`.
   - Valida o token URL-safe de uso único.
   - Ativa a conta e redireciona o usuário autenticado para `/projects` (ou `/login?verified=true`).

### 2.4 Configuração SMTP no Painel do Administrador (`/admin/settings#smtp`)
1. **Nova Seção em Configurações**:
   - Seção intitulada **SMTP / E-mail** na barra lateral de navegação e no corpo de `/admin/settings`.
2. **Campos Configuráveis**:
   - Servidor SMTP (`smtp_host`)
   - Porta SMTP (`smtp_port`, default 587)
   - Usuário SMTP (`smtp_user`)
   - Senha SMTP (`smtp_password`, mascarada e criptografada com `SecretBox`)
   - E-mail Remetente (`smtp_from`, ex: `noreply@painkiller.local`)
   - Usar TLS/STARTTLS (`smtp_tls`, booleano, default True)
3. **Ações**:
   - **Salvar Configurações SMTP** (`PUT /api/setup/smtp`)
   - **Testar Conexão / Enviar E-mail de Teste** (`POST /api/setup/smtp/test` com campo para e-mail de destino do teste)
4. **Fallback de Desenvolvimento**:
   - Quando o SMTP não estiver preenchido ou configurado, o Painkiller opera em modo simulado/local: registra no log do servidor com destaque visual:
     ```
     ========================================================================
     [EMAIL DISPATCH]
     Para: usuario@exemplo.com
     Assunto: Confirme sua conta no Painkiller
     Código: 123456
     Link: http://localhost:8000/api/auth/verify-link?token=...
     ========================================================================
     ```
   - Isso garante que os testes locais e desenvolvimento nunca fiquem bloqueados por falta de infraestrutura SMTP externa.

---

## 3. Arquitetura e Modelagem de Dados

### 3.1 Entidade e Banco de Dados (`painkiller/core/domain/models.py` e `sqlite_tracker.py`)

#### Alterações no modelo `User` e tabela `users` (`UserRecord`):
- `password_hash: Optional[str] = None` — hash com algoritmo `scrypt` padronizado.
- `is_active: bool = True` — falso para recém-cadastrados até a verificação.
- `email_verified: bool = True` — falso para recém-cadastrados até a verificação.
- `verification_code: Optional[str] = None` — código numérico de 6 dígitos (`f"{secrets.randbelow(1_000_000):06d}"`).
- `verification_token: Optional[str] = None` — token aleatório URL-safe de 32 bytes (`secrets.token_urlsafe(32)`).
- `verification_expires_at: Optional[datetime] = None` — validade de 24 horas.

#### Alterações no `PlatformSettings`:
- `smtp_host: Optional[str] = None`
- `smtp_port: Optional[int] = 587`
- `smtp_user: Optional[str] = None`
- `smtp_password: Optional[str] = None` (adicionado à tupla `PLATFORM_SECRET_FIELDS` para criptografia em repouso)
- `smtp_from: Optional[str] = None`
- `smtp_tls: bool = True`

### 3.2 Adaptador de E-mail (`painkiller/adapters/email/smtp_sender.py`)
- Classe `EmailSender` com método assíncrono:
  ```python
  async def send_verification_email(self, to_email: str, name: str, code: str, link: str) -> None
  async def test_connection(self, to_email: str) -> None
  ```
- Lê as configurações de `app.state.platform.settings`.
- Se configurado, conecta via `aiosmtplib` ou `smtplib` em executor thread com STARTTLS / SSL conforme porta.
- Se não configurado, faz o fallback emitindo no log com nível INFO.

### 3.3 Endpoints de Autenticação (`painkiller/api/routes/auth.py`)
- `POST /api/auth/register`: Cadastro inicial.
- `POST /api/auth/verify-code`: Validação do código de 6 dígitos.
- `GET /api/auth/verify-link`: Validação via clique no link.
- `POST /api/auth/resend-code`: Reenvio de código.
- `POST /api/auth/login`: Atualizado para autenticar tanto admin break-glass quanto usuários da tabela `users` (por e-mail ou username) com verificação de `is_active`.

---

## 4. Internacionalização (i18n)

- Textos adicionados em `web/src/lib/i18n/pt-BR.ts` e espelhados em `web/src/lib/i18n/en-US.ts`:
  - `login.createAccount`, `login.orDivider`, `login.backToLogin`
  - `register.title`, `register.firstName`, `register.lastName`, `register.email`, `register.password`, `register.confirmPassword`, `register.submit`, `register.passwordMismatch`, `register.passwordTooShort`
  - `verify.title`, `verify.instruction`, `verify.codeLabel`, `verify.submit`, `verify.resend`, `verify.resendSuccess`, `verify.orClickLink`
  - `adminSettings.smtp`, `setup.smtpHost`, `setup.smtpPort`, `setup.smtpUser`, `setup.smtpPassword`, `setup.smtpFrom`, `setup.smtpTls`, `setup.smtpTest`, `setup.smtpTestSuccess`
- Chaves de erro da API mapeadas em `painkiller/core/i18n.py` (garantindo aprovação em `tests/unit/test_i18n.py`).

---

## 5. Estratégia de Testes

1. **Testes Unitários Backend**:
   - `test_register_user_success`: Criação de usuário pendente, geração de código e token.
   - `test_register_duplicate_active_email`: Rejeição de e-mail já existente.
   - `test_verify_code_success`: Ativação de conta e emissão de token de sessão.
   - `test_verify_code_invalid_or_expired`: Rejeição de código inválido ou expirado.
   - `test_verify_link_success`: Validação via token de link.
   - `test_login_inactive_user`: Falha com mensagem de conta pendente de ativação.
   - `test_login_active_user`: Sucesso no login com e-mail e senha.
   - `test_smtp_settings_save_and_seal`: Salvamento seguro das credenciais SMTP.
   - `test_i18n`: Verificação de cobertura de todas as novas mensagens da API em pt-BR e en-US.
2. **Testes Frontend**:
   - `npm run check` na pasta `web` sem nenhum erro de tipo ou i18n.
