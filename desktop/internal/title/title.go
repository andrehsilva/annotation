// Package title busca um título legível para o link, com fallback para o host.
package title

import (
	"context"
	"html"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	maxBytes  = 512 << 10
	maxRunes  = 200
	browserUA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 " +
		"(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

var (
	element = regexp.MustCompile(`(?is)<title[^>]*>(.*?)</title>`)
	client  = &http.Client{Timeout: 8 * time.Second}
)

// ForURL devolve o <title> da página ou, quando não dá, o hostname.
//
// É uma leitura best-effort: timeout curto, limite de bytes e só HTML. Nunca devolve erro;
// a captura pode seguir sem título.
func ForURL(ctx context.Context, raw string) string {
	parsed, err := url.Parse(raw)
	fallback := raw
	if err == nil && parsed.Hostname() != "" {
		fallback = parsed.Hostname()
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, raw, nil)
	if err != nil {
		return fallback
	}
	req.Header.Set("User-Agent", browserUA)
	req.Header.Set("Accept", "text/html,application/xhtml+xml")
	response, err := client.Do(req)
	if err != nil {
		return fallback
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fallback
	}
	contentType := strings.ToLower(response.Header.Get("Content-Type"))
	if contentType != "" && !strings.Contains(contentType, "text/html") &&
		!strings.Contains(contentType, "application/xhtml") {
		return fallback
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, maxBytes))
	if err != nil {
		return fallback
	}
	match := element.FindSubmatch(body)
	if len(match) < 2 {
		return fallback
	}
	found := strings.Join(strings.Fields(html.UnescapeString(string(match[1]))), " ")
	if found == "" {
		return fallback
	}
	return Truncate(found, maxRunes)
}

// Truncate corta por runas, não por bytes, e marca o corte.
func Truncate(text string, limit int) string {
	if limit <= 0 || utf8.RuneCountInString(text) <= limit {
		return text
	}
	runes := []rune(text)
	if limit == 1 {
		return "…"
	}
	return string(runes[:limit-1]) + "…"
}
