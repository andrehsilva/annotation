# NotAI

Caderno de anotações para desenvolvedores. Cada **caderno** guarda **notas**; cada nota é uma
sequência de **blocos** de cinco tipos: `texto`, `código`, `url`, `imagem`, `vídeo`. O texto corre
livre e o tipo do bloco troca no teclado, sem tirar a mão da linha.

Cada pessoa entra com **e-mail e senha** e enxerga só os próprios cadernos — notas, blocos, tags,
vínculos e arquivos são dela. Quem cria as contas é o **admin**, na tela **Usuários**.

- Backend: FastAPI como BFF fino, com **Appwrite como camada de dados** (`backend/`)
- Frontend: React 19 + Vite + TypeScript (`frontend/`)
- Tema escuro e claro, tokens em [`DESIGN.md`](DESIGN.md)

## Rodando

Backend (porta 8000) — precisa de `backend/.env` com as credenciais do Appwrite (veja `backend/.env.example`):

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# .venv/bin/python -m pip install -r requirements.txt         # macOS/Linux
.venv/Scripts/python.exe tools/appwrite_schema.py --check     # o schema está em dia na instância?
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

O schema do Appwrite é **código**: `tools/appwrite_schema.py --spec` imprime o que está declarado,
`--check` diz o que falta e `--apply` cria (idempotente). Nada de migração no start do app.

No primeiro start com a tabela de usuários vazia o app cria o admin e imprime a senha **uma vez** no log:

```
[notai] admin criado: admin@notai.local / senha k1Ki2YJGUvrf_8mQ — troque com `python manage.py set-password <e-mail>`
```

`CADERNO_ADMIN_EMAIL` e `CADERNO_ADMIN_PASSWORD` escolhem esse primeiro admin (sem a senha na
variável, ela é sorteada e mostrada no log) — o admin entra, troca a senha e cria as contas dos outros.

Frontend (porta 5173, proxy de `/api` e `/media` para o backend):

```bash
cd frontend
npm install
npm run dev
```

Dados de demonstração: `cd backend && .venv/Scripts/python.exe seed.py --reset`
(`--email <e-mail>` dá os dados a outra pessoa; o padrão é o admin).

## Deploy

Produção é Docker Compose atrás do proxy do painel: `deploy/docker-compose.yml` sobe dois serviços —
`api` (uvicorn em 8000) e `web` (nginx servindo o SPA e repassando `/api` e `/media` para `api:8000`) —
com as variáveis de `deploy/.env.example` (a `APPWRITE_API_KEY` fica só no painel, nunca no repositório).
Nenhuma porta é publicada: quem liga o domínio à porta 80 do serviço `web` é o EasyPanel.

No painel, o serviço é do tipo **Compose**, com o repositório deste projeto, branch `main` e **build
path** `deploy`. O segundo `server_name` do `frontend/nginx.conf` (console do Appwrite em
`host.docker.internal:8080`) só serve se o Appwrite for movido para essa porta; com o console roteado
pelo próprio painel ele fica sem uso.

## Dados

Tudo mora no **Appwrite** (TablesDB + Storage), no database de `APPWRITE_DATABASE_ID` — o Postgres/MariaDB
do Appwrite é o banco de verdade. O backend é a única porta: o front nunca fala com o Appwrite, então
não há SDK, CORS nem cookie de terceiro no navegador.

| tabela | o que guarda | chave (`$id`) |
| --- | --- | --- |
| `users` | conta, papel, `is_active`, hash da senha, `activity_seen_at` | id numérico (legado verbatim) |
| `sessions` | sessão do cookie: sha256 do token **truncado a 32 chars** (o `$id` aceita 36) | id truncado |
| `notebooks`, `notes`, `blocks` | o conteúdo, com `position` para a ordem | id numérico |
| `notebook_members` | papel do usuário no caderno (`owner`/`editor`/`viewer`) | `<user_id>_<notebook_id>` |
| `tags` | tag por dono; `name_key = "<owner_id>::<nome>"` com índice unique faz o nome ser único na conta | id numérico |
| `notebook_tags`, `note_tags` | tag aplicada a caderno/nota | `<caderno ou nota>_<tag>` |
| `note_relations`, `block_links` | vínculos declarados e menções `[[…]]`; índice unique no par | id numérico |
| `media_files` + bucket `media` | arquivos enviados; o arquivo é servido só para o dono | nome do arquivo |
| `events` | auditoria (o sino), uma linha por escrita | id numérico |
| `drive_files`, `drive_state` | estado do export para o Drive | `note_id` / `<user_id>_<chave>` |
| `counters` | contador de id por família (incremento atômico) | nome da família |

