"""Idioma das mensagens que o Painkiller mostra a pessoas.

O texto-fonte é pt-BR, escrito direto no código como sempre foi; este módulo
só sabe traduzi-lo. Dois idiomas existem: ``pt-BR`` (padrão) e ``en-US``.

- **API**: o idioma da requisição (``?lang=`` ou ``Accept-Language``) fica num
  ``ContextVar`` posto pelo middleware do servidor, e um handler de
  ``HTTPException`` passa o ``detail`` por :func:`translate`. Por isso as
  rotas continuam levantando a mensagem em português, inclusive o
  ``str(e)`` que vem do engine.
- **Agentes**: o projeto tem o próprio idioma (``Project.language``); o que é
  escrito para o agente ou gravado em nome dele usa :func:`use_locale` com
  esse valor.

Uma entrada do catálogo pode ter ``{nome}``: vira um padrão que casa com o
texto já formatado, e o valor capturado é reposto na tradução. Texto sem
entrada passa inalterado — traduzir é melhoria, nunca requisito.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Iterator, Optional

DEFAULT_LOCALE = "pt-BR"
SUPPORTED_LOCALES = ("pt-BR", "en-US")

_locale: ContextVar[str] = ContextVar("painkiller_locale", default=DEFAULT_LOCALE)


def normalize_locale(value: Optional[str]) -> Optional[str]:
    """Casa "en", "en-GB", "pt_PT"… com um idioma suportado; None se nenhum."""
    if not value or not isinstance(value, str):
        return None
    lang = value.strip().replace("_", "-").split("-")[0].lower()
    if lang == "pt":
        return "pt-BR"
    if lang == "en":
        return "en-US"
    return None


def parse_accept_language(header: Optional[str]) -> Optional[str]:
    """O primeiro idioma suportado de um Accept-Language, respeitando o peso q."""
    if not header:
        return None
    ranked: list[tuple[float, int, str]] = []
    for index, part in enumerate(header.split(",")):
        pieces = part.strip().split(";")
        weight = 1.0
        for param in pieces[1:]:
            name, _, raw = param.strip().partition("=")
            if name == "q":
                try:
                    weight = float(raw)
                except ValueError:
                    weight = 0.0
        ranked.append((-weight, index, pieces[0]))
    for _, _, tag in sorted(ranked):
        locale = normalize_locale(tag)
        if locale:
            return locale
    return None


def project_language(project: object) -> str:
    """Idioma do agente de um projeto (ou do que se passar por um, nos testes)."""
    value = getattr(project, "language", None)
    return value if value in SUPPORTED_LOCALES else DEFAULT_LOCALE


def get_locale() -> str:
    return _locale.get()


def set_locale(locale: Optional[str]):
    """Define o idioma do contexto atual; devolve o token para ``reset_locale``."""
    return _locale.set(normalize_locale(locale) or DEFAULT_LOCALE)


def reset_locale(token) -> None:
    _locale.reset(token)


@contextmanager
def use_locale(locale: Optional[str]) -> Iterator[str]:
    token = set_locale(locale)
    try:
        yield _locale.get()
    finally:
        _locale.reset(token)


def tr(message: str, locale: Optional[str] = None, **params: object) -> str:
    """Traduz o texto-fonte pt-BR e só então o formata com ``params``."""
    target = normalize_locale(locale) or get_locale()
    template = EN_US.get(message, message) if target == "en-US" else message
    return template.format(**params) if params else template


@lru_cache(maxsize=None)
def _patterns() -> list[tuple[re.Pattern[str], str]]:
    compiled = []
    # Mais longos primeiro: o padrão mais específico ganha.
    for source in sorted((k for k in EN_US if "{" in k), key=len, reverse=True):
        regex = re.escape(source)
        regex = re.sub(r"\\\{(\w+)\\\}", lambda m: f"(?P<{m.group(1)}>.*?)", regex)
        compiled.append((re.compile(f"^{regex}$", re.S), EN_US[source]))
    return compiled


def translate(text: object, locale: Optional[str] = None) -> object:
    """Traduz um texto já formatado (ex.: ``detail`` de erro). Não-texto passa direto."""
    if not isinstance(text, str):
        return text
    target = normalize_locale(locale) or get_locale()
    if target != "en-US" or not text:
        return text
    exact = EN_US.get(text)
    if exact is not None and "{" not in text:
        return exact
    for pattern, template in _patterns():
        match = pattern.match(text)
        if match:
            values = {k: translate(v, target) for k, v in match.groupdict().items()}
            return template.format(**values)
    return text


#: pt-BR (fonte) → en-US. Toda mensagem que chega a uma pessoa pela API tem de
#: estar aqui; ``tests/unit/test_i18n.py`` confere as do código.
EN_US: dict[str, str] = {
    # ---- autenticação e acesso ----
    "Sessão inválida ou expirada": "Invalid or expired session",
    "Usuário ou senha incorretos": "Wrong username or password",
    "O primeiro acesso já foi feito. Entre com o administrador.":
        "First access has already been done. Sign in as the administrator.",
    "Login com Google não está configurado": "Google sign-in is not configured",
    "Apenas o administrador pode fazer isso": "Only the administrator can do this",
    "O usuário precisa ter de 1 a 64 caracteres, sem espaços.":
        "The username must have 1 to 64 characters, without spaces.",
    "A senha precisa ter pelo menos {count} caracteres.":
        "The password needs at least {count} characters.",
    "A senha atual não confere.": "The current password does not match.",
    # ---- recursos não encontrados ----
    "Projeto não encontrado": "Project not found",
    "Projeto {id} não encontrado": "Project {id} not found",
    "Sessão não encontrada": "Session not found",
    "Tarefa não encontrada": "Task not found",
    "Nenhuma pendência de esclarecimento para esta tarefa": "No pending clarification for this task",
    "Sessão {id} não encontrada": "Session {id} not found",
    "Sessão {id} não está ativa": "Session {id} is not active",
    "Sessão de análise não encontrada": "Analysis session not found",
    "Template não encontrado": "Template not found",
    "Arquivo de skill não encontrado": "Skill file not found",
    "Arquivo de arcabouço não encontrado": "Scaffold file not found",
    "Deploy não encontrado": "Deploy not found",
    "Documento não encontrado": "Document not found",
    "Repositório local não encontrado": "Local repository not found",
    # ---- projetos ----
    "Esforço inválido. Use um de: {levels}.": "Invalid effort. Use one of: {levels}.",
    "Idioma inválido. Use um de: {locales}.": "Invalid language. Use one of: {locales}.",
    "Só o administrador pode escolher o caminho do repositório":
        "Only the administrator can choose the repository path",
    "Informe a chave de API {provider} do projeto.": "Enter the project's {provider} API key.",
    "Este harness usa outro provedor: informe a chave de API {provider}.":
        "This harness uses another provider: enter the {provider} API key.",
    "Espelhamento de issues não está configurado": "Issue mirroring is not configured",
    "Acesso restrito ao repositório do projeto": "Access restricted to the project's repository",
    "Erro ao ler arquivo: {error}": "Error reading file: {error}",
    "Referência inválida": "Invalid reference",
    "Não foi possível gerar o zip de '{target}': {error}": "Could not build the zip of '{target}': {error}",
    "Este projeto não tem chave de API cadastrada. Abra Editar projeto e informe a chave "
    "do provedor do harness antes de despachar tarefas.":
        "This project has no API key. Open Edit project and enter the harness provider's key "
        "before dispatching tasks.",
    "Este projeto não tem chave de API cadastrada. Abra Editar projeto e informe a chave "
    "do provedor do harness antes de iniciar o agente.":
        "This project has no API key. Open Edit project and enter the harness provider's key "
        "before starting the agent.",
    # ---- templates ----
    "A skill deve ser um arquivo .zip ou .md": "The skill must be a .zip or .md file",
    "O arcabouço da aplicação deve ser um arquivo .zip": "The application scaffold must be a .zip file",
    # ---- análise ----
    "Falha ao iniciar o agente: {error}": "Failed to start the agent: {error}",
    "Mensagem vazia": "Empty message",
    "Arquivo maior que 20 MB": "File larger than 20 MB",
    "Backlog inválido: {error}": "Invalid backlog: {error}",
    "A sessão não tem repositório para receber o anexo.":
        "The session has no repository to receive the attachment.",
    "O agente ainda não gravou {path}. Conclua a análise e peça a ele para registrar o backlog antes de importar.":
        "The agent has not written {path} yet. Finish the analysis and ask it to record the backlog before importing.",
    "A imagem do agente '{image}' não foi encontrada no Docker. "
    "Construa as imagens dos harnesses com: docker compose --profile build build":
        "The agent image '{image}' was not found in Docker. "
        "Build the harness images with: docker compose --profile build build",
    # ---- tarefas ----
    "A tarefa já foi concluída.": "The task is already completed.",
    "Falha ao realizar merge da branch {branch} na {base}: {output}":
        "Failed to merge branch {branch} into {base}: {output}",
    # ---- deploys ----
    "Erro ao disparar deploy: {error}": "Error triggering the deploy: {error}",
    "A sessão desta tarefa foi finalizada e as branches dela foram apagadas "
    "após o merge. Só as tarefas da sessão atual podem ser testadas.":
        "This task's session was finalized and its branches were deleted after the merge. "
        "Only tasks of the current session can be tested.",
    "Não foi possível enviar a branch {branch} ao Gitea antes do deploy: {output}":
        "Could not push branch {branch} to Gitea before the deploy: {output}",
    "Falha ao registrar chave SSH no Coolify: {error}": "Failed to register the SSH key in Coolify: {error}",
    # ---- setup ----
    "A URL pública precisa começar com http:// ou https://.":
        "The public URL must start with http:// or https://.",
    "A validade da sessão vai de 1 hora a 30 dias (720 h).":
        "The session lifetime ranges from 1 hour to 30 days (720 h).",
    "Não foi possível gravar em {path}: {error}": "Could not write to {path}: {error}",
    "Nenhuma imagem de harness construída. Rode `docker compose --profile build build`.":
        "No harness image built. Run `docker compose --profile build build`.",
    "O contêiner de teste não conseguiu montar a pasta: {error}":
        "The test container could not mount the folder: {error}",
    "O contêiner montou {source}, mas a pasta não é a mesma. Confira o caminho no host.":
        "The container mounted {source}, but it is not the same folder. Check the host path.",
    "Os agentes enxergam {source} como /workspace.": "Agents see {source} as /workspace.",
    "O Client ID do Google termina em .apps.googleusercontent.com. Confira o valor copiado.":
        "The Google Client ID ends in .apps.googleusercontent.com. Check the copied value.",
    "Informe também o Client secret.": "Also enter the Client secret.",
    "Não foi possível inspecionar o Coolify: {error}": "Could not inspect Coolify: {error}",
    "O Coolify não aceitou o token.": "Coolify did not accept the token.",
    "Nenhuma conta do Coolify foi criada pelo Painkiller.": "No Coolify account was created by Painkiller.",
    "Esta etapa não pode ser pulada.": "This step cannot be skipped.",
    "Coolify inacessível em {url}: {error}": "Coolify unreachable at {url}: {error}",
    "A API do Coolify está desligada (Settings → Advanced → API Access).":
        "The Coolify API is disabled (Settings → Advanced → API Access).",
    "O Coolify não devolveu resultado: {output}": "Coolify returned no result: {output}",
    "Contêiner {name} não encontrado. Suba o Coolify com `docker compose up -d`.":
        "Container {name} not found. Start Coolify with `docker compose up -d`.",
    "O contêiner {name} não está rodando ({status}).": "Container {name} is not running ({status}).",
    "O Coolify recusou a automação (código {code}): {output}":
        "Coolify refused the automation (code {code}): {output}",
    "O Coolify não emitiu o token.": "Coolify did not issue the token.",
    # ---- erros dos harnesses (gravados na sessão, no idioma do projeto) ----
    "A conta DeepSeek está sem saldo. Recarregue os créditos em "
    "platform.deepseek.com ou troque a chave de API do projeto.":
        "The DeepSeek account is out of balance. Top up the credits at "
        "platform.deepseek.com or change the project's API key.",
    "A DeepSeek recusou a chave de API. Confira a chave do projeto em Editar projeto.":
        "DeepSeek refused the API key. Check the project's key in Edit project.",
    "A chave Gemini excedeu a cota (limite de uso ou de faturamento). Confira o "
    "faturamento em aistudio.google.com ou troque a chave de API do projeto.":
        "The Gemini key exceeded its quota (usage or billing limit). Check billing at "
        "aistudio.google.com or change the project's API key.",
    "O Google recusou a chave Gemini. Confira a chave do projeto em Editar projeto.":
        "Google refused the Gemini key. Check the project's key in Edit project.",
    "O agente falhou: {detail}": "The agent failed: {detail}",
    "Sem adapter Coolify.": "No Coolify adapter.",
    # ---- execução de tarefas (gravado na tarefa, no idioma do projeto) ----
    "Não foi possível enviar a branch {branch} ao Gitea: {output}":
        "Could not push branch {branch} to Gitea: {output}",
    "Reiniciando o agente sem testes, a pedido do analista":
        "Restarting the agent without tests, as the analyst asked",
    "Iniciando contêiner na branch {branch}": "Starting container on branch {branch}",
    "Agente encerrou com código {code}": "Agent exited with code {code}",
    "🤖 Pausada para esclarecimento: {question}": "🤖 Paused for clarification: {question}",
    "Testes abreviados pelo analista: suíte não executada": "Tests skipped by the analyst: suite not run",
    "Executando a suíte de testes do repositório": "Running the repository's test suite",
    "Incorporando branch na {branch}": "Merging branch into {branch}",
    "✅ Tarefa concluída, testada e incorporada na {branch}.": "✅ Task completed, tested and merged into {branch}.",
    "Testes abreviados pelo analista: o teste manual fica por conta dele.":
        "Tests skipped by the analyst: manual testing is on them.",
    "(Sem testes coletados no repositório)": "(No tests collected in the repository)",
    "Falha ao realizar merge na {branch}:": "Failed to merge into {branch}:",
    "❌ Falha no auto-merge da branch {branch} na {base}:": "❌ Auto-merge of branch {branch} into {base} failed:",
    "❌ Os testes falharam depois da execução do agente:": "❌ Tests failed after the agent run:",
    "Final do log do agente:": "End of the agent log:",
    "💬 O analista respondeu: {answer}": "💬 The analyst answered: {answer}",
    "Interrompendo execução da tarefa a pedido do usuário": "Stopping the task run at the user's request",
    "⏩ Testes abreviados: o analista assume o teste manual e os riscos.":
        "⏩ Tests skipped: the analyst takes on manual testing and the risks.",
    "Testes abreviados pelo analista: reiniciando o agente sem testes":
        "Tests skipped by the analyst: restarting the agent without tests",
    "Execução interrompida pelo usuário. O trabalho parcial ficou na branch {branch}: "
    "use Repetir para continuar de onde parou.":
        "Run stopped by the user. The partial work is on branch {branch}: "
        "use Retry to continue where it stopped.",
    "O agente excedeu o tempo limite de {minutes} min e o contêiner foi encerrado. "
    "O trabalho parcial ficou na branch {branch}: use Repetir para continuar de onde parou "
    "ou aumente PAINKILLER_TASK_TIMEOUT.":
        "The agent exceeded the {minutes} min time limit and the container was killed. "
        "The partial work is on branch {branch}: use Retry to continue where it stopped "
        "or raise PAINKILLER_TASK_TIMEOUT.",
    "O agente encerrou com código {code}.": "The agent exited with code {code}.",
    "Última mensagem do agente:": "Agent's last message:",
    "🚀 Tarefa aprovada e incorporada na branch principal ({branch}).":
        "🚀 Task approved and merged into the main branch ({branch}).",
    # ---- custos e chaves ----
    "Moeda local inválida. Use um código como BRL.": "Invalid local currency. Use a code such as USD.",
    "Não foi possível consultar o saldo: {error}": "Could not fetch the balance: {error}",
    "Validação não suportada para {provider}.": "Validation not supported for {provider}.",
    "Não foi possível falar com o provedor: {error}": "Could not reach the provider: {error}",
    "O provedor respondeu HTTP {status}; a chave não foi confirmada.":
        "The provider answered HTTP {status}; the key was not confirmed.",
    "Informe a chave de API.": "Enter the API key.",
    "{provider} recusou a chave (HTTP {status}).": "{provider} refused the key (HTTP {status}).",
    # ---- registro e autenticação ----
    "Todos os campos são obrigatórios.": "All fields are required.",
    "Formato de e-mail inválido.": "Invalid email format.",
    "As senhas não coincidem.": "Passwords do not match.",
    "A senha deve ter pelo menos 8 caracteres.": "Password must be at least 8 characters.",
    "Este e-mail já está cadastrado.": "This email is already registered.",
    "Usuário não encontrado.": "User not found.",
    "Código de verificação incorreto.": "Incorrect verification code.",
    "Código de verificação expirado.": "Verification code expired.",
    "Esta conta já está ativada.": "This account is already active.",
    "Sua conta ainda não foi ativada. Verifique o código enviado ao seu e-mail.":
        "Your account has not been activated yet. Please check the code sent to your email.",
}
