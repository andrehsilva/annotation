// Command notai-capture salva o link atual no NotAI.
//
// A bandeja fala D-Bus puro (sem GTK/CGO); a CLI serve para atalho do GNOME e scripts.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/andrehsilva/annotation/desktop/internal/app"
	"github.com/andrehsilva/annotation/desktop/internal/clipboard"
	"github.com/andrehsilva/annotation/desktop/internal/config"
	"github.com/andrehsilva/annotation/desktop/internal/credentials"
	"github.com/andrehsilva/annotation/desktop/internal/install"
	"github.com/andrehsilva/annotation/desktop/internal/link"
	"github.com/andrehsilva/annotation/desktop/internal/notify"
	"github.com/andrehsilva/annotation/desktop/internal/prompt"
	"github.com/andrehsilva/annotation/desktop/internal/tray"
)

var version = "dev"

const usageText = `notai-capture — salva links no NotAI

Uso:
  notai-capture                          abre a bandeja
  notai-capture capture [URL]            salva a URL (sem URL, lê o clipboard)
  notai-capture login [--base URL]       entra e guarda o token
  notai-capture logout                   revoga a sessão e apaga o token
  notai-capture status                   mostra a conta conectada
  notai-capture open                     abre a plataforma no navegador
  notai-capture install                  instala binário, menu, handler e autostart
  notai-capture uninstall                remove o que o install colocou
  notai-capture config [--base URL] [--email EMAIL] [--note ID]
  notai-capture notai://capture?url=...&title=...
  notai-capture version

Opções de capture:
  --title TEXTO   título do bloco (padrão: <title> da página)
  --note ID       nota que recebe o link (0 = nota nova)
  --base URL      origem do app (padrão: config ou http://localhost:8000)

O atalho do GNOME deve chamar: notai-capture capture
O handler notai:// deve chamar:   notai-capture %u
`

func main() {
	logFile, err := setupLog()
	if err == nil {
		defer logFile.Close()
	}
	if err := run(os.Args[1:]); err != nil {
		switch {
		case errors.Is(err, prompt.ErrCanceled):
			os.Exit(1)
		case errors.Is(err, tray.ErrAlreadyRunning):
			os.Exit(0)
		default:
			fmt.Fprintln(os.Stderr, "notai-capture:", err)
			os.Exit(1)
		}
	}
}

func run(args []string) error {
	if len(args) == 0 {
		return runTray()
	}
	first := args[0]

	if capture, ok, err := link.ParseScheme(first); ok {
		if err != nil {
			return err
		}
		return captureOne(capture.URL, capture.Title, 0, "")
	}

	switch first {
	case "tray":
		return runTray()
	case "capture":
		return runCapture(args[1:])
	case "login":
		return runLogin(args[1:])
	case "logout":
		return runLogout()
	case "status":
		return runStatus()
	case "open":
		return runOpen()
	case "install":
		return runInstall()
	case "uninstall":
		return runUninstall()
	case "config":
		return runConfig(args[1:])
	case "version", "--version", "-v":
		fmt.Println("notai-capture", version)
		return nil
	case "help", "--help", "-h":
		fmt.Print(usageText)
		return nil
	}

	if _, err := link.Validate(first); err == nil {
		return captureOne(first, "", 0, "")
	}
	return fmt.Errorf("comando desconhecido: %q (use --help)", first)
}

func loadApp(out io.Writer, baseOverride string) (*app.App, error) {
	cfg, err := config.Load()
	if err != nil {
		return nil, err
	}
	if env := strings.TrimSpace(os.Getenv("NOTAI_BASE")); env != "" {
		cfg.BaseURL = env
		cfg.Normalize()
	}
	if strings.TrimSpace(baseOverride) != "" {
		cfg.BaseURL = baseOverride
		cfg.Normalize()
	}
	return app.New(cfg, credentials.New(), prompt.Default{}, out)
}