Convenções que valem a pena saber antes de mexer:

- **Sem cascata no servidor**: apagar caderno/nota/usuário é código nosso (`purge_user` no admin), em
  ordem, idempotente.
- **Escrita + auditoria no mesmo commit** via transação do Appwrite; linha repetida ou índice único
  violado aparece no commit e vira `Conflict`.
- **Agregação é nossa**: o Appwrite não tem `GROUP BY`/`JOIN`, então contagens, afinidade e busca
  filtram em Python sobre uma foto curta por usuário (`store().snapshot`).
- **Upload**: o bucket está limitado a **30 MB** pelo `_APP_STORAGE_LIMIT` do servidor; para os 256 MB
  do app é preciso subir essa variável no `.env` do Appwrite e recriar o stack.
- **Backup** passa a ser do Appwrite: `mysqldump` do banco + volumes `appwrite-uploads` e o `.env`
  (`_APP_OPENSSL_KEY_V1`). Os tokens do Drive continuam em `backend/data/drive_*.json`.

Ferramentas em `backend/tools/`: `appwrite_schema.py` (schema como código), `reset_appwrite.py`
(zera tabelas, bucket, contadores e sessões, e recria só o admin — `--dry-run` mostra antes),
`migrate_sqlite.py` (SQLite → Appwrite, idempotente), `parity_check.py` (grava/repete um roteiro de
requisições e compara as respostas), `test_appwrite_schema.py` (idempotência offline) e
`test_store_live.py` (a camada de dados contra a instância real).

## Usuários

- **Entrar**: só com e-mail e senha; a sessão é um cookie `notai_session` (httpOnly, 30 dias).
  Não existe autocadastro: sem conta, o admin cria uma.
- **Admin**: o chip **Usuários** (só aparece para quem tem o papel) lista todo mundo com cadernos,
  notas, blocos e espaço de mídia, cria conta, redefine senha, ativa/desativa e exclui. Excluir leva
  junto cadernos, notas, vínculos e os arquivos enviados — o diálogo diz isso antes. O admin não
  consegue rebaixar, desativar nem excluir a própria conta, e o último admin ativo fica protegido.
- **Qualquer um**: o chip do próprio nome (antes do botão do Drive) tem **Trocar senha** e **Sair**.
  Trocar a senha derruba as outras sessões daquela pessoa; o admin, ao redefinir a senha de alguém,
  derruba todas.
- **Sem acesso**: id de caderno, nota, bloco, tag ou arquivo de outra pessoa responde `404` (não
  `403`, para não confirmar que existe), e `401` aparece quando a sessão expira ou foi revogada — o
  app volta para a tela de entrada.
- **Atividade**: cada escrita na API vira uma linha em `events` (quem, o quê, em quê) e o sino mostra
  as 5 últimas. O admin enxerga a plataforma inteira, com o nome de quem agiu; uma conta comum enxerga
  apenas as próprias ações. Apagar uma conta leva junto as linhas dela — o que sobra é o registro de
  quem continua.
- **Fora do app**: quando a senha se perde, `backend/manage.py` resolve sem servidor no ar:

```bash
cd backend
.venv/Scripts/python.exe manage.py list-users
.venv/Scripts/python.exe manage.py create-user ana@casa.local --name Ana --admin
.venv/Scripts/python.exe manage.py set-password ana@casa.local
.venv/Scripts/python.exe manage.py set-role ana@casa.local user
.venv/Scripts/python.exe manage.py deactivate ana@casa.local
```

A senha é guardada como `scrypt` (`hashlib`, sem dependência nova) e cinco tentativas erradas no
mesmo e-mail em quinze minutos respondem `429` com `Retry-After`.

## Teclado

