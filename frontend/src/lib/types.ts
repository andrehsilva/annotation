export type BlockType = "text" | "code" | "url" | "image" | "video";

export interface Tag {
  id: number;
  name: string;
  color: string;
}

export interface TagUsage extends Tag {
  notebooks_count: number;
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
  updated_at: string;
  note_id: number;
  note_title: string;
  notebook_id: number;
  notebook_title: string;
}

export type BlockCounts = Record<BlockType, number>;

export interface NoteSummary {
  id: number;
  notebook_id: number;
  notebook_title: string;
  title: string;
  position: number;
  created_at: string;
  updated_at: string;
  tags: Tag[];
  counts: BlockCounts;
  excerpt: string;
}

/** A note seen from another one: enough to label it, open it and place it in its notebook. */
export interface RelatableNote {
  id: number;
  title: string;
  notebook_id: number;
  notebook_title: string;
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

/** A notebook reached through its notes, with how many note links cross over. */
export interface NotebookAffinity {
  notebook_id: number;
  title: string;
  links_count: number;
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
  source_notebook_id: number;
  target_notebook_id: number;
}

export interface Note {
  id: number;
  notebook_id: number;
  title: string;
  position: number;
  created_at: string;
  updated_at: string;
  tags: Tag[];
  blocks: Block[];
  relations: NoteRelation[];
}

export interface Tag {
  id: number;
  name: string;
  color: string;
}

export interface TagUsage extends Tag {
  notebooks_count: number;
  notes_count: number;
}

export interface NotebookSummary {
  id: number;
  title: string;
  description: string;
  created_at: string;
  updated_at: string;
  tags: Tag[];
  notes_count: number;
  counts: BlockCounts;
  /** How many other notebooks this one reaches through its notes. */
  relations_count: number;
}

export interface Notebook extends NotebookSummary {
  notes: NoteSummary[];
  affinity: NotebookAffinity[];
}

export interface SearchHit {
  kind: "notebook" | "note" | "block" | "tag";
  id: number;
  notebook_id: number | null;
  note_id: number | null;
  title: string;
  snippet: string;
}

export interface SearchResults {
  query: string;
  hits: SearchHit[];
}

export interface Stats {
  notebooks: number;
  notes: number;
  blocks: number;
  tags: number;
  relations: number;
  counts: BlockCounts;
}

export interface MediaUpload {
  url: string;
  kind: "image" | "video";
  name: string;
  size: number;
}

export interface SyncSummary {
  notes_sent: number;
  notes_unchanged: number;
  folders_created: number;
  media_sent: number;
  skipped_media: number;
  errors: string[];
  at: string;
}

export interface DriveStatus {
  connected: boolean;
  has_client_file: boolean;
  auto_sync: boolean;
  pending: boolean;
  last_sync_at: string | null;
  last_summary: SyncSummary | null;
  last_error: string | null;
}

export type Role = "admin" | "user";

/** The account behind the session cookie. */
export interface User {
  id: number;
  email: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

/** The same account seen from the admin screen: how much data it holds. */
export interface AdminUser extends User {
  notebooks: number;
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
