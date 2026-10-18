//go:build linux

// Package notify mostra o resultado da captura sem depender da janela do app.
package notify

import (
	"os/exec"
	"strings"
)

func Send(summary, body string, critical bool) {
	path, err := exec.LookPath("notify-send")
	if err != nil {
		return
	}
	if runes := []rune(body); len(runes) > 500 {
		body = string(runes[:499]) + "…"
	}
	body = strings.TrimSpace(body)
	args := []string{"-a", "NotAI", "-t", "4000"}
	if critical {
		args = append(args, "-u", "critical")
	}
	args = append(args, summary, body)
	_ = exec.Command(path, args...).Run()
}