| Atalho | Efeito |
| --- | --- |
| `/` (em bloco vazio) | Abre o menu de tipo: `1`–`5` ou setas + `Enter` escolhe texto, código, url, imagem ou vídeo |
| `#` (em bloco vazio) | Abre a paleta de tags: filtra as existentes, `Enter` aplica/remove, ou cria a tag digitada. A tag nova entra na nota e no caderno |
| `[[` ou `@` (em bloco de texto) | Abre o seletor de notas: filtra por título, `Enter` insere `[[Título]]` e cria a menção |
| `Ctrl+Shift+L` | Mesmo menu de tipo, para quando o bloco já tem texto (abre um bloco novo do tipo escolhido) |
| Clicar no selo de tipo | Alternativa de mouse ao `/`, em qualquer bloco |
| `Ctrl+K` | Busca global em cadernos, notas, blocos e tags |
| `Enter` | Novo bloco (exceto em blocos de código, onde quebra linha) |
| `Shift+Enter` | Quebra de linha dentro do bloco |
| `Enter` na barra do caderno | Cria a nota com o nome digitado na barra e já abre para escrever |
| Digitar no caderno | Qualquer letra pula direto para a barra de escrever |
| `Alt+Enter` | Novo bloco de código mesmo dentro de um bloco de código |
| `Backspace` | Em um bloco vazio, apaga o bloco e volta o foco para o anterior |
| `Arrastar` o handle `⠿` | Reordena blocos |
| `Esc` | Fecha a paleta de tags, o menu de tipo, a busca ou o modal de confirmação |

> **Por que não `Alt+Espaço` / `Ctrl+Espaço`:** no Windows o `Alt+Espaço` abre o menu da janela e o
> `Ctrl+Espaço` é o alternador de IME — nenhum dos dois chega à página. Os gatilhos digitados (`/`,
> `#`) funcionam em qualquer navegador e não colidem com atalhos do browser ou do sistema.

Ações destrutivas (apagar caderno, nota, tag ou vínculo) passam por um modal próprio, com `Esc` para
cancelar e `Enter` para confirmar. Avisos de sucesso e erro aparecem em toasts na lateral direita,
logo abaixo da barra superior, e somem sozinhos (erros ficam por 7 s).

## Tela

- Sem sessão válida o app abre na tela de entrada (e-mail e senha); a lista, os contadores, a busca,
  as tags, o grafo e o Drive passam a mostrar só o que é daquela conta. A navegação (Cadernos, Notas,
  Tags, Relações) e, para o admin, **Usuários**, aparece no pipe da barra superior, ao lado dos
  **contadores por tipo de bloco** — os dois lados só com ícone + número (o nome aparece no hover),
  somando todos os cadernos no caso dos tipos. Clicar num contador abre a lista achatada daquele tipo:
  sem agrupamento por caderno, o mais recente primeiro, e cada cartão mostra a origem
  (`caderno › nota`) e um botão **Abrir nota**.
- **Notas**, logo depois de Cadernos, abre a lista de todas as notas de todos os cadernos — da mais
  recente para a mais antiga, com o trecho, o caderno de origem, as contagens por tipo e há quanto
  tempo foi mexida. Um clique abre a nota (mesmo vindo de outro caderno).
