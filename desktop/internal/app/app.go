// Package app junta config, cofre, cliente HTTP e as ações que a CLI e a bandeja usam.
package app

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/andrehsilva/annotation/desktop/internal/config"
	"github.com/andrehsilva/annotation/desktop/internal/credentials"
	"github.com/andrehsilva/annotation/desktop/internal/link"
	"github.com/andrehsilva/annotation/desktop/internal/notai"
	"github.com/andrehsilva/annotation/desktop/internal/notify"
	"github.com/andrehsilva/annotation/desktop/internal/openurl"
	"github.com/andrehsilva/annotation/desktop/internal/prompt"
	titlepkg "github.com/andrehsilva/annotation/desktop/internal/title"
)

// Notifier existe para os testes não chamarem notify-send.
type Notifier func(summary, body string, critical bool)

// App é o helper em memória. Não é seguro capturar em paralelo com o mesmo token? É: o cliente
// HTTP é seguro para uso concorrente; o chamador serializa os diálogos.
type App struct {
	Cfg      config.Config
	Store    credentials.Store
	Client   *notai.Client
	Prompt   prompt.Prompter
	Out      io.Writer
	Notifier Notifier

	token string
}

// New lê o token salvo (se houver) e monta o cliente. Nunca fala com a rede.
func New(cfg config.Config, store credentials.Store, prompter prompt.Prompter, out io.Writer) (*App, error) {
	cfg.Normalize()
	client, err := notai.NewClient(cfg.BaseURL, "")
	if err != nil {
		return nil, err
	}
	if prompter == nil {
		prompter = prompt.Default{}
	}
	if out == nil {
		out = io.Discard
	}
	application := &App{
		Cfg:      cfg,
		Store:    store,
		Client:   client,
		Prompt:   prompter,
		Out:      out,
		Notifier: notify.Send,
	}
	if cfg.Email != "" {
		token, err := store.Get(cfg.Email)
		switch {
		case err == nil:
			application.token = token
			client.SetToken(token)
		case !errors.Is(err, credentials.ErrNotFound):
			fmt.Fprintf(out, "aviso: não li o token salvo: %v\n", err)
		}
	}
	return application, nil
}

// Token informa se há uma sessão carregada (sem expor o valor).
func (a *App) Token() bool { return a.token != "" }

// Login força o diálogo de credenciais e grava o token.
func (a *App) Login(ctx context.Context) error { return a.login(ctx) }

func (a *App) login(ctx context.Context) error {
	email := a.Cfg.Email
	if email == "" {
		email = strings.TrimSpace(os.Getenv("NOTAI_EMAIL"))
	}
	if email == "" {
		value, err := a.Prompt.Entry("NotAI", "E-mail da conta", "")
		if err != nil {
			return err
		}
		email = value
	}
	email = strings.ToLower(strings.TrimSpace(email))
	if email == "" {
		return errors.New("e-mail vazio")
	}
	password := os.Getenv("NOTAI_PASSWORD")
	if password == "" {
		value, err := a.Prompt.Password("NotAI", "Senha de "+email)
		if err != nil {
			return err
		}
		password = value
	}
	token, user, err := a.Client.Login(ctx, email, password)
	if err != nil {
		return fmt.Errorf("entrar: %w", err)
	}
	a.Cfg.Email = email
	a.token = token
	a.Client.SetToken(token)
	if err := a.Store.Set(email, token); err != nil {
		fmt.Fprintf(a.Out, "aviso: não guardei o token: %v\n", err)
	}
	if _, err := config.Save(a.Cfg); err != nil {
		fmt.Fprintf(a.Out, "aviso: não guardei a configuração: %v\n", err)
	}
	who := user.Email
	if who == "" {
		who = email
	}
	fmt.Fprintf(a.Out, "conectado como %s\n", who)
	return nil
}

// withSession garante login e repete a ação uma vez quando o servidor responde 401.
func (a *App) withSession(ctx context.Context, run func() error) error {
	if a.token == "" {
		if err := a.login(ctx); err != nil {
			return err
		}
	}
	err := run()
	if !errors.Is(err, notai.ErrUnauthorized) {
		return err
	}
	if a.Cfg.Email != "" {
		_ = a.Store.Delete(a.Cfg.Email)
	}
	a.token = ""
	a.Client.SetToken("")
	if loginErr := a.login(ctx); loginErr != nil {
		return loginErr
	}
	return run()
}

// Capture valida o link, resolve o título e grava o bloco url na nota configurada (ou numa nova).
func (a *App) Capture(ctx context.Context, rawURL, title string) (notai.Captured, error) {
	target, err := link.Validate(rawURL)
	if err != nil {
		return notai.Captured{}, err
	}
	title = strings.Join(strings.Fields(strings.TrimSpace(title)), " ")
	if title == "" {
		title = titlepkg.ForURL(ctx, target)
	}
	title = titlepkg.Truncate(strings.TrimSpace(title), 200)
	if title == "" {
		title = titlepkg.Truncate(target, 200)
	}

	var captured notai.Captured
	err = a.withSession(ctx, func() error {
		value, err := a.Client.Capture(ctx, a.Cfg.NoteID, target, title)
		if err != nil {
			return err
		}
		captured = value
		return nil
	})
	if err != nil {
		a.notify("NotAI", "Falhou: "+err.Error(), true)
		return notai.Captured{}, fmt.Errorf("salvar %s: %w", target, err)
	}
	a.notify("NotAI", "Salvo: "+title, false)
	fmt.Fprintf(a.Out, "salvo: %s (%s)\n", title, target)
	return captured, nil
}

// Status mostra quem está conectado, fazendo login se preciso.
func (a *App) Status(ctx context.Context) (notai.User, error) {
	var user notai.User
	err := a.withSession(ctx, func() error {
		value, err := a.Client.Me(ctx)
		if err != nil {
			return err
		}
		user = value
		return nil
	})
	return user, err
}

// Logout revoga a sessão no servidor e apaga o token local.
func (a *App) Logout(ctx context.Context) error {
	if a.token != "" {
		if err := a.Client.Logout(ctx); err != nil {
			fmt.Fprintf(a.Out, "aviso: o servidor não revogou a sessão: %v\n", err)
		}
	}
	if a.Cfg.Email != "" {
		if err := a.Store.Delete(a.Cfg.Email); err != nil {
			return fmt.Errorf("apagar token: %w", err)
		}
	}
	a.token = ""
	a.Client.SetToken("")
	fmt.Fprintln(a.Out, "sessão removida deste computador")
	return nil
}

// Open abre a plataforma no navegador padrão.
func (a *App) Open() error { return openurl.Open(a.Cfg.BaseURL) }

// ConfigPath devolve onde o config está (ou estaria) gravado.
func (a *App) ConfigPath() string {
	path, err := config.Path()
	if err != nil {
		return ""
	}
	return path
}

func (a *App) notify(summary, body string, critical bool) {
	if a.Notifier != nil {
		a.Notifier(summary, body, critical)
	}
}
