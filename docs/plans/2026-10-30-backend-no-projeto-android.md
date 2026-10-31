# Plano: backend no mesmo projeto do app Android

## Objetivo

Um projeto Android pode ganhar um backend que nasce e evolui pelo mesmo fluxo
(análise → backlog → tarefas → merge), no mesmo repositório. Esse backend guarda
os segredos do app (chaves de API pagas, credenciais), serve dados compartilhados
e é publicado no Coolify. O app só conhece a URL dele.

Decisões já tomadas:

- **Um repositório, um projeto.** O app fica na raiz, como hoje; o backend vive em
  `backend/`. Nada do que já detecta o Capacitor (`test_plan`, `apk`, `preview`) muda de lugar.
- **O backend é opcional e o repo decide.** "O projeto tem backend" quer dizer "existe
  `backend/Dockerfile`", sem flag no banco, como a verificação, que segue o repo e não o template.
- **Stack fixa: FastAPI (Python).** O pytest em `backend/tests` e o `uv` nos workers já existem.
- **Segredo de verdade nunca vai para o APK.** Só a config pública (`VITE_*`) entra no bundle.

Cada etapa pode ser entregue sozinha, nesta ordem.

---

## Etapa 1: Scaffold e estrutura

**Novo:** `painkiller/scaffolds/backend-fastapi/`, que será copiado para `backend/`:

- `app/main.py`: FastAPI com `GET /health`, CORS configurável por `CORS_ORIGINS`
  (padrão `*`, porque o preview roda com origem opaca, `Origin: null`) e o esqueleto de um
  middleware de autenticação ou limite de requisições (ver Etapa 6).
- `tests/test_health.py`, `requirements.txt` (fastapi, uvicorn, httpx, pytest).
- `Dockerfile` (python:3.13-slim, `uvicorn app.main:app --host 0.0.0.0 --port 8000`).
- `.env.example` vazio, com um comentário sobre segredos.

**Novo:** `painkiller/core/backend.py`

- `BACKEND_DIR = "backend"`, `has_backend(repo_path)`.
- `apply_backend_scaffold(repo_path)`: reutiliza `copy_scaffold_dir` de `core/scaffold.py`
  e recusa se `backend/` já existir.

**Como o backend nasce** (dois caminhos, mesmo código):

1. **Pela análise:** o JSON do backlog ganha um campo de topo opcional, `"backend": true`.
   `POST /api/analysis/{sid}/commit` aplica o scaffold no branch padrão antes de importar
   as tarefas (commit + push), se `backend/` ainda não existir.
2. **Manual:** `POST /api/projects/{id}/backend` ("Adicionar backend" no painel). Recusa
   com 409 se já existir, se houver tarefa `RUNNING` (a árvore de trabalho pode estar num
   `feature/`) ou se o template for Kotlin nativo.

Para trocar de branch e commitar com segurança, seguir `_ensure_default_branch` da análise.

**Testes:** `test_backend_scaffold.py` (cópia, recusa duplicada) e as rotas (commit com
`backend: true`, 409 com tarefa rodando).

---

## Etapa 2: Verificação pós-tarefa

`core/test_plan.py`, em `build_capacitor_script`:

- Hoje o script termina em `exit 0` (quando `android/` não mudou) ou num `exec gradlew`. O
  bloco do backend tem que vir **antes** da decisão nativa.
- Novo trecho: se `backend/` existe e o diff contra o branch padrão (mais os não rastreados)
  toca `^backend/`, ou se não há base para comparar, roda `cd backend`, `_install_deps`
  e `pytest`. Exit 5 (nenhum teste coletado) não reprova, como já acontece hoje.
- Uma tarefa que só mexe no backend continua rodando `npm test` e `npm run build`. É barato,
  e o app pode depender de um tipo compartilhado.

O bloco "Ambiente" (`ENVIRONMENT_NOTES` em `engine/orchestrator.py`) ganha um complemento
anexado só quando `has_backend(repo_path)`: estrutura de `backend/`, comandos de validação,
"não crie outro servidor, não mude a porta", "segredos chegam como variáveis de ambiente,
nunca escreva valores".

**Testes:** `test_test_plan.py` (o script contém o pytest de `backend/` antes do `exit 0`;
sem `backend/`, o script fica igual ao de hoje).

---

## Etapa 3: Deploy do backend no Coolify (feita)

Decisão: **dois apps no Coolify**. O app web continua `{slug}-{env}`, como antes, e o
backend vira `{slug}-api-{env}`.

- `DeploymentRecord.component` (`app` | `backend`), com coluna nova; registros antigos
  contam como `app`. `get_latest_deployment` filtra por componente.
- O backend é criado com `build_pack=dockerfile`, `base_directory=/backend` e porta 8000,
  realinhados no PATCH de cada deploy. Não há health check do Coolify: ele roda curl/wget
  dentro do contêiner, e a imagem python-slim não tem nenhum dos dois.
- `POST /deploy` aceita `component` e responde 409 se o projeto não tiver `backend/`.
  `deployments/status` traz `backend: {test, production}`. As URLs do projeto continuam
  sendo as do app.
- UI: o "Testar" do backlog publica os dois. O painel mostra "Backend · teste" e
  "Backend · produção" (produção sempre a partir do branch padrão).
