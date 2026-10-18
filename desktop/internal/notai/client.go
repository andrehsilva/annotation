// Package notai é o cliente HTTP do BFF. Cliente nativo não manda Origin, então o guard de
// escrita do backend (pensado para cookie no navegador) não barra estas requisições.
package notai

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"strings"
	"time"
)

// Version aparece no User-Agent e no `notai-capture version`.
const Version = "1.0.0"

const (
	cookieName = "notai_session"
	maxBody    = 4 << 20
)

// ErrUnauthorized é o sentinela que o app usa para pedir login de novo.
var ErrUnauthorized = errors.New("sessão expirada ou inválida")

// APIError carrega o `detail` que o FastAPI devolve.
type APIError struct {
	Status int
	Detail string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("%s (HTTP %d)", e.Detail, e.Status)
}

// Is faz errors.Is(err, ErrUnauthorized) funcionar sem perder o detalhe.
func (e *APIError) Is(target error) bool {
	return target == ErrUnauthorized && e.Status == http.StatusUnauthorized
}

// Client fala com uma origem do app. O cookie de sessão fica no cookiejar.
type Client struct {
	base *url.URL
	http *http.Client
}

// User é o subconjunto de /api/auth/me que o helper usa.
type User struct {
	ID          int64  `json:"id"`
	Email       string `json:"email"`
	DisplayName string `json:"display_name"`
	Role        string `json:"role"`
}

// Note é o subconjunto de NoteOut necessário para encadear o bloco.
type Note struct {
	ID    int64  `json:"id"`
	Title string `json:"title"`
}

// Block é o subconjunto de BlockOut devolvido pela criação.
type Block struct {
	ID     int64  `json:"id"`
	NoteID int64  `json:"note_id"`
	Type   string `json:"type"`
	URL    string `json:"url"`
}

// Captured é o resultado de uma captura completa.
type Captured struct {
	NoteID  int64
	BlockID int64
	Title   string
}

// NewClient valida a origem e monta o cliente. token pode ser vazio (login pendente).
func NewClient(baseURL, token string) (*Client, error) {
	baseURL = strings.TrimSpace(baseURL)
	parsed, err := url.Parse(baseURL)
	if err != nil {
		return nil, fmt.Errorf("base inválida: %w", err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return nil, fmt.Errorf("base precisa ser http:// ou https://: %q", baseURL)
	}
	if parsed.Host == "" {
		return nil, fmt.Errorf("base sem host: %q", baseURL)
	}
	parsed.Path, parsed.RawQuery, parsed.Fragment, parsed.User = "", "", "", nil
	client := &Client{base: parsed, http: &http.Client{Timeout: 30 * time.Second}}
	client.SetToken(token)
	return client, nil
}

// SetToken troca o cookie de sessão. String vazia limpa o cookiejar.
func (c *Client) SetToken(token string) {
	jar, _ := cookiejar.New(nil)
	c.http.Jar = jar
	if token == "" {
		return
	}
	jar.SetCookies(c.base, []*http.Cookie{{
		Name:  cookieName,
		Value: token,
		Path:  "/",
	}})
}

// BaseURL é a origem configurada, sem barra final.
func (c *Client) BaseURL() string {
	return c.base.String()
}

func (c *Client) endpoint(parts ...string) string {
	parsed := *c.base
	parsed.Path = "/" + strings.Join(parts, "/")
	return parsed.String()
}

// Login devolve o token do cookie e o usuário autenticado.
func (c *Client) Login(ctx context.Context, email, password string) (string, User, error) {
	var user User
	err := c.do(ctx, http.MethodPost, []string{"api", "auth", "login"}, map[string]string{
		"email":    email,
		"password": password,
	}, &user)
	if err != nil {
		return "", User{}, err
	}
	for _, cookie := range c.http.Jar.Cookies(c.base) {
		if cookie.Name == cookieName && cookie.Value != "" {
			return cookie.Value, user, nil
		}
	}
	return "", user, errors.New("login não devolveu o cookie de sessão")
}

// Me confere se a sessão atual ainda vale.
func (c *Client) Me(ctx context.Context) (User, error) {
	var user User
	err := c.do(ctx, http.MethodGet, []string{"api", "auth", "me"}, nil, &user)
	return user, err
}

// Logout revoga a sessão no servidor. Sem token, é no-op.
func (c *Client) Logout(ctx context.Context) error {
	return c.do(ctx, http.MethodPost, []string{"api", "auth", "logout"}, nil, nil)
}

// CreateNote cria uma nota vazia (o bloco entra em seguida, no mesmo fluxo).
func (c *Client) CreateNote(ctx context.Context, title string) (Note, error) {
	var note Note
	err := c.do(ctx, http.MethodPost, []string{"api", "notes"}, map[string]string{
		"title": title,
		"text":  "",
	}, &note)
	return note, err
}

// CreateURLBlock pendura um bloco do tipo url na nota.
func (c *Client) CreateURLBlock(ctx context.Context, noteID int64, rawURL, caption string) (Block, error) {
	var block Block
	err := c.do(ctx, http.MethodPost, []string{
		"api", "notes", fmt.Sprintf("%d", noteID), "blocks",
	}, map[string]string{
		"type":    "url",
		"url":     rawURL,
		"caption": caption,
	}, &block)
	return block, err
}

// Capture cria a nota (quando noteID é 0) e o bloco de link.
func (c *Client) Capture(ctx context.Context, noteID int64, rawURL, caption string) (Captured, error) {
	result := Captured{NoteID: noteID, Title: caption}
	if noteID == 0 {
		note, err := c.CreateNote(ctx, caption)
		if err != nil {
			return Captured{}, err
		}
		result.NoteID = note.ID
		if note.Title != "" {
			result.Title = note.Title
		}
	}
	block, err := c.CreateURLBlock(ctx, result.NoteID, rawURL, caption)
	if err != nil {
		return Captured{}, err
	}
	result.BlockID = block.ID
	return result, nil
}

func (c *Client) do(ctx context.Context, method string, parts []string, in, out any) error {
	var body io.Reader
	if in != nil {
		payload, err := json.Marshal(in)
		if err != nil {
			return err
		}
		body = bytes.NewReader(payload)
	}
	request, err := http.NewRequestWithContext(ctx, method, c.endpoint(parts...), body)
	if err != nil {
		return err
	}
	request.Header.Set("Accept", "application/json")
	request.Header.Set("User-Agent", "notai-capture/"+Version)
	if in != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	response, err := c.http.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return parseError(response)
	}
	if out == nil {
		_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 1<<20))
		return nil
	}
	if err := json.NewDecoder(io.LimitReader(response.Body, maxBody)).Decode(out); err != nil {
		return fmt.Errorf("resposta inválida de %s: %w", request.URL.Path, err)
	}
	return nil
}

func parseError(response *http.Response) error {
	body, _ := io.ReadAll(io.LimitReader(response.Body, 64<<10))
	detail := strings.TrimSpace(string(body))
	var payload struct {
		Detail json.RawMessage `json:"detail"`
	}
	if json.Unmarshal(body, &payload) == nil && len(payload.Detail) > 0 {
		var text string
		if json.Unmarshal(payload.Detail, &text) == nil {
			detail = strings.TrimSpace(text)
		} else {
			detail = strings.TrimSpace(string(payload.Detail))
		}
	}
	if detail == "" {
		detail = http.StatusText(response.StatusCode)
	}
	return &APIError{Status: response.StatusCode, Detail: detail}
}