- **Usuários** (só admin): a lista de contas com cadernos, notas, blocos e espaço de mídia, o
  formulário de criação e as ações de cada linha — redefinir senha, ativar/desativar e excluir, com o
  mesmo modal de confirmação das outras ações destrutivas. Detalhes em [Usuários](#usuários).
- O **sino** ao lado do seu nome conta as interações ainda não vistas e mostra as 5 últimas. Ele abre
  sozinho ao entrar quando há alguma coisa no feed; ao fechar (clique fora, `Esc` ou novo clique no
  sino), tudo ali conta como visto e o contador zera — inclusive na conta, não só neste navegador.
  Cada linha diz quem fez, o quê e em quê: “criou a nota «X»”, “marcou «Y» com a tag «ideias»”,
  “apagou o caderno «Z»”.
- O chip com o próprio nome, à direita antes do botão do Drive, abre **Trocar senha** e **Sair**.
- Dentro da nota, o botão ao lado de **voltar** inverte a ordem dos blocos (mais novos primeiro); a
  faixa "continue escrevendo" e a linha de ícones/atalhos vão junto, de modo que o próximo bloco entra
  logo abaixo delas. A ordem das relações no rodapé não muda, e os números dos blocos continuam sendo
  a posição real na nota. A escolha fica guardada no navegador.
- Nessa lista o clique principal depende do tipo: **url** abre o site em outra aba, **imagem** abre um
  modal com a imagem no tamanho real, **vídeo** toca ali mesmo, e **texto/código** abre a nota já no
  bloco (que fica destacado por alguns segundos).
- A **imagem** abre em modal nos dois lugares onde ela aparece — o preview dentro da nota e o cartão da
  lista por tipo. O modal mostra o tamanho natural: se a imagem couber na janela, aparece 1:1; se não
  couber, entra encolhida até caber e um clique na imagem devolve o 1:1 com rolagem. A legenda diz as
  dimensões reais (`2000×1500px`). `Esc`, clique no fundo ou no botão fecham.
- A lista de cadernos pode ser escondida e trazida de volta pelo botão no canto esquerdo da barra
  superior (ou pelo botão no cabeçalho da própria lista). O estado fica salvo no navegador, e com a
  lista escondida o conteúdo usa a largura extra.
- A afinidade de um caderno fica atrás do botão **Afinidade** no cabeçalho: um modal que lista os
  outros cadernos alcançados pelas notas dele (relações declaradas e menções), com a contagem. É
  derivada, não declarada — quem cria vínculo são as notas. A visão global (grafo de notas) fica no
  item **Relações** da barra superior.
- Os contadores no cabeçalho do caderno são só ícone + número, e tipos com zero não aparecem.
- O ícone de nuvem na barra (antes do tema) abre o **Backup no Google Drive**. Ele ganha um ponto
  azul quando a conta está conectada.

As edições são salvas sozinhas (debounce de 700 ms) e o que ainda não foi enviado é descarregado ao
sair da nota.

## Ligações entre notas

O vínculo é **entre notas**, não entre cadernos: relacionar "Estudos de Rust" com "Backend" diz pouco,
enquanto ligar "Ownership em uma frase" a "Gestão de Memória no C++" diz exatamente qual conceito
conecta os dois. São duas camadas:

- **Relação declarada** — no rodapé da nota aberta, **relacionar com…** abre um seletor de notas com
  campo de rótulo opcional (`pré-requisito`, `complementa`, o que quiser). Aparece nos dois lados.
  O rodapé também lista o que a nota **relaciona**, o que ela **menciona** e os **mencionado em**
  (com o trecho de origem); qualquer item leva à nota.
- **Menção no texto** — dentro de um bloco de texto, digite `[[` (ou `@`, depois de um espaço) e
  escolha a nota: o texto passa a ter `[[Título da nota]]`. A menção é guardada pelo **id** da nota,
  então renomear a nota alvo reescreve o `[[…]]` nos blocos que a citam em vez de quebrar o vínculo.
  Título inexistente simplesmente não vira ligação (o texto fica como está).

A **afinidade de caderno** é consequência: soma as relações e as menções que atravessam cadernos e
conta quantas notas ligam cada par. Ela não pode ser declarada à mão — se as notas não se ligam, os
cadernos não têm afinidade. Cadernos com a mesma nota repetida não contam duas vezes.

A tela **Relações** é só leitura: o grafo desenha uma bolinha por nota ligada (cor = caderno), com
linha cheia para relação e tracejada para menção, e a lista embaixo mostra cada vínculo, com remover
só nas relações declaradas (uma menção sai editando o texto).

## Backup no Google Drive

O app mantém uma cópia das notas no Drive do próprio usuário, um `.md` por nota, em
`NotAI/<Caderno>/<Nota>.md`. É **mão única**: o NotAI escreve, nunca lê nem apaga nada no Drive —
apagar uma nota no app deixa o arquivo lá (órfão, para remoção manual). O escopo é `drive.file`, então
o app só enxerga o que ele mesmo criou.

**Cada conta conecta a própria conta Google** (o cliente OAuth e o token ficam em
`backend/data/drive_client.<id>.json` e `drive_token.<id>.json`, e o estado do export em `drive_state`
por usuário): cada um exporta só as próprias notas, e a conexão de um não aparece para os outros.
Quem não conectou simplesmente não tem backup — o painel explica isso.

Cada arquivo começa com front matter (`notebook`, `note`, `tags`, `related`, `mentions`, `created`,
`updated`, `notai_id`) e depois repete o texto do bloco, a cerca de código com a linguagem,
`[rótulo](url)` para url/vídeo e `![rótulo](url)` para imagem; arquivos locais (`/media/...`) são
enviados para `NotAI/_media` e o link do Drive entra no lugar da url local (acima de 20 MB, ou se o
arquivo sumiu, a url local fica).

Depois de cada escrita na API o app espera 20 s (o autosave faz rajadas) e envia só o que mudou —
a comparação é um sha256 do markdown já gravado em `drive_files`. O painel mostra o último envio, o
resumo, o erro mais recente, um botão **Sincronizar agora** e o liga/desliga do envio automático
(também por usuário). Renomear caderno ou nota renomeia pasta/arquivo **mantendo o mesmo id** no Drive.

Para conectar (uma vez, ~2 min): criar um projeto no
[Google Cloud Console](https://console.cloud.google.com/), ativar a **Google Drive API**, criar a
tela de permissão OAuth (tipo **Externo**, com o seu e-mail em "Usuários de teste"), criar um ID de
cliente do tipo **Aplicativo para computador** e baixar o JSON. O painel do app recebe esse JSON,
abre o navegador para autorizar e guarda o token em `backend/data/` (pasta fora do git). No modo
"Testes" do Google o refresh token expira em 7 dias: o app percebe, descarta o token e o painel volta
a pedir a conexão.

## Modelo de dados

O modelo lógico é o de sempre (abaixo); o de-para físico com as tabelas do Appwrite, as chaves e as
permissões está em [Dados](#dados).

```
users ──< sessions
  │
  └──< notebook_members >── notebooks ──< notes ──< blocks
        (papel: owner|editor|viewer)  │        │         │
                                      │        │         └──< block_links >── notes   (menção `[[…]]`)
                                      │        └──< note_relations >── notes          (N:N, com rótulo)
                                      └──< notebook_tags >── tags ──< note_tags >──┘
users ──< media_files        (dono de cada arquivo enviado)
users ──< drive_state        (chave/valor do export, uma linha por usuário)
users ──< events             (o feed do sino: quem fez, o quê, em quê)
```

**O dono de tudo é a linha em `notebook_members`** — notas, blocos, tags, vínculos e mídia pendem
dela, e é a única coisa que decide o que aparece para quem. Hoje cada caderno tem exatamente um
membro, com papel `owner`, criado junto com o caderno; `editor` e `viewer` já são entendidos por
`acl.allows`, então caderno compartilhado no futuro é uma linha nova nessa tabela, sem mexer em
nenhuma rota. Toda consulta passa por `readable_notebook_ids`/`readable_note_ids` e todo id que chega
pela URL passa por um loader que confere o papel e responde `404` quando não é de quem pediu.

`users` guarda e-mail (único, minúsculo), nome, `role` (`admin` ou `user`), `is_active` e o hash da
senha — nunca a senha. `sessions` guarda o `sha256` do token do cookie, o dono e a validade; apagar a
linha desloga na hora. `media_files` diz de quem é cada arquivo de `data/media/`, e é o que permite
`/media/<arquivo>` servir só para o dono. `tags` são de cada usuário (`owner_id` + nome único por
dono): a mesma palavra em duas contas são duas linhas, e renomear/apagar a de um não toca na do outro.

Cada bloco tem `type` e os campos `text`, `language`, `url`, `caption`; só os relevantes para o tipo
são usados, o que mantém a troca de tipo (Alt+Espaço) sem perda de conteúdo.

`note_relations` guarda uma linha por par (a direção só registra quem declarou, como o antigo vínculo
de caderno) e `block_links` uma linha por menção resolvida — as duas caem junto com a nota
(`ON DELETE CASCADE`). A afinidade de caderno e as contagens são calculadas a partir delas: não há
tabela de vínculo entre cadernos. Relação e menção nunca atravessam contas: a escrita valida as duas
pontas e a resolução do `[[título]]` só olha as notas de quem escreveu.

`events` é o histórico do que aconteceu: `user_id` (quem agiu), `action` (`created`, `updated`,
`deleted`, `tagged`, `untagged`, `linked`, `unlinked`, `uploaded`, `reset`), `entity` (`notebook`,
`note`, `block`, `tag`, `relation`, `media`, `user`), `target` (o rótulo do alvo, guardado no momento
da ação — sobrevive ao alvo ser apagado), `detail` (o segundo rótulo das ações de duas partes, como o
nome da tag) e `created_at`. A linha entra no mesmo commit da ação: se a ação falha, não sobra
histórico. Quem pode ler é decidido no servidor: o admin lê tudo, as outras contas leem só as próprias
linhas, e `users.activity_seen_at` guarda até quando aquela conta já viu — é o que alimenta o
contador de não lidas.

O backup usa duas tabelas à parte: `drive_files` (uma linha por nota: id do arquivo e da pasta no
Drive, caminho `Caderno/Nota.md`, sha256 do markdown enviado) e `drive_state` (chave/valor, por
usuário, com os ids de pasta, os links de mídia, o resumo do último envio e o `auto_sync`). Nenhuma
das duas guarda conteúdo de nota.

## API

Todas as rotas de `/api` (menos `login` e `health`) exigem o cookie de sessão; sem ele a resposta é
`401`. Erros de permissão são `404` quando o recurso é de outra conta e `403` só quando a conta existe
e o papel não permite (rotas de admin).

| Método | Rota | Uso |
| --- | --- | --- |
| `POST` | `/api/auth/login` · `/logout` · `/password` | entra (cookie de 30 dias) / sai / troca a própria senha |
| `GET` | `/api/auth/me` | quem está logado; `401` se a sessão acabou |
| `GET` | `/api/events?limit=` | o feed do sino: as últimas interações visíveis para quem pediu, com `unread` |
| `POST` | `/api/events/read` | marca tudo até agora como visto (é o que zera o contador) |
| `GET/POST` | `/api/admin/users` | lista as contas com cadernos, notas, blocos e mídia / cria (`409` se o e-mail existe) |
| `PATCH/DELETE` | `/api/admin/users/{id}` | nome, papel e ativação / exclui a conta com tudo o que é dela |
| `POST` | `/api/admin/users/{id}/password` | redefine a senha e derruba as sessões daquela conta |
| `GET/POST` | `/api/notebooks` | lista com contagens por tipo de bloco / cria (já com uma nota vazia) |
| `GET/PATCH/DELETE` | `/api/notebooks/{id}` | detalhe (notas, tags, afinidade derivada), renomear, apagar |
| `POST/DELETE` | `/api/notebooks/{id}/tags/{tag_id}` | aplica/remove tag do caderno |
| `GET` | `/api/relations` | todas as arestas entre notas, declaradas e menções (usado pelo grafo) |
| `GET/POST` | `/api/notebooks/{id}/notes` | lista/cria notas (`{"title": "...", "text": "..."}`; o `text`, quando vem, vira o primeiro bloco) |
| `GET` | `/api/notes` | todas as notas (resumo com caderno, trecho e contagens), da mais recente para a mais antiga; `?q=` filtra por título |
| `GET/PATCH/DELETE` | `/api/notes/{id}` | nota com blocos e relações, renomear, apagar |
| `GET` | `/api/notes/{id}/related` | relações, menções de saída e backlinks da nota |
| `POST/DELETE` | `/api/notes/{id}/relations[/{id}]` | cria (idempotente, com rótulo) / remove relação entre notas |
| `POST/DELETE` | `/api/notes/{id}/tags/{tag_id}` | aplica/remove tag da nota (a tag nova também entra no caderno) |
| `POST` | `/api/notes/{id}/blocks` | cria bloco |
| `POST` | `/api/notes/{id}/blocks/reorder` | reordena (`{"block_ids": [...]}` com todos os blocos da nota) |
| `PATCH/DELETE` | `/api/blocks/{id}` | edita/apaga bloco |
| `GET/POST/PATCH/DELETE` | `/api/tags` | as tags de quem pediu, com contagem de uso; `POST` é idempotente por nome dentro da conta |
| `POST` | `/api/media` | upload (imagem/vídeo, até 256 MB) → `{"url": "/media/..."}`; o arquivo fica com o dono |
| `GET` | `/media/{arquivo}` | serve o arquivo só para o dono; qualquer outro recebe `404` |
| `GET` | `/api/search?q=` · `/api/stats` | busca e totais apenas do que é daquela conta |
| `GET` | `/api/drive/status` | conexão, `auto_sync`, envio pendente, resumo e erro do último envio |
| `POST` | `/api/drive/client-file` | recebe o JSON do cliente OAuth (multipart `file`) |
| `POST` | `/api/drive/connect` | abre o navegador e espera a autorização (bloqueia até voltar) |
| `POST` | `/api/drive/disconnect` | esquece token e ids em cache; não toca em nada no Drive |
| `PATCH` | `/api/drive/settings` | `{"auto_sync": true\|false}` |
| `POST` | `/api/drive/sync` | exporta agora e devolve o resumo (`409` se não conectado ou já rodando) |
