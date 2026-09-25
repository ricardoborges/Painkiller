/* Anexos do chat da análise.
   O backend (ATTACHMENTS_HEADER em painkiller/engine/analysis.py) acrescenta à
   mensagem do analista um bloco com os caminhos dos arquivos, que é o que o
   agente lê. Na transcrição o bloco vira etiquetas com o nome de cada arquivo. */

const HEADER = 'Anexos enviados pelo analista';
const ITEM = /^- `([^`]+)`/;

export interface ParsedAnalystMessage {
  body: string;
  /** Nomes dos arquivos, sem o prefixo aleatório que o backend acrescenta. */
  files: string[];
}

export function parseAnalystMessage(text: string): ParsedAnalystMessage {
  const i = text.indexOf(HEADER);
  if (i < 0) return { body: text, files: [] };
  const files = text
    .slice(i)
    .split('\n')
    .map((l) => l.trim().match(ITEM)?.[1])
    .filter((p): p is string => !!p)
    .map(displayName);
  return { body: text.slice(0, i).trim(), files };
}

export function displayName(path: string): string {
  const base = path.split('/').pop() ?? path;
  return base.replace(/^[0-9a-f]{6}_/, '');
}

export function isImage(file: File): boolean {
  return file.type.startsWith('image/');
}

/** Imagem colada da área de transferência chega como "image.png": dá um nome melhor. */
export function namePasted(file: File): File {
  if (file.name && file.name !== 'image.png') return file;
  const ext = file.type.split('/')[1] || 'png';
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
  return new File([file], `colada-${stamp}.${ext}`, { type: file.type });
}
