import type {
  AdminUser,
  Block,
  BlockListItem,
  BlockType,
  DriveStatus,
  EventFeed,
  MediaUpload,
  Note,
  NoteRelated,
  NoteSummary,
  Notebook,
  NotebookSummary,
  RelationEdge,
  Role,
  SearchResults,
  Stats,
  SyncSummary,
  Tag,
  TagUsage,
  User,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = init.body instanceof FormData;
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: isForm ? init.headers : { "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* response had no JSON body */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const api = {
  me: () => request<User>("/api/auth/me"),
  login: (email: string, password: string) =>
    request<User>("/api/auth/login", { method: "POST", ...json({ email, password }) }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("/api/auth/password", {
      method: "POST",
      ...json({ current_password, new_password }),
    }),

  events: (limit = 5) => request<EventFeed>(`/api/events?limit=${limit}`),
  markEventsRead: () => request<void>("/api/events/read", { method: "POST" }),

  adminListUsers: () => request<AdminUser[]>("/api/admin/users"),
  adminCreateUser: (payload: {
    email: string;
    display_name: string;
    password: string;
    role: Role;
  }) => request<AdminUser>("/api/admin/users", { method: "POST", ...json(payload) }),
  adminUpdateUser: (id: number, patch: { display_name?: string; role?: Role; is_active?: boolean }) =>
    request<AdminUser>(`/api/admin/users/${id}`, { method: "PATCH", ...json(patch) }),
  adminResetPassword: (id: number, password: string) =>
    request<void>(`/api/admin/users/${id}/password`, { method: "POST", ...json({ password }) }),
  adminDeleteUser: (id: number) => request<void>(`/api/admin/users/${id}`, { method: "DELETE" }),

  listNotebooks: () => request<NotebookSummary[]>("/api/notebooks"),
  getNotebook: (id: number) => request<Notebook>(`/api/notebooks/${id}`),
  createNotebook: (title: string, description = "") =>
    request<Notebook>("/api/notebooks", { method: "POST", ...json({ title, description }) }),
  updateNotebook: (id: number, patch: { title?: string; description?: string }) =>
    request<Notebook>(`/api/notebooks/${id}`, { method: "PATCH", ...json(patch) }),
  deleteNotebook: (id: number) => request<void>(`/api/notebooks/${id}`, { method: "DELETE" }),
  attachNotebookTag: (id: number, tagId: number) =>
    request<Notebook>(`/api/notebooks/${id}/tags/${tagId}`, { method: "POST" }),
  detachNotebookTag: (id: number, tagId: number) =>
    request<Notebook>(`/api/notebooks/${id}/tags/${tagId}`, { method: "DELETE" }),

  getNote: (id: number) => request<Note>(`/api/notes/${id}`),
  createNote: (notebookId: number, title = "", text = "") =>
    request<Note>(`/api/notebooks/${notebookId}/notes`, {
      method: "POST",
      ...json({ title, text }),
    }),
  updateNote: (id: number, patch: { title?: string; position?: number }) =>
    request<Note>(`/api/notes/${id}`, { method: "PATCH", ...json(patch) }),
  deleteNote: (id: number) => request<void>(`/api/notes/${id}`, { method: "DELETE" }),
  attachNoteTag: (id: number, tagId: number) =>
    request<Note>(`/api/notes/${id}/tags/${tagId}`, { method: "POST" }),
  detachNoteTag: (id: number, tagId: number) =>
    request<Note>(`/api/notes/${id}/tags/${tagId}`, { method: "DELETE" }),

  noteRelated: (id: number) => request<NoteRelated>(`/api/notes/${id}/related`),
  createRelation: (id: number, targetId: number, label: string) =>
    request<NoteRelated>(`/api/notes/${id}/relations`, {
      method: "POST",
      ...json({ target_id: targetId, label }),
    }),
  deleteRelation: (id: number, relationId: number) =>
    request<NoteRelated>(`/api/notes/${id}/relations/${relationId}`, { method: "DELETE" }),
  listNotes: (q = "", limit = 300) =>
    request<NoteSummary[]>(`/api/notes?q=${encodeURIComponent(q)}&limit=${limit}`),

  createBlock: (noteId: number, type: BlockType, position?: number) =>
    request<Block>(`/api/notes/${noteId}/blocks`, {
      method: "POST",
      ...json({ type, position }),
    }),
  updateBlock: (
    id: number,
    patch: Partial<Pick<Block, "type" | "text" | "language" | "url" | "caption">>,
  ) => request<Block>(`/api/blocks/${id}`, { method: "PATCH", ...json(patch) }),
  deleteBlock: (id: number) => request<void>(`/api/blocks/${id}`, { method: "DELETE" }),
  reorderBlocks: (noteId: number, blockIds: number[]) =>
    request<Block[]>(`/api/notes/${noteId}/blocks/reorder`, {
      method: "POST",
      ...json({ block_ids: blockIds }),
    }),

  listTags: () => request<TagUsage[]>("/api/tags"),
  listRelations: () => request<RelationEdge[]>("/api/relations"),
  listBlocks: (type: BlockType, limit = 300) =>
    request<BlockListItem[]>(`/api/blocks?type=${type}&limit=${limit}`),
  createTag: (name: string) => request<Tag>("/api/tags", { method: "POST", ...json({ name }) }),
  deleteTag: (id: number) => request<void>(`/api/tags/${id}`, { method: "DELETE" }),

  upload: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<MediaUpload>("/api/media", { method: "POST", body });
  },

  driveStatus: () => request<DriveStatus>("/api/drive/status"),
  driveUploadClient: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<DriveStatus>("/api/drive/client-file", { method: "POST", body });
  },
  driveConnect: () => request<DriveStatus>("/api/drive/connect", { method: "POST" }),
  driveDisconnect: () => request<void>("/api/drive/disconnect", { method: "POST" }),
  driveSync: () => request<SyncSummary>("/api/drive/sync", { method: "POST" }),
  driveSetAutoSync: (enabled: boolean) =>
    request<DriveStatus>("/api/drive/settings", { method: "PATCH", ...json({ auto_sync: enabled }) }),

  search: (query: string) =>
    request<SearchResults>(`/api/search?q=${encodeURIComponent(query)}`),
  stats: () => request<Stats>("/api/stats"),
};
