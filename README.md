# Painkiller

Plataforma para uma pessoa **sem formação técnica** descrever o software que
precisa e recebê-lo pronto e **publicado em produção**. Por baixo, agentes de
código trabalham em contêineres Docker; por cima, a pessoa só conversa, aprova
e clica em "Construir e publicar".

## O fluxo, do começo ao fim

1. **Descrever.** A pessoa cria um projeto com três campos em linguagem
   natural (descrição, propósito, solução desejada) e, se quiser, anexa
   documentos.
2. **Conversar.** "Iniciar análise" sobe um agente (Antigravity CLI +
   [superpowers](https://github.com/obra/superpowers) `brainstorming` +
   Gemini) que entrevista a pessoa em português simples, uma pergunta por vez,
   e toma as decisões técnicas sozinho. Ao aprovar a especificação, o agente
   grava o spec em `docs/superpowers/specs/` e o backlog decomposto em
   `.painkiller/backlog.json`, já com porta e forma de build para o deploy.
3. **Construir.** Cada tarefa vai para um agente de codificação isolado
   (Aider) em um contêiner efêmero, numa branch própria. A tarefa é verificada
   pelos testes do repositório (detectados automaticamente) e, se passar, é
   incorporada à branch principal. Se o agente tiver uma dúvida, ele pausa
   (`painkiller ask`, código de saída 42) e a pergunta aparece na interface; a
   resposta entra no prompt da reexecução.
4. **Publicar.** Ao fim do backlog, o piloto automático envia a branch
   principal ao **Coolify**, que constrói a imagem e coloca a aplicação no ar.
   Cada merge posterior gera um novo deploy.

## Rodando

```bash
cp .env.example .env            # preencha GEMINI_API_KEY, a chave do LLM do Aider e o Coolify
docker compose --profile build build
docker compose up -d            # interface em http://localhost:8000, Gitea em :3000
```

Sem Docker para a API (desenvolvimento):

```bash
pip install -e ".[dev]"
uvicorn painkiller.api.server:app --reload
docker build -f docker/worker.Dockerfile -t painkiller-worker:latest .
docker build -f docker/agent.Dockerfile  -t painkiller-agent:latest .
```

Frontend (SvelteKit) em `web/`; `npm run build` emite a SPA em
`painkiller/api/static/`, que é versionada para que um clone rode sem Node.

## Coolify

O Coolify clona o repositório do projeto a partir do Gitea embutido, então o
servidor do Coolify precisa alcançar o Gitea (`COOLIFY_GIT_BASE_URL` quando o
endereço não é o mesmo que o navegador usa). Variáveis:

| Variável | Para quê |
| --- | --- |
| `COOLIFY_URL`, `COOLIFY_TOKEN` | instância e token de API |
| `COOLIFY_PROJECT_UUID`, `COOLIFY_SERVER_UUID` | onde a aplicação é criada |
| `COOLIFY_ENVIRONMENT_NAME` | ambiente (padrão `production`) |
| `COOLIFY_DOMAIN_TEMPLATE` | opcional, ex. `https://{slug}.apps.exemplo.com.br` |
| `COOLIFY_GIT_BASE_URL` | opcional, como o Coolify enxerga o Gitea |

Sem essas variáveis tudo funciona até o backlog; só o botão "Publicar" e o
passo final do piloto ficam desativados.

## Arquitetura

Hexagonal (ports & adapters): `core/` define entidades e as portas
`IssueTrackerPort`, `SandboxPort`, `AgentSessionPort`, `GitPort`, `LLMPort` e
`DeploymentPort`; `adapters/` as implementa (SQLite, Docker, git CLI, Gitea,
Coolify, LiteLLM); `engine/` contém o orquestrador de tarefas, a análise
interativa e o piloto automático; `api/` é o FastAPI que faz a amarração. Veja
[CLAUDE.md](CLAUDE.md) para os detalhes que não estão óbvios no código.

```bash
pytest                          # suíte completa; Docker e Coolify são mockados
```
