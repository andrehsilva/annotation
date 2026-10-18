//go:build windows

package clipboard

import (
	"fmt"
	"os/exec"
	"strings"
)

func Read() (string, error) {
	const script = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"
	for _, shell := range []string{"powershell.exe", "pwsh.exe"} {
		if _, err := exec.LookPath(shell); err != nil {
			continue
		}
		output, err := exec.Command(shell, "-NoProfile", "-NonInteractive", "-Command", script).Output()
		if err != nil {
			return "", fmt.Errorf("%s: %w", shell, err)
		}
		return strings.TrimSpace(string(output)), nil
	}
	return "", fmt.Errorf("PowerShell não encontrado para ler o clipboard")
}
