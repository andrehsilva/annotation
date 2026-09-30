import type {
  AdminUser,
  Block,
  BlockListItem,
  BlockType,
  EventFeed,
  Group,
  GroupDetail,
  MediaUpload,
  Note,
  NoteSharing,
  NoteRelated,
  NoteSummary,
  RelationEdge,
  Role,
  SearchResults,
  Stats,
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
  /** A introdução do primeiro login foi lida: a marca fica na conta e volta o usuário atualizado. */
  dismissWelcome: () => request<User>("/api/auth/welcome", { method: "POST" }),

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

  adminGroups: () => request<Group[]>("/api/admin/groups"),
  adminCreateGroup: (name: string) =>
    request<Group>("/api/admin/groups", { method: "POST", ...json({ name }) }),
  adminGroup: (id: number) => request<GroupDetail>(`/api/admin/groups/${id}`),
  adminRenameGroup: (id: number, name: string) =>
    request<Group>(`/api/admin/groups/${id}`, { method: "PATCH", ...json({ name }) }),
  adminDeleteGroup: (id: number) => request<void>(`/api/admin/groups/${id}`, { method: "DELETE" }),
  adminAddGroupMember: (groupId: number, userId: number) =>
    request<void>(`/api/admin/groups/${groupId}/members/${userId}`, { method: "PUT" }),
  adminRemoveGroupMember: (groupId: number, userId: number) =>
    request<void>(`/api/admin/groups/${groupId}/members/${userId}`, { method: "DELETE" }),

  /** Os grupos de que a conta participa: é a lista que o painel de compartilhar oferece. */
  myGroups: () => request<Group[]>("/api/groups"),
  noteSharing: (id: number) => request<NoteSharing>(`/api/notes/${id}/members`),
  shareNote: (id: number, groupId: number, role: "editor" | "viewer") =>
    request<NoteSharing>(`/api/notes/${id}/groups/${groupId}`, { method: "POST", ...json({ role }) }),
  unshareNote: (id: number, groupId: number) =>
    request<NoteSharing>(`/api/notes/${id}/groups/${groupId}`, { method: "DELETE" }),

  listNotes: (q = "", limit = 300) =>
    request<NoteSummary[]>(`/api/notes?q=${encodeURIComponent(q)}&limit=${limit}`),
  getNote: (id: number) => request<Note>(`/api/notes/${id}`),
  createNote: (title = "", text = "") =>
    request<Note>("/api/notes", { method: "POST", ...json({ title, text }) }),
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

  search: (query: string) =>
    request<SearchResults>(`/api/search?q=${encodeURIComponent(query)}`),
  stats: () => request<Stats>("/api/stats"),
};
