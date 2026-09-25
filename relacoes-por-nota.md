# Relações por nota (e menções `[[…]]` nos blocos)

## Goal
Mover o relacionamento explícito do nível **caderno** para o nível **nota**, deixar a afinidade entre
cadernos como algo **derivado** das notas, e permitir citar outra nota de dentro de um bloco com `[[`
(ou `@`), com backlinks no rodapé da nota.

## Tasks

- [ ] **1. Modelo novo (aditivo)** — `backend/app/models.py`: `NoteRelation` (`source_id`/`target_id`
      FK `notes.id` CASCADE e indexadas, `label String(80)`, `created_at`, `UniqueConstraint(source_id,
      target_id)`) e `BlockLink` (`block_id` FK `blocks.id` CASCADE, `note_id` FK `notes.id` CASCADE,
      `UniqueConstraint(block_id, note_id)`) — mesmo molde de `NotebookRelation`.
      → Verify: `create_all` cria `note_relations` e `block_links`; `import app.main` ok e
      `GET /api/notebooks` responde 200 (nada antigo foi tocado ainda).

- [ ] **2. Menções + serviços derivados** — novo `backend/app/links.py`: `parse_mentions(text)`
      (regex `\[\[([^\[\]]+)\]\]`), `resolve(db, titles)` (casamento por título, ignora a própria nota e
      título inexistente), `reindex_block(db, block)` (apaga as linhas do bloco e regrava) e
      `rename_in_mentions(db, old, new)` (reescreve `[[antigo]]` → `[[novo]]` nos blocos que citam e
      reindexa). Ganchos: `routers/blocks.py::update_block`, `routers/notes.py::create_block` e
      `create_note` (texto do `NoteIn`) chamam `reindex_block`; `update_note` chama
      `rename_in_mentions` quando o título muda. Em `services.py`: `note_relations_for(db, note)` (as
      duas direções), `backlinks_for(db, note)` (blocos que citam, com nota de origem + trecho) e
      `notebook_affinity(db)` (conta pares de notas entre cadernos, somando relações e menções).
      → Verify: script descartável com 2 cadernos/3 notas grava `[[Outra nota]]` num bloco e confere
      as linhas em `block_links`, o backlink do alvo e afinidade 1 entre os cadernos; renomear a nota
      alvo reescreve o texto do bloco fonte e o vínculo continua.

- [ ] **3. Cutover do nível caderno** — remover `NotebookRelation` (modelo, `Notebook.relations`,
      `create_relation`/`delete_relation` em `routers/notebooks.py`, `services.relations_for` e o
      `relation_counts_by_notebook` atual), reescrever `relation_counts_by_notebook` sobre a afinidade
      derivada e rodar `DROP TABLE notebook_relations` no banco (as 1–2 linhas são descartadas por
      decisão).
      → Verify: `.tables` sem `notebook_relations`; `POST /api/notebooks/{id}/relations` → **404**;
      `import app.main` ok; `GET /api/notebooks` com `relations_count` já derivado.

- [ ] **4. Rotas de nota e grafo** — `routers/notes.py`: `POST`/`DELETE /api/notes/{id}/relations[/{rid}]`
      (idempotente, no formato do antigo de caderno), `GET /api/notes/{id}/related` →
      `{relations, mentions_out, backlinks}` e `relations: list[NoteRelationOut]` no `NoteOut`.
      `routers/relations.py`: `GET /api/relations` devolve arestas de **nota** (`source_id`,
      `target_id`, títulos, caderno de cada lado, `label`, `kind: "relation" | "mention"`).
      `routers/notebooks.py`: `NotebookOut` ganha `affinity: list[NotebookAffinity]`.
      `schemas.py`: `NoteRelationIn/Out`, `NoteRef` (com `notebook_title`), `NotebookAffinity`,
      `RelationEdge` novo.
      → Verify: `curl` cria relação entre duas notas, `GET /api/notes/{id}` traz `relations`,
      `GET /api/relations` traz as arestas (relação = cheia, menção = tracejada), `DELETE` → 204.

- [ ] **5. Frontend: tipos + api** — `lib/types.ts` (`NoteRelation`, `NoteRef`, `Backlink`,
      `NotebookAffinity`, `RelationEdge` novo) e `lib/api.ts` (`createNoteRelation`,
      `deleteNoteRelation`, `noteRelated`, e a remoção de `createRelation`/`deleteRelation`).
      → Verify: `npm run build` sem erro e sem referência sobrando a `api.createRelation`.

