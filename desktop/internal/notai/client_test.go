package notai

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

func writeJSON(t *testing.T, w http.ResponseWriter, status int, value any) {
	t.Helper()
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil {
		t.Errorf("encode: %v", err)
	}
}

func requireCookie(t *testing.T, w http.ResponseWriter, r *http.Request, want string) bool {
	t.Helper()
	cookie, err := r.Cookie(cookieName)
	if err != nil || cookie.Value != want {
		http.Error(w, `{"detail":"sessão inválida"}`, http.StatusUnauthorized)
		return false
	}
	return true
}

func TestLoginMeAndCapture(t *testing.T) {
	var mu sync.Mutex
	var origins []string
	logins, notes, blocks := 0, 0, 0

	mux := http.NewServeMux()
	mux.HandleFunc("/api/auth/login", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		logins++
		origins = append(origins, r.Header.Get("Origin"))
		mu.Unlock()
		if r.Method != http.MethodPost {
			t.Errorf("login method = %s", r.Method)
		}
		var body map[string]string
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("login body: %v", err)
		}
		if body["email"] != "ana@example.com" || body["password"] != "segredo" {
			t.Errorf("login body = %+v", body)
		}
		http.SetCookie(w, &http.Cookie{Name: cookieName, Value: "token-1", Path: "/", HttpOnly: true})
		writeJSON(t, w, http.StatusOK, map[string]any{
			"id": 1, "email": "ana@example.com", "display_name": "Ana", "role": "user",
		})
	})
	mux.HandleFunc("/api/auth/me", func(w http.ResponseWriter, r *http.Request) {
		if !requireCookie(t, w, r, "token-1") {
			return
		}
		writeJSON(t, w, http.StatusOK, map[string]any{
			"id": 1, "email": "ana@example.com", "display_name": "Ana", "role": "user",
		})
	})
	mux.HandleFunc("/api/notes", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		notes++
		mu.Unlock()
		if !requireCookie(t, w, r, "token-1") {
			return
		}
		var body map[string]string
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("note body: %v", err)
		}
		if body["title"] != "Título" || body["text"] != "" {
			t.Errorf("note body = %+v", body)
		}
		writeJSON(t, w, http.StatusCreated, map[string]any{"id": 7, "title": "Título"})
	})
	mux.HandleFunc("/api/notes/7/blocks", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		blocks++
		mu.Unlock()
		if !requireCookie(t, w, r, "token-1") {
			return
		}
		var body map[string]string
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("block body: %v", err)
		}
		if body["type"] != "url" || body["url"] != "https://example.com/a" || body["caption"] != "Título" {
			t.Errorf("block body = %+v", body)
		}
		writeJSON(t, w, http.StatusCreated, map[string]any{
			"id": 9, "note_id": 7, "type": "url", "url": body["url"],
		})
	})

	server := httptest.NewServer(mux)
	defer server.Close()

	client, err := NewClient(server.URL+"/", "")
	if err != nil {
		t.Fatal(err)
	}
	if client.BaseURL() != server.URL {
		t.Fatalf("BaseURL = %q", client.BaseURL())
	}

	token, user, err := client.Login(context.Background(), "ana@example.com", "segredo")
	if err != nil {
		t.Fatal(err)
	}
	if token != "token-1" || user.Email != "ana@example.com" {
		t.Fatalf("login = %q, %+v", token, user)
	}
	client.SetToken(token)

	me, err := client.Me(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if me.DisplayName != "Ana" {
		t.Fatalf("me = %+v", me)
	}

	captured, err := client.Capture(context.Background(), 0, "https://example.com/a", "Título")
	if err != nil {
		t.Fatal(err)
	}
	if captured.NoteID != 7 || captured.BlockID != 9 || captured.Title != "Título" {
		t.Fatalf("captured = %+v", captured)
	}

	mu.Lock()
	defer mu.Unlock()
	if logins != 1 || notes != 1 || blocks != 1 {
		t.Fatalf("logins=%d notes=%d blocks=%d", logins, notes, blocks)
	}
	for _, origin := range origins {
		if origin != "" {
			t.Fatalf("cliente nativo mandou Origin: %q", origin)
		}
	}
}