func captureOne(rawURL, title string, noteID int64, base string) error {
	application, err := loadApp(os.Stdout, base)
	if err != nil {
		return err
	}
	if noteID > 0 {
		application.Cfg.NoteID = noteID
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	_, err = application.Capture(ctx, rawURL, title)
	return err
}

type captureOptions struct {
	URL     string
	Title   string
	NoteID  int64
	NoteSet bool
	Base    string
}

func parseCaptureArgs(args []string) (captureOptions, error) {
	var opts captureOptions
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch {
		case arg == "-h" || arg == "--help":
			return opts, flag.ErrHelp
		case arg == "--title" || arg == "-title":
			i++
			if i >= len(args) {
				return opts, errors.New("--title sem valor")
			}
			opts.Title = args[i]
		case strings.HasPrefix(arg, "--title="):
			opts.Title = strings.TrimPrefix(arg, "--title=")
		case arg == "--note" || arg == "-note":
			i++
			if i >= len(args) {
				return opts, errors.New("--note sem valor")
			}
			value, err := strconv.ParseInt(args[i], 10, 64)
			if err != nil {
				return opts, fmt.Errorf("--note: %w", err)
			}
			opts.NoteID, opts.NoteSet = value, true
		case strings.HasPrefix(arg, "--note="):
			value, err := strconv.ParseInt(strings.TrimPrefix(arg, "--note="), 10, 64)
			if err != nil {
				return opts, fmt.Errorf("--note: %w", err)
			}
			opts.NoteID, opts.NoteSet = value, true
		case arg == "--base" || arg == "-base":
			i++
			if i >= len(args) {
				return opts, errors.New("--base sem valor")
			}
			opts.Base = args[i]
		case strings.HasPrefix(arg, "--base="):
			opts.Base = strings.TrimPrefix(arg, "--base=")
		case strings.HasPrefix(arg, "-"):
			return opts, fmt.Errorf("opção desconhecida: %s", arg)
		default:
			if opts.URL != "" {
				return opts, fmt.Errorf("URL duplicada: %s", arg)
			}
			opts.URL = arg
		}
	}
	return opts, nil
}

