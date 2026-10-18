//go:build linux

// Package clipboard lê o texto copiado. Wayland usa wl-paste; X11 cai para xclip/xsel.
package clipboard

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
	"time"
)

func Read() (string, error) {
	candidates := []struct {
		name string
		args []string
	}{
		{"wl-paste", []string{"--no-newline"}},
		{"xclip", []string{"-selection", "clipboard", "-o"}},
		{"xsel", []string{"--clipboard", "--output"}},
	}
	var problems []string
	for _, candidate := range candidates {
		if _, err := exec.LookPath(candidate.name); err != nil {
			continue
		}
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		output, err := exec.CommandContext(ctx, candidate.name, candidate.args...).Output()
		cancel()
		if err != nil {
			problems = append(problems, fmt.Sprintf("%s: %v", candidate.name, err))
			continue
		}
		text := strings.TrimSpace(string(output))
		if text != "" {
			return text, nil
		}
	}
	if len(problems) == 0 {
		return "", fmt.Errorf("nenhum leitor de clipboard encontrado (wl-paste, xclip ou xsel)")
	}
	return "", fmt.Errorf("não consegui ler o clipboard: %s", strings.Join(problems, "; "))
}