- [ ] **6. Editor: picker `[[` + rodapé** — `BlockCard.tsx` (só o `textarea` de `type === "text"`):
      quando o texto antes do caret casar `/\[\[([^\[\]]*)$/` ou `/@([\w\s]*)$/`, avisar o
      `NoteEditor` com `onMentionQuery(blockId, {query, start, end})`. `NoteEditor.tsx`: estado
      `mentionFor` + `MentionPalette.tsx` novo (mesmas classes `.palette` de `TagPalette`, notas
      filtradas por `api.search`, mostrando `caderno › nota`) que ao escolher troca `[[query` por
      `[[Título]]`. `NoteLinks.tsx` novo no fim do editor: **Relacionadas** (`+ relacionar com…` abrindo
      o picker, lista com remover), **Menciona** e **Mencionado em** (origem + trecho); cada item abre a
      nota por `onOpenNote(noteId, notebookId)`, ligado em `App.tsx` ao `openNote` existente.
      → Verify: no navegador `[[` abre a lista, `Enter` insere `[[Nota X]]`, X aparece em "Menciona" e
      a nota atual em "Mencionado em" de X; `+ relacionar` cria o vínculo no rodapé dos dois lados.

- [ ] **7. Caderno + grafo** — `RelationsModal.tsx` vira leitura: afinidade derivada
      (`outro caderno · N notas em comum`), clique abre o caderno, sai o formulário e as props
      `onAddRelation`/`onRemoveRelation`. `NotebookView.tsx`: botão "Afinidade" e chip com o
      `relations_count` derivado; `Sidebar.tsx` idem. `RelationsView.tsx`: sai o formulário de
      cadernos, a lista vira arestas de nota (remover + rótulo). `GraphCanvas.tsx`: nós = **notas**
      (cor por caderno), aresta cheia = relação, tracejada = menção, `onSelect(noteId, notebookId)`.
      → Verify: tela Relações com nós de nota e os dois tipos de aresta; remover pela lista some do
      grafo; modal do caderno sem formulário e abrindo o outro caderno.

- [ ] **8. Export `.md` + README** — `markdown.py::note_markdown(note, media_links=None, links=None)`:
      front matter ganha `related: [Título A, …]` (relações explícitas) e `mentions: [Título X, …]`
      (notas citadas); `sync.py::_export` passa as listas resolvidas. README: trocar a descrição de
      relações de caderno por nota + menções e atualizar a tabela de rotas.
      → Verify: script descartável imprime o `.md` de uma nota com relação e confere as duas linhas;
      próximo sync reenvia só os `.md` afetados e `notes_unchanged` volta ao normal.

- [ ] **9. Verificação** — com `api`/`web` locais rodando: relacionar duas notas de cadernos
      diferentes, citar com `[[`, conferir backlink e afinidade, renomear a nota alvo (texto
      reescrito + mesmo vínculo), remover a relação, conferir o grafo e `GET /api/stats`; `npm run
      build` limpo; nenhum 404/500 nos logs. Apagar os scripts descartáveis antes de fechar.
      → Verify: as duas telas e a API concordam com o `.md` exportado; `drive_state.last_error` vazio.

## Done When
- [ ] Relação explícita é entre **notas**, com rótulo opcional, criada no rodapé da nota e visível
      nos dois lados; a tela Relações só inspeciona e remove.
- [ ] Caderno não tem vínculo manual: a afinidade é derivada das notas (relações + menções), com
      contagem, no modal e nos chips.
- [ ] `[[` (e `@`) abre o seletor de nota dentro de um bloco de texto; a nota citada ganha
      "Mencionado em" com a origem.
- [ ] `GET /api/relations` e o grafo operam no nível de nota; `notebook_relations` não existe mais.
- [ ] O `.md` exportado traz `related`/`mentions` no front matter.

## Notes
- **Vocabulário**: nenhum rename é preciso — a UI já diz Caderno → Notas → Blocos (`Notas`, `Nova
  nota`, `Nota sem título`, `notes_count`); "Página" nunca apareceu no código.
- **Menção resolvida por id** (`block_links`), não por título: renomear a nota alvo reescreve
  `[[antigo]]` → `[[novo]]` nos blocos que citam (e o `.md` dessas notas é reenviado — correto).
  Menção a título inexistente não vira vínculo e o texto fica como está (sem aviso).
- **Menção ≠ relação**: Nota = relação declarada (com rótulo); Bloco = âncora no texto. As duas
  somam na afinidade do caderno.
- **Fora de escopo** (marcado como futuro por você): transclusão/bloco-espelho, relação bloco↔bloco,
  sugestão automática de relação.
- Se preferir manter dados do vínculo manual depois de ver o resultado, o passo 3 é o único que
  descarta (a tabela e as linhas); dá para trocá-lo por "preservar oculto" sem mexer no resto.
