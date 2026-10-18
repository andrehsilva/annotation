# notai-capture

Helper de desktop em Go para salvar o link que está aberto no navegador no **NotAI**. Roda como
bandeja (Linux/GNOME) ou como comando, sem extensão de navegador e sem CGO.

O app nativo fala direto com o BFF: faz login com e-mail/senha, guarda o cookie de sessão no cofre do
sistema e cria **nota + bloco `url`** pelas rotas existentes. Como ele não manda `Origin`, o guard de
escrita do backend (`backend/app/main.py`) não interfere.

## Build

Precisa de Go 1.22 ou mais novo.

```bash
cd desktop
go test ./...
CGO_ENABLED=0 go build -trimpath -o bin/notai-capture ./cmd/notai-capture
```

Se você tiver `make`, `make test` e `make build` fazem o mesmo. O binário é estático e não depende
de bibliotecas gráficas.

## Instalar

O próprio binário instala os arquivos (não precisa de `make`):

```bash
./bin/notai-capture install
```

Ou `make install`, se preferir. Isso copia:

- `bin/notai-capture` para `~/.local/bin/`;
- o item de menu e o handler `notai://` para `~/.local/share/applications/`;
- o autostart para `~/.config/autostart/`;
- o ícone para `~/.local/share/icons/hicolor/scalable/apps/`.

Para tirar o autostart sem desinstalar o resto:

```bash
rm ~/.config/autostart/notai-capture-autostart.desktop
```

## Primeiro login

```bash
notai-capture login --base https://notai.seudominio.com
```

Em desenvolvimento, a base padrão é `http://localhost:8000` (o backend direto). O e-mail e a senha
são pedidos uma vez; o token fica no **Secret Service** (`secret-tool`) e a senha não é guardada. Se
o cofre não estiver disponível, o fallback é um arquivo `0600` em
`~/.local/state/notai-capture/token-*`.

Para conferir:

```bash
notai-capture status
```

## Usar

### Bandeja

`notai-capture` (sem argumentos) ou o item **NotAI Capture** no menu. O menu da bandeja tem:

- **Salvar link do clipboard** — pega a URL copiada e cria a nota/bloco;
- **Salvar link…** — abre um campo já preenchido com o clipboard;
- **Abrir NotAI**;
- **Entrar…** / **Sair**.

No GNOME, a bandeja depende da extensão **AppIndicator and KStatusNotifierItem Support** (já vem
habilitada em muitos Fedora). Sem ela o ícone não aparece.

### Atalho do GNOME (Wayland)

Atalhos globais por biblioteca não funcionam bem em Wayland. Use **Configurações → Teclado →
Atalhos personalizados**:

- Nome: `Salvar no NotAI`
- Comando: `notai-capture capture`
- Atalho: `Ctrl+Alt+L`

`Ctrl+Alt+N` não serve: o app já usa essa combinação para criar uma nota. Fluxo: `Ctrl+L`, `Ctrl+C` e
o atalho. O helper lê o clipboard, busca o `<title>` da página e salva.

### Um clique com bookmarklet

Com o handler instalado, crie um favorito com esta URL:

```js
javascript:void(location.href='notai://capture?url='+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title))
```

O navegador pergunta uma vez se pode abrir o `notai://`; depois é um clique. O título vem da própria
página, sem requisição extra.

### CLI

```bash
notai-capture capture https://exemplo.com/artigo --title "Artigo"
notai-capture capture                     # lê o clipboard
notai-capture capture --note 42           # entra na nota 42 em vez de criar outra
notai-capture login --base https://...
notai-capture logout
notai-capture status
notai-capture open
notai-capture install                     # copia binário, menu, handler e autostart
notai-capture uninstall                   # remove o que o install colocou
notai-capture config --note 42            # nota fixa para todas as capturas
notai-capture config --base https://... --email ana@exemplo.com
notai-capture version
```

`Capture` cria uma nota por link por padrão. Para juntar tudo numa nota só:

```bash
notai-capture config --note <id-da-nota>
```

## Arquivos

| caminho | conteúdo |
| --- | --- |
| `~/.config/notai-capture/config.json` | `base_url`, `email`, `note_id` (sem segredo) |
| Secret Service (`secret-tool`) | token da sessão, por e-mail |
| `~/.local/state/notai-capture/token-*` | fallback do token, permissão `0600` |
| `~/.local/state/notai-capture/notai-capture.log` | log da bandeja |

O token é uma credencial completa: quem o tiver age como a conta até a sessão expirar (30 dias) ou
ser revogada. `notai-capture logout` chama `/api/auth/logout` e apaga o token local; trocar a senha
derruba as outras sessões.

## Windows e macOS

O núcleo (HTTP, config, link, título) é portátil e compila com `CGO_ENABLED=0`:

```bash
GOOS=windows GOARCH=amd64 go build -o notai-capture.exe ./cmd/notai-capture
GOOS=darwin  GOARCH=amd64 go build -o notai-capture ./cmd/notai-capture
```

No Windows, a CLI funciona (clipboard via PowerShell, token em arquivo), mas a **bandeja** ainda não
tem adaptador: `notai-capture tray` responde "bandeja não suportada". O próximo passo é
`Shell_NotifyIcon` + `RegisterHotKey` + Credential Manager; no macOS, `NSStatusItem`. O código já
separa esses adaptadores por build tag.

## Limites conhecidos

- A captura faz `POST /api/notes` e depois `POST /api/notes/{id}/blocks`; se o segundo falhar, sobra
  uma nota vazia. Um endpoint `POST /api/capture` atômico resolveria.
- O título é lido como UTF-8; páginas em outra codificação caem para o hostname.
- Não há janela sempre no topo no Wayland; a bandeja é o lugar certo.
- O autostart do GNOME depende de `~/.local/bin` estar no `PATH` da sessão (no Fedora padrão, está).
