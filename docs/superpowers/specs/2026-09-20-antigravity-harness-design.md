# Design: Refatoração do Harness para Antigravity CLI + Superpowers + Gemini 3.8 Flash

## 1. Contexto e Objetivos

O Painkiller orquestra agentes autônomos para desenvolvimento de software. Na fase de análise inicial (*"Iniciar análise"*), um agente em contêiner conduz uma entrevista de elicitação de requisitos com o analista humano através da skill `superpowers:brainstorming`.

Atualmente, essa etapa roda sobre o Claude Code (`@anthropic-ai/claude-code`) acoplado a um proxy intermediário (LiteLLM) para tradução de chamadas. 

**Objetivo:** Refatorar o harness de agente para utilizar nativamente o **Antigravity CLI (`agy`)** com o plugin **Superpowers** e o modelo **Gemini 3.8 Flash**, alimentado diretamente pela chave de API configurada no arquivo `.env` (`GEMINI_API_KEY`).

---

## 2. Arquitetura do Novo Harness

### 2.1 Componentes e Fluxo de Execução

1. **Daemon do Contêiner (`agent.Dockerfile`)**:
   - Instalação do binário nativo do Antigravity CLI (`agy`) a partir do instalador oficial (`https://antigravity.google/cli/install.sh`).
   - Clone do repositório `superpowers` em `/opt/superpowers` e registro do plugin no `agy` (`agy plugin install /opt/superpowers` e espelhamento em `/root/.gemini/config/plugins/superpowers`).
   - Permissões de usuário sem privilégios (`node` uid 1000) e configuração segura do git.

2. **Ponte de Entrada (`painkiller agent-run`)**:
   - Executa o binário `agy` (padrão `--agent-bin agy`).
   - Faz o tail de `.painkiller/agent-stdin.jsonl` no workspace montado e envia mensagens NDJSON no stdin do processo.
   - Suporta detecção de sentinela `__painkiller_eof__` para encerramento gracioso.

3. **Adaptador Docker (`DockerAgentSession`)**:
   - Valida precocemente a existência de `GEMINI_API_KEY` (ou `GOOGLE_API_KEY`) no ambiente com mensagem clara em pt-BR.
   - Repassa `GEMINI_API_KEY` e variáveis do modelo para o contêiner.
   - Monta o volume de persistência do Antigravity em `/root/.gemini`.
   - Executa `agy` com as flags headless e de streaming:
     - `--model gemini-3.8-flash`
     - `--effort medium`
     - `--dangerously-skip-permissions`
     - `--input-format stream-json`
     - `--output-format stream-json`
     - `--conversation <id>` (quando em resume)
   - Formata as mensagens de usuário com `{ "event": "user", "type": "user", "message": { "role": "user", "content": text } }`.

4. **Parser de Eventos (`parse_agent_line`)**:
   - Mapeia a saída `stream-json` do `agy` para `AgentEvent`:
     - `event == "init"`: Identificação da conversa (`conversation_id`), inicialização do modelo.
     - `event == "step_update"`:
       - `step_type == "agent_response"` com `text_delta` -> `AgentEventType.ASSISTANT_DELTA`.
       - `step_type == "agent_response"` com `thinking_delta` -> `AgentEventType.THINKING_DELTA`.
       - `step_type == "tool"` (estado `ACTIVE`/`RUNNING`) -> `AgentEventType.TOOL_USE`.
       - `step_type == "tool"` (estado `DONE`/`ERROR`) -> `AgentEventType.TOOL_RESULT`.
     - `event == "result"`: Conclusão do turno -> `AgentEventType.RESULT` contendo `response`.
     - Mantém retrocompatibilidade com eventos anteriores do Claude Code.

5. **Configuração de Ambiente (`.env` e `docker-compose.yml`)**:
   - `GEMINI_API_KEY`: Armazena a chave de API do Gemini no `.env`.
   - `PAINKILLER_AGENT_MODEL`: `gemini-3.8-flash`.
   - `PAINKILLER_AGENT_EFFORT`: `medium`.
   - `docker-compose.yml`: Propaga `GEMINI_API_KEY` para o serviço `api`.

---

## 3. Plano de Testes e Validação

1. **Testes Unitários**:
   - `tests/unit/test_docker_agent_session.py`:
     - Validação de erro amigável na ausência de `GEMINI_API_KEY`.
     - Verificação do comando gerado com `--agent-bin agy`, flags de modelo `gemini-3.8-flash`, `--effort medium` e streaming JSON.
     - Validação do parser `parse_agent_line` cobrindo eventos `init`, `step_update` (deltas, tool calls) e `result`.
   - Execução de toda a suíte de testes existente com `pytest --import-mode=importlib`.

2. **Validação Manual / Execução Local**:
   - Verificação das flags executando o `agy` em modo stream-json com Gemini 3.8 Flash.
   - Garantir que `.env` está devidamente configurado com `GEMINI_API_KEY`.