- Mixed content, decisão: `allowMixedContent` **só no APK debug**. Depois do
  `cap sync`, o build debug (num clone em `/tmp/src`) liga `android.allowMixedContent` e
  escreve um `AndroidManifest.xml` de debug com `usesCleartextTraffic`. O release não recebe
  nenhum dos dois, e na Etapa 4 passa a exigir uma URL https de produção.

---

## Etapa 4: URL do backend nos builds (feita)

Como a regra do https no release seria impossível de cumprir com o `http://` fixo, o domínio
curinga do Coolify agora aceita `https://` na frente (`split_wildcard`). Com isso, todos os
hosts gerados saem em https, e o Coolify emite os certificados.

Variável única: **`VITE_API_URL`**. O app lê `import.meta.env.VITE_API_URL` e nunca tem
endereço fixo no código.

| Build | Onde | `VITE_API_URL` |
|---|---|---|
| Verificação pós-tarefa | `run_tests` | URL de teste (`environment_url(TEST)`) |
| Preview no celular simulado | mesmo script | URL de teste |
| APK debug | `build_apk` | URL de teste |
| APK release | `build_apk` | URL de produção |

- `SandboxPort.run_tests` e `build_apk` ganham `extra_env: dict[str, str] | None = None`.
  Atualizar o adapter e os `AsyncMock` dos testes.
- O orquestrador (`run_tests`) e o `ApkBuildService` montam o `extra_env`, que a Etapa 5
  depois completa com os segredos `app`.
- APK release de um projeto com backend: recusa com 409 se não houver deploy de produção
  `HEALTHY` ou se a URL não for https. A mensagem é em pt-BR, com entrada no `EN_US`.

**Testes:** o `extra_env` chega ao contêiner (mock do docker) e a recusa do release.

---

## Etapa 5: Segredos do projeto (feita)

Na implementação, o escopo é deduzido do nome (a UI não tem seletor). O app web publicado em
teste no Coolify também recebe os `VITE_*` e o `VITE_API_URL`, já que o build do Vite os embute.

**Domínio e porta:** `ProjectSecret(name, scope: "app" | "server", updated_at)`, com o valor
fora do modelo. Novo `ProjectSecretsPort` (`list_secrets`, `get_secret_values(scope)`,
`put_secret`, `delete_secret`, `delete_project_secrets`), implementado por
`SQLiteIssueTracker`: tabela `project_secrets`, valor cifrado com `secret_box` (Fernet,
a mesma chave da instalação).

**Regras de nome:** `^[A-Z][A-Z0-9_]*$`. Escopo `app` exige o prefixo `VITE_`; escopo
`server` o proíbe. Assim o nome já diz para onde o valor vai.

**API:** `GET /api/projects/{id}/secrets` devolve nomes, escopo e data, **nunca valores**.
`PUT /api/projects/{id}/secrets/{name}` grava valor e escopo; `DELETE` remove. Mesmo
`require_project` das outras rotas. `delete_project` apaga os segredos.

**Para onde vai cada escopo:**
- `app`: entra no `extra_env` da verificação, do preview e do APK (Etapa 4). A UI avisa que
  esse valor fica legível dentro do APK e no preview.
- `server`: antes de cada deploy, `DeploymentService` envia as variáveis para a aplicação no
  Coolify (`PATCH /applications/{uuid}/envs/bulk`). No começo é um valor só para teste e
  produção; separar por ambiente fica para depois, se alguém pedir.
- **Nunca** no contêiner do agente nem no da análise.

**O agente só vê nomes:** `_build_task_instructions` e `build_analysis_prompt` listam os
segredos existentes ("disponível como `X` em tempo de execução/build; use `.env.example`;
nunca escreva valores nem peça valores ao analista").

**Redação:** os valores conhecidos do projeto são trocados por `***` antes de persistir
`Task.error`, comentários (`add_comment`, que também chega ao Gitea) e eventos do
`TaskActivityHub`. Ponto único: um helper `redact(text, values)` chamado no orquestrador.

**UI:** seção "Segredos" na edição do projeto. Lista com escopo, data e "Substituir"/"Excluir";
o valor não pode ser lido de volta. i18n nos dois locales.

**Testes:** valor cifrado no banco, GET sem valores, validação de nome × escopo, redação,
nada de segredo no ambiente do `DockerAgentSession` nem do `run_task`, envio ao Coolify.

---

## Etapa 6: Análise e diretrizes (feita)

Além do previsto, saiu do prompt da análise a instrução de criar um Dockerfile na raiz, que sobrou
da edição generalista.

- `PLATFORM_NOTES` (`engine/analysis.py`): quando propor backend (chave paga ou secreta,
  dados compartilhados entre usuários, autenticação, lógica que não pode ficar no aparelho),
  a stack fixa, e o campo `"backend": true` no JSON do backlog. Se o projeto já tem backend,
  dizer isso e não propor outro.
- Diretrizes fixas do backend (no complemento do Ambiente da Etapa 2): um proxy aberto é um
  relay grátis para a chave do analista, então toda rota que gasta a chave exige autenticação
  do usuário do app ou, no mínimo, limite de requisições por IP/dispositivo. O CORS fica
  restrito em produção, exceto pela origem do app (`https://localhost`).
- Atualizar o `CLAUDE.md`: estrutura `backend/`, verificação, deploy, `VITE_API_URL`, segredos.

---

## Fora deste plano

- Banco de dados gerenciado para o backend (Postgres no Coolify). Até lá, SQLite em volume
  do Coolify, se o agente precisar.
- Valores de segredo diferentes por ambiente.
- Backend para o template Kotlin nativo (inativo).
