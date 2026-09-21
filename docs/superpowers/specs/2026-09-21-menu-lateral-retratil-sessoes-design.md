# Spec: Menu Lateral Retrátil de Sessões (Estilo Devin / Painkiller)

**Data:** 2026-09-21  
**Status:** Aprovado  
**Inspiração:** Menu lateral retrátil do Devin (Cognition AI), adaptado à identidade visual técnica e monocromática do Painkiller.

---

## 1. Visão Geral

Atualmente, as sessões ágeis (`IterationSession`) em `/projetos/[id]` são selecionadas através de um seletor horizontal (`SessionSelector.svelte`) posicionado no cabeçalho, entre o título do projeto e a régua de abas.

Este documento especifica a refatoração do seletor para uma **Sidebar Retrátil exclusiva de Sessões**, posicionada à esquerda do conteúdo do projeto. O componente oferece dois modos de visualização:
1. **Expandido (~240px)**: Exibe cabeçalho com título, botão de recolher `[|]`, lista vertical das sessões (#1, #2...) com títulos e badges de status, filete marcador ativo na borda esquerda e botão "+ Nova sessão".
2. **Recolhido / Mini-rail (~48px)**: Trilho compacto que exibe o botão `[|]` para expansão, identificadores numéricos das sessões em monospace (`#1`, `#2`) com filete ativo, e botão `+` para criação rápida.

O estado expandido/recolhido é persistido no `localStorage` do navegador para preservar a preferência do usuário entre recarregamentos e navegação.

---

## 2. Arquitetura e Layout

### 2.1 Estrutura em Duas Colunas em `routes/projetos/[id]/+layout.svelte`

O layout da rota de projetos passa a envolver o conteúdo principal e a barra lateral em uma grade/flexbox de layout persistente:

```
+-------------------------------------------------------------------------------+
| Cabeçalho Global do Painkiller (Logo | Projetos | Pendências | Usuário)       |
+-------------------+-----------------------------------------------------------+
| SIDEBAR SESSÕES   | ÁREA PRINCIPAL DO PROJETO                                 |
|                   |                                                           |
| [240px ou 48px]   | Topo: ← Projetos                            Repositório ↗ |
|                   | Título do Projeto (nome, id, branch)                      |
|                   | Abas de Navegação: 1 Análise | 2 Backlog | 3 Sprints ...  |
|                   | --------------------------------------------------------- |
|                   | {@render children()}                                      |
|                   | (Análise / Backlog / Sprints / Artefatos / Contexto...)   |
+-------------------+-----------------------------------------------------------+
```

### 2.2 Persistência e Responsividade

- Chave no `localStorage`: `painkiller_sessions_sidebar_collapsed` (`"true"` | `"false"`).
- Para telas menores que `768px` (mobile), a sidebar não divide a largura da tela; fica oculta por padrão e desliza como gaveta (*drawer*) sobreposta ao clicar no botão de acionamento no topo.

---

## 3. Componentes e Mudanças na Interface

### 3.1 Primitiva SVG: Ícone `sidebar` em `Icon.svelte`
Adicionar a variante `'sidebar'` ao tipo `Name` e ao corpo SVG com traço único de 1.5 e terminais retos:
- Desenha o retângulo do navegador/painel com a divisória vertical à esquerda:
  - `<rect x="2" y="2.5" width="12" height="11" rx="0" />`
  - `<path d="M6 2.5v11" />`

### 3.2 Novo Componente `SessionSidebar.svelte`
Substitui `SessionSelector.svelte`.
- **Props:**
  - `sessions: IterationSession[]`
  - `activeSessionId: string | null`
  - `loading?: boolean`
  - `creating?: boolean`
  - `onselect: (session: IterationSession) => void`
  - `oncreate: () => void`

- **Elementos no modo expandido (240px):**
  - **Header da sidebar:**
    - Rótulo em caixa alta `SESSÕES` (`font-size: var(--t-micro); letter-spacing: 0.05em; color: var(--ink-3)`).
    - Botão de recolher com o ícone `sidebar` (`size={13}`), `title="Recolher barra lateral"`.
  - **Lista de sessões:**
    - Elemento `<button>` para cada sessão.
    - Indicador ativo: borda esquerda de 2px `var(--ink)` (estilo Devin, integrado à paleta Painkiller).
    - Conteúdo: `#1`, título truncado com reticências se longo, e badge de status (`PLANNING`, `BACKLOG`, `IN_SPRINT`, `COMPLETED`).
    - Tooltip nativo (`title`) com detalhes completos para acessibilidade.
  - **Rodapé / Ação:**
    - Botão `btn btn-line btn-sm` com largura total: `+ Nova sessão`.
    - Feedback imediato durante requisições (`creating = true`).

- **Elementos no modo recolhido / mini-rail (48px):**
  - **Header da sidebar:**
    - Botão centralizado com ícone `sidebar`, `title="Expandir barra lateral"`.
  - **Lista de sessões:**
    - Botão quadrado centralizado exibindo apenas `#1`, `#2` em fonte mono.
    - Borda esquerda indicadora ativa preservada.
    - `title` com o resumo da sessão (`#1 Sessão 1 — Status: Análise`).
  - **Ação:**
    - Botão compacto `+` centralizado.

### 3.3 Estilos e Filosofia Visual
- Paleta estritamente monocromática (`--paper`, `--paper-2`, `--rule-ink`, `--rule-2`, `--ink`, `--ink-2`, `--ink-3`).
- Sem bordas arredondadas (`border-radius: 0`).
- Transições rápidas e discretas (`0.15s cubic-bezier(0.4, 0, 0.2, 1)`).

---

## 4. Plano de Verificação

1. **Validação de Tipos e Build:**
   - Executar `npm run check` na pasta `web/` garantindo 0 erros de TypeScript / Svelte.
2. **Validação Visual e Interativa:**
   - Alternar entre os modos expandido e recolhido clicando no botão `[|]`.
   - Selecionar sessões diferentes no modo expandido e no modo recolhido, verificando a atualização do contexto em todas as telas (Análise, Backlog, Sprints, Artefatos).
   - Criar uma nova sessão a partir do botão `+` em ambos os modos.
   - Recarregar a página e confirmar que o estado de recolhimento é preservado via `localStorage`.
   - Redimensionar a tela para testar comportamento responsivo.
