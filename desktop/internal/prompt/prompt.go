// Package prompt pede e-mail e senha: zenity quando há sessão gráfica, terminal como fallback.
package prompt

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
)

// ErrCanceled é o "Cancelar" do diálogo; não é falha de rede nem de login.
var ErrCanceled = errors.New("cancelado")

// Prompter permite substituir os diálogos nos testes.
type Prompter interface {
	Entry(title, text, initial string) (string, error)
	Password(title, text string) (string, error)
}

// Default usa zenity/terminal.
type Default struct{}

func (Default) Entry(title, text, initial string) (string, error) {
	if zenity := findZenity(); zenity != "" {
		args := []string{"--entry", "--title", title, "--text", text}
		if initial != "" {
			args = append(args, "--entry-text", initial)
		}
		output, err := exec.Command(zenity, args...).Output()
		if err == nil {
			return strings.TrimSpace(string(output)), nil
		}
		if canceled(err) {
			return "", ErrCanceled
		}
		return "", err
	}
	fmt.Fprintf(os.Stderr, "%s: ", text)
	line, err := bufio.NewReader(os.Stdin).ReadString('\n')
	if err != nil && !errors.Is(err, io.EOF) {
		return "", err
	}
	return strings.TrimSpace(line), nil
}

func (Default) Password(title, text string) (string, error) {
	if zenity := findZenity(); zenity != "" {
		output, err := exec.Command(zenity, "--password", "--title", title, "--text", text).Output()
		if err == nil {
			return strings.TrimSpace(string(output)), nil
		}
		if canceled(err) {
			return "", ErrCanceled
		}
		return "", err
	}
	return readSecret()
}

func findZenity() string {
	if os.Getenv("DISPLAY") == "" && os.Getenv("WAYLAND_DISPLAY") == "" {
		return ""
	}
	path, err := exec.LookPath("zenity")
	if err != nil {
		return ""
	}
	return path
}

func canceled(err error) bool {
	var exit *exec.ExitError
	return errors.As(err, &exit) && exit.ExitCode() == 1
}

func readSecret() (string, error) {
	fmt.Fprint(os.Stderr, "Senha: ")
	if stty, err := exec.LookPath("stty"); err == nil {
		_ = exec.Command(stty, "-echo").Run()
		defer func() { _ = exec.Command(stty, "echo").Run() }()
	}
	line, err := bufio.NewReader(os.Stdin).ReadString('\n')
	fmt.Fprintln(os.Stderr)
	if err != nil && !errors.Is(err, io.EOF) {
		return "", err
	}
	return strings.TrimSpace(line), nil
}