func runCapture(args []string) error {
	opts, err := parseCaptureArgs(args)
	if err != nil {
		if errors.Is(err, flag.ErrHelp) {
			fmt.Print(usageText)
			return nil
		}
		return err
	}
	rawURL := strings.TrimSpace(opts.URL)
	if rawURL == "" {
		value, err := clipboard.Read()
		if err != nil {
			return fmt.Errorf("clipboard: %w", err)
		}
		rawURL = value
	}
	application, err := loadApp(os.Stdout, opts.Base)
	if err != nil {
		return err
	}
	if opts.NoteSet {
		application.Cfg.NoteID = opts.NoteID
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	_, err = application.Capture(ctx, rawURL, opts.Title)
	return err
}

func runLogin(args []string) error {
	fs := flag.NewFlagSet("login", flag.ContinueOnError)
	fs.SetOutput(os.Stderr)
	base := fs.String("base", "", "origem do app")
	email := fs.String("email", "", "e-mail da conta")
	if err := fs.Parse(args); err != nil {
		return err
	}
	application, err := loadApp(os.Stdout, *base)
	if err != nil {
		return err
	}
	if strings.TrimSpace(*email) != "" {
		application.Cfg.Email = strings.ToLower(strings.TrimSpace(*email))
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	return application.Login(ctx)
}

func runLogout() error {
	application, err := loadApp(os.Stdout, "")
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	return application.Logout(ctx)
}

func runStatus() error {
	application, err := loadApp(os.Stdout, "")
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	user, err := application.Status(ctx)
	if err != nil {
		return err
	}
	name := user.DisplayName
	if name == "" {
		name = user.Email
	}
	fmt.Printf("%s <%s> (%s)\n", name, user.Email, user.Role)
	return nil
}

func runOpen() error {
	application, err := loadApp(io.Discard, "")
	if err != nil {
		return err
	}
	return application.Open()
}

func runInstall() error {
	executable, err := os.Executable()
	if err != nil {
		return err
	}
	paths, err := install.Install(executable)
	if err != nil {
		return err
	}
	fmt.Printf("binário: %s\napps:    %s\nhandler: %s\n", paths.Binary, paths.Apps,
		filepath.Join(paths.Apps, "notai-capture-handler.desktop"))
	fmt.Println("atalho do GNOME: notai-capture capture")
	return nil
}

func runUninstall() error {
	paths, err := install.Uninstall()
	if err != nil {
		return err
	}
	fmt.Printf("removido de %s\n", paths.Binary)
	return nil
}

func runConfig(args []string) error {
	fs := flag.NewFlagSet("config", flag.ContinueOnError)
	fs.SetOutput(os.Stderr)
	base := fs.String("base", "", "origem do app")
	email := fs.String("email", "", "e-mail da conta")
	note := fs.Int64("note", 0, "nota fixa para as capturas (0 = nota nova)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	set := map[string]bool{}
	fs.Visit(func(f *flag.Flag) { set[f.Name] = true })
	if set["base"] {
		cfg.BaseURL = *base
	}
	if set["email"] {
		cfg.Email = *email
	}
	if set["note"] {
		cfg.NoteID = *note
	}
	path, err := config.Save(cfg)
	if err != nil {
		return err
	}
	fmt.Printf("config: %s\nbase:   %s\ne-mail: %s\nnota:   %d\n", path, cfg.BaseURL, cfg.Email, cfg.NoteID)
	return nil
}

func runTray() error {
	application, err := loadApp(io.Discard, "")
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()

	var busy sync.Mutex
	run := func(name string, action func(context.Context) error) {
		if !busy.TryLock() {
			notify.Send("NotAI", "Ainda estou ocupado com a captura anterior.", false)
			return
		}
		defer busy.Unlock()
		if err := action(ctx); err != nil {
			log.Printf("%s: %v", name, err)
		}
	}

	handlers := tray.Handlers{
		CaptureClipboard: func() {
			run("clipboard", func(ctx context.Context) error {
				rawURL, err := clipboard.Read()
				if err != nil {
					notify.Send("NotAI", err.Error(), true)
					return err
				}
				_, err = application.Capture(ctx, rawURL, "")
				return err
			})
		},
		CaptureDialog: func() {
			run("dialog", func(ctx context.Context) error {
				initial, _ := clipboard.Read()
				if _, err := link.Validate(initial); err != nil {
					initial = ""
				}
				rawURL, err := application.Prompt.Entry("NotAI", "URL para salvar", initial)
				if err != nil {
					return err
				}
				_, err = application.Capture(ctx, rawURL, "")
				return err
			})
		},
		Open: func() {
			if err := application.Open(); err != nil {
				notify.Send("NotAI", err.Error(), true)
			}
		},
		Login: func() {
			run("login", func(ctx context.Context) error {
				if err := application.Login(ctx); err != nil {
					notify.Send("NotAI", "Login falhou: "+err.Error(), true)
					return err
				}
				notify.Send("NotAI", "Conectado.", false)
				return nil
			})
		},
		Logout: func() {
			run("logout", func(ctx context.Context) error {
				if err := application.Logout(ctx); err != nil {
					notify.Send("NotAI", err.Error(), true)
					return err
				}
				notify.Send("NotAI", "Sessão removida deste computador.", false)
				return nil
			})
		},
		Quit: func() {
			log.Print("encerrando bandeja")
			stop()
		},
	}
	if err := tray.Run(ctx, handlers); err != nil {
		if errors.Is(err, tray.ErrAlreadyRunning) {
			return nil
		}
		return err
	}
	return nil
}

func setupLog() (*os.File, error) {
	dir := strings.TrimSpace(os.Getenv("XDG_STATE_HOME"))
	if dir == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return nil, err
		}
		dir = filepath.Join(home, ".local", "state")
	}
	dir = filepath.Join(dir, "notai-capture")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	path := filepath.Join(dir, "notai-capture.log")
	file, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, err
	}
	log.SetOutput(io.MultiWriter(os.Stderr, file))
	log.SetFlags(log.LstdFlags)
	return file, nil
}
