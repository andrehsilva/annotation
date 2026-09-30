import type { Block, BlockType, NoteSummary, ShareRole } from "./types";

/** Alt+Space walks this order. */
export const KIND_ORDER: BlockType[] = ["text", "code", "url", "image", "video", "pdf"];

/** O papel de uma conta dentro de uma nota, como a tela o chama. */
export const SHARE_ROLE_LABELS: Record<ShareRole, string> = {
  owner: "dono",
  editor: "editor",
  viewer: "leitor",
};

export const KIND_LABELS: Record<BlockType, string> = {
  text: "texto",
  code: "código",
  url: "url",
  image: "imagem",
  video: "vídeo",
  pdf: "pdf",
};

export const KIND_SHORT: Record<BlockType, string> = {
  text: "TXT",
  code: "COD",
  url: "URL",
  image: "IMG",
  video: "VID",
  pdf: "PDF",
};

export function nextKind(kind: BlockType): BlockType {
  return KIND_ORDER[(KIND_ORDER.indexOf(kind) + 1) % KIND_ORDER.length];
}

export function isBlank(block: Pick<Block, "text" | "url" | "caption">): boolean {
  return !block.text.trim() && !block.url.trim() && !block.caption.trim();
}

/**
 * O bloco é de outra conta (nota compartilhada). A API só deixa quem escreveu mudá-lo ou
 * apagá-lo, então a tela desliga a edição: `author` vem preenchido apenas para bloco alheio.
 */
export function isForeignBlock(block: Pick<Block, "author">): boolean {
  return block.author !== "";
}

/** O filtro da lista, também usado pelo atalho de tag: título, trecho ou tag aplicada. */
export function noteMatches(note: NoteSummary, needle: string): boolean {
  const term = needle.trim().toLowerCase();
  if (!term) return true;
  return (
    note.title.toLowerCase().includes(term) ||
    note.excerpt.toLowerCase().includes(term) ||
    note.tags.some((tag) => tag.name.toLowerCase().includes(term))
  );
}

const dateFormatter = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "short",
  year: "numeric",
});

export function formatDate(iso: string): string {
  return dateFormatter.format(new Date(iso));
}

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 1) return "agora";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} d`;
  return formatDate(iso);
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function youtubeId(url: string): string | null {
  const match = url.match(
    /(?:youtube\.com\/(?:watch\?v=|embed\/|shorts\/)|youtu\.be\/)([A-Za-z0-9_-]{6,})/,
  );
  return match ? match[1] : null;
}

export function vimeoId(url: string): string | null {
  const match = url.match(/vimeo\.com\/(\d+)/);
  return match ? match[1] : null;
}
