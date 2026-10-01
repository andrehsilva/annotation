export type BlockType = "text" | "code" | "url" | "image" | "video" | "pdf";

export interface Tag {
  id: number;
  name: string;
  color: string;
}

export interface TagUsage extends Tag {
  notes_count: number;
}

export interface Block {
  id: number;
  note_id: number;
  position: number;
  type: BlockType;
  text: string;
  language: string;
  url: string;
  caption: string;
  /** Quem escreveu, quando não é você (nota compartilhada); vazio nos seus blocos. */
  author: string;
  created_at: string;
  updated_at: string;
}

export interface BlockListItem {
  id: number;
  type: BlockType;
  text: string;
  language: string;
  url: string;
  caption: string;
  author: string;
  updated_at: string;
  note_id: number;
  note_title: string;
}

export type BlockCounts = Record<BlockType, number>;

/** Uma nota na lista: é a unidade do app — tem dono, papel e compartilhamento próprios. */
export interface NoteSummary {
  id: number;
  title: string;
  position: number;
  created_at: string;
  updated_at: string;
  tags: Tag[];
  counts: BlockCounts;
  excerpt: string;
  /** Quantos vínculos (declarados ou citações) tocam esta nota. */
  relations_count: number;
  /** O papel de quem pediu: a nota pode ser de outra conta, alcançada por grupo. */
  role: ShareRole;
  owner_id: number;
  owner_name: string;
  /** `role !== "owner"`: a nota é de outra conta e chegou aqui por grupo. */
  shared: boolean;
  /** O outro lado: os grupos com que **esta** nota saiu daqui — vazio quando não é minha. */
  shared_groups: string[];
  /** Quantas contas esses grupos levam até a nota, fora eu (o dono já está aqui). */
  shared_people: number;
}

/** A nota com os blocos e os vínculos, como o editor a recebe. */
export interface Note extends NoteSummary {
  blocks: Block[];
  relations: NoteRelation[];
}

/** A note seen from another one: enough to label it and open it. */
export interface RelatableNote {
  id: number;
  title: string;
}

export interface NoteRelation {
  id: number;
  label: string;
  outgoing: boolean;
  other: RelatableNote;
}

export interface Backlink {
  note: RelatableNote;
  block_id: number;
  excerpt: string;
}

/** Everything around one note: declared relations, notes it cites, and who cites it. */
export interface NoteRelated {
  relations: NoteRelation[];
  mentions: RelatableNote[];
  backlinks: Backlink[];
}

export interface RelationEdge {
  key: string;
  kind: "relation" | "mention";
  id: number;
  label: string;
  source_id: number;
  target_id: number;
  source_title: string;
  target_title: string;
}

export interface SearchHit {
  kind: "note" | "block" | "tag";
  id: number;
  note_id: number | null;
  title: string;
  snippet: string;
}

export interface SearchResults {
  query: string;
  hits: SearchHit[];
}

export interface Stats {
  notes: number;
  blocks: number;
  tags: number;
  relations: number;
  counts: BlockCounts;
}

export interface MediaUpload {
  url: string;
  kind: "image" | "video" | "pdf";
  name: string;
  size: number;
}

/** Uma nota já publicada como gist: o id dela aqui e o link no GitHub. */
export interface PublishedGist {
  note_id: number;
  url: string;
}

/** O estado da publicação: se há token salvo e o que já saiu daqui. */
export interface GithubStatus {
  connected: boolean;
  published: PublishedGist[];
}

export type Role = "admin" | "user";

/** Papel de uma conta dentro de uma nota: quem só lê, quem escreve, e o dono. */
export type ShareRole = "owner" | "editor" | "viewer";

/** Grupo de contas — o público do compartilhamento, criado e mantido pelo admin. */
export interface Group {
  id: number;
  name: string;
  created_at: string;
  members: number;
}

export interface GroupDetail extends Group {
  member_ids: number[];
}

/** Quem alcança a nota, com o papel efetivo e os grupos que o trouxeram. */
export interface NoteMember {
  user_id: number;
  display_name: string;
  email: string;
  role: ShareRole;
  owner: boolean;
  groups: string[];
}

/** Um grupo com que a nota está compartilhada: o papel vale para todo mundo dele. */
export interface NoteGroupShare {
  group_id: number;
  name: string;
  role: "editor" | "viewer";
  members: number;
}

/** O painel de compartilhar: quem alcança, com quais grupos, e o que eu ainda posso escolher. */
export interface NoteSharing {
  role: ShareRole;
  can_share: boolean;
  members: NoteMember[];
  groups: NoteGroupShare[];
  available: Group[];
}

/** The account behind the session cookie. */
export interface User {
  id: number;
  email: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  /** `null` = a introdução do primeiro login ainda não foi dispensada, e ela abre ao entrar. */
  welcome_seen_at: string | null;
}

/** The same account seen from the admin screen: how much data it holds. */
export interface AdminUser extends User {
  notes: number;
  blocks: number;
  media_bytes: number;
}

/** Uma interação da plataforma, como o sino do topo a mostra. */
export interface ActivityEvent {
  id: number;
  action: string;
  entity: string;
  target: string;
  /** Segundo rótulo, só nas ações de duas partes (a tag e onde ela entrou). */
  detail: string;
  created_at: string;
  /** Quem fez; na conta comum é sempre quem está lendo. */
  actor: string;
  mine: boolean;
}

/** A página do feed com o total ainda não lido. */
export interface EventFeed {
  items: ActivityEvent[];
  unread: number;
}
