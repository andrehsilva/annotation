// Package openurl abre a plataforma no navegador padrão.
package openurl

import (
	"fmt"
	"os/exec"
	"runtime"
)

func Open(raw string) error {
	var command *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		command = exec.Command("rundll32", "url.dll,FileProtocolHandler", raw)
	case "darwin":
		command = exec.Command("open", raw)
	default:
		command = exec.Command("xdg-open", raw)
	}
	if err := command.Run(); err != nil {
		return fmt.Errorf("abrir %s: %w", raw, err)
	}
	return nil
}
