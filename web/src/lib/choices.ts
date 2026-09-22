/* Perguntas de múltipla escolha do agente de análise.
   O prompt (CHOICES_FENCE em painkiller/engine/analysis.py) pede que o agente
   termine a pergunta com um bloco ```painkiller-choices contendo JSON. Aqui ele
   é separado do markdown e vira opções clicáveis. Se o bloco não vier, ou vier
   inválido, a mensagem é mostrada como sempre foi — nada quebra. */

const FENCE = 'painkiller-choices';
const BLOCK = new RegExp('```' + FENCE + '[^\\n]*\\n([\\s\\S]*?)```', 'i');
const OPENING = new RegExp('```' + FENCE, 'i');

export interface ChoiceOption {
  label: string;
  description?: string;
}

export interface Choices {
  multiple: boolean;
  options: ChoiceOption[];
}

export interface ParsedMessage {
  body: string;
  choices: Choices | null;
}

function normalize(raw: unknown): Choices | null {
  if (!raw || typeof raw !== 'object') return null;
  const data = raw as { multiple?: unknown; options?: unknown };
  if (!Array.isArray(data.options)) return null;
  const options: ChoiceOption[] = [];
  for (const o of data.options) {
    if (typeof o === 'string' && o.trim()) {
      options.push({ label: o.trim() });
    } else if (o && typeof o === 'object' && typeof (o as ChoiceOption).label === 'string') {
      const { label, description } = o as ChoiceOption;
      if (!label.trim()) continue;
      options.push({
        label: label.trim(),
        description: typeof description === 'string' && description.trim() ? description.trim() : undefined
      });
    }
  }
  // "Outro" é da plataforma (Choices.svelte sempre acrescenta): o do agente sairia duplicado.
  const own = options.filter((o) => !isOther(o.label));
  if (!own.length) return null;
  return { multiple: data.multiple === true, options: own };
}

/** Rótulo da opção de resposta livre que o formulário sempre oferece. */
export const OTHER_LABEL = 'Outro';

function isOther(label: string): boolean {
  return /^outr[oa]s?(\s*\(.*\))?\s*[.:…]*$/i.test(label.trim());
}

/** Separa o bloco de opções do texto da mensagem. */
export function parseMessage(text: string): ParsedMessage {
  const m = text.match(BLOCK);
  if (!m) return { body: text, choices: null };
  let choices: Choices | null = null;
  try {
    choices = normalize(JSON.parse(m[1]));
  } catch {
    choices = null;
  }
  if (!choices) return { body: text, choices: null };
  return { body: text.replace(m[0], '').trim(), choices };
}

/** Durante o streaming o bloco chega pela metade: escondemos a partir da
    cerca de abertura, para o JSON cru não piscar na tela. */
export function hidePartialBlock(text: string): string {
  const i = text.search(OPENING);
  return i < 0 ? text : text.slice(0, i).trimEnd();
}

/** Recupera quais rótulos uma resposta já enviada escolheu; texto que não é
    rótulo de nenhuma opção conta como "Outro". */
export function pickedFrom(answer: string | undefined, choices: Choices): Set<string> {
  const picked = new Set<string>();
  if (!answer) return picked;
  const lines = answer
    .split('\n')
    .map((l) => l.replace(/^[-*]\s*/, '').trim())
    .filter(Boolean);
  const labels = new Set(choices.options.map((o) => o.label));
  for (const line of lines) picked.add(labels.has(line) ? line : OTHER_LABEL);
  return picked;
}

/** Monta o texto que vai ao agente a partir das opções marcadas e do "Outro". */
export function composeAnswer(labels: string[], other: string): string {
  const o = other.trim();
  if (!labels.length) return o;
  const base = labels.length === 1 ? labels[0] : labels.map((l) => `- ${l}`).join('\n');
  return o ? `${base}\n\n${OTHER_LABEL}: ${o}` : base;
}
