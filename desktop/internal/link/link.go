// Package link valida URLs de captura e interpreta o esquema notai://.
package link

import (
	"errors"
	"fmt"
	"net/url"
	"strings"
)

// ErrNotHTTP recusa esquemas que o app não sabe abrir.
var ErrNotHTTP = errors.New("só links http:// ou https://")

// Validate normaliza e confere uma URL antes de ela virar bloco.
func Validate(raw string) (string, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "", errors.New("link vazio")
	}
	parsed, err := url.Parse(raw)
	if err != nil {
		return "", fmt.Errorf("link inválido: %w", err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return "", ErrNotHTTP
	}
	if parsed.Host == "" {
		return "", errors.New("link sem host")
	}
	return parsed.String(), nil
}

// Capture é o que o handler notai:// entrega ao app.
type Capture struct {
	URL   string
	Title string
}

// ParseScheme reconhece notai://capture?url=...&title=....
//
// O segundo retorno diz se a entrada tinha o esquema notai:; o terceiro, se ela é válida.
func ParseScheme(raw string) (Capture, bool, error) {
	trimmed := strings.TrimSpace(raw)
	if !strings.HasPrefix(strings.ToLower(trimmed), "notai:") {
		return Capture{}, false, nil
	}
	parsed, err := url.Parse(trimmed)
	if err != nil {
		return Capture{}, true, fmt.Errorf("link notai:// inválido: %w", err)
	}
	action := parsed.Host
	if action == "" {
		action = strings.TrimPrefix(parsed.Opaque, "//")
		if action == "" {
			action = strings.TrimPrefix(parsed.Path, "/")
		}
	}
	if action != "capture" {
		return Capture{}, true, fmt.Errorf("ação desconhecida: %q", action)
	}
	target, err := Validate(parsed.Query().Get("url"))
	if err != nil {
		return Capture{}, true, err
	}
	title := strings.TrimSpace(parsed.Query().Get("title"))
	if runes := []rune(title); len(runes) > 300 {
		title = string(runes[:300])
	}
	return Capture{URL: target, Title: title}, true, nil
}