func TestUnauthorizedSentinel(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(t, w, http.StatusUnauthorized, map[string]string{"detail": "Sessão inválida"})
	}))
	defer server.Close()

	client, err := NewClient(server.URL, "expirado")
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.Me(context.Background())
	if !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("err = %v, quer ErrUnauthorized", err)
	}
	var apiErr *APIError
	if !errors.As(err, &apiErr) || apiErr.Status != http.StatusUnauthorized {
		t.Fatalf("err = %#v", err)
	}
	if apiErr.Detail != "Sessão inválida" {
		t.Fatalf("detail = %q", apiErr.Detail)
	}
}

func TestSetTokenEmptyClearsCookie(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if _, err := r.Cookie(cookieName); err != nil {
			writeJSON(t, w, http.StatusUnauthorized, map[string]string{"detail": "sem cookie"})
			return
		}
		writeJSON(t, w, http.StatusOK, map[string]any{"id": 1, "email": "ana@example.com"})
	}))
	defer server.Close()

	client, err := NewClient(server.URL, "token")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := client.Me(context.Background()); err != nil {
		t.Fatal(err)
	}
	client.SetToken("")
	if _, err := client.Me(context.Background()); !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("após limpar: %v", err)
	}
}

func TestLogout(t *testing.T) {
	called := false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/auth/logout" || r.Method != http.MethodPost {
			t.Errorf("%s %s", r.Method, r.URL.Path)
		}
		if !requireCookie(t, w, r, "token") {
			return
		}
		called = true
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	client, err := NewClient(server.URL, "token")
	if err != nil {
		t.Fatal(err)
	}
	if err := client.Logout(context.Background()); err != nil {
		t.Fatal(err)
	}
	if !called {
		t.Fatal("logout não chegou ao servidor")
	}
}

func TestCaptureExistingNoteSkipsNoteCreation(t *testing.T) {
	noteCreated := false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/notes":
			noteCreated = true
			writeJSON(t, w, http.StatusCreated, map[string]any{"id": 1})
		case "/api/notes/42/blocks":
			writeJSON(t, w, http.StatusCreated, map[string]any{"id": 2, "note_id": 42})
		default:
			t.Errorf("caminho inesperado: %s", r.URL.Path)
		}
	}))
	defer server.Close()

	client, err := NewClient(server.URL, "token")
	if err != nil {
		t.Fatal(err)
	}
	captured, err := client.Capture(context.Background(), 42, "https://example.com", "X")
	if err != nil {
		t.Fatal(err)
	}
	if noteCreated {
		t.Fatal("não deveria criar nota quando noteID > 0")
	}
	if captured.NoteID != 42 || captured.BlockID != 2 {
		t.Fatalf("captured = %+v", captured)
	}
}

func TestAPIErrorWithValidationDetail(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(t, w, http.StatusUnprocessableEntity, map[string]any{
			"detail": []map[string]any{{"loc": []string{"body", "title"}, "msg": "too long"}},
		})
	}))
	defer server.Close()

	client, err := NewClient(server.URL, "token")
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.CreateNote(context.Background(), strings.Repeat("x", 300))
	var apiErr *APIError
	if !errors.As(err, &apiErr) || apiErr.Status != http.StatusUnprocessableEntity {
		t.Fatalf("err = %#v", err)
	}
	if !strings.Contains(apiErr.Detail, "too long") {
		t.Fatalf("detail = %q", apiErr.Detail)
	}
}

func TestLoginWithoutCookie(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(t, w, http.StatusOK, map[string]any{"id": 1, "email": "ana@example.com"})
	}))
	defer server.Close()

	client, err := NewClient(server.URL, "")
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := client.Login(context.Background(), "ana@example.com", "x"); err == nil {
		t.Fatal("login sem Set-Cookie deveria falhar")
	}
}

func TestNewClientRejectsBadBase(t *testing.T) {
	for _, base := range []string{"", "example.com", "ftp://example.com", "http://"} {
		if _, err := NewClient(base, ""); err == nil {
			t.Fatalf("NewClient(%q) deveria falhar", base)
		}
	}
}
