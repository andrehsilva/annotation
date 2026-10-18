package app

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/andrehsilva/annotation/desktop/internal/config"
	"github.com/andrehsilva/annotation/desktop/internal/credentials"
)

type memoryStore struct {
	mu     sync.Mutex
	values map[string]string
}

func newMemoryStore() *memoryStore {
	return &memoryStore{values: map[string]string{}}
}

func (m *memoryStore) Get(email string) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	value, ok := m.values[email]
	if !ok {
		return "", credentials.ErrNotFound
	}
	return value, nil
}

func (m *memoryStore) Set(email, token string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.values[email] = token
	return nil
}

func (m *memoryStore) Delete(email string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.values, email)
	return nil
}

type fakePrompt struct {
	email      string
	password   string
	err        error
	entryCalls int
	passCalls  int
}

func (f *fakePrompt) Entry(title, text, initial string) (string, error) {
	f.entryCalls++
	if f.err != nil {
		return "", f.err
	}
	return f.email, nil
}

func (f *fakePrompt) Password(title, text string) (string, error) {
	f.passCalls++
	if f.err != nil {
		return "", f.err
	}
	return f.password, nil
}

type fakeServer struct {
	mu                    sync.Mutex
	logins, notes, blocks int
	logouts, requests     int
}

func writeJSON(t *testing.T, w http.ResponseWriter, status int, value any) {
	t.Helper()
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil {
		t.Errorf("encode: %v", err)
	}
}

func (s *fakeServer) cookie(t *testing.T, w http.ResponseWriter, r *http.Request) bool {
	t.Helper()
	cookie, err := r.Cookie("notai_session")
	if err != nil || cookie.Value != "fresh" {
		writeJSON(t, w, http.StatusUnauthorized, map[string]string{"detail": "sessão expirada"})
		return false
	}
	return true
}

func newFakeServer(t *testing.T) (*fakeServer, *httptest.Server) {
	t.Helper()
	state := &fakeServer{}
	mux := http.NewServeMux()

	mux.HandleFunc("/api/auth/login", func(w http.ResponseWriter, r *http.Request) {
		state.mu.Lock()
		state.logins++
		state.requests++
		state.mu.Unlock()
		var body map[string]string
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("login body: %v", err)
		}
		if body["email"] != "ana@example.com" || body["password"] != "segredo" {
			t.Errorf("login = %+v", body)
		}
		http.SetCookie(w, &http.Cookie{Name: "notai_session", Value: "fresh", Path: "/"})
		writeJSON(t, w, http.StatusOK, map[string]any{
			"id": 1, "email": "ana@example.com", "display_name": "Ana", "role": "user",
		})
	})

	mux.HandleFunc("/api/auth/me", func(w http.ResponseWriter, r *http.Request) {
		state.mu.Lock()
		state.requests++
		state.mu.Unlock()
		if !state.cookie(t, w, r) {
			return
		}
		writeJSON(t, w, http.StatusOK, map[string]any{
			"id": 1, "email": "ana@example.com", "display_name": "Ana", "role": "user",
		})
	})

	mux.HandleFunc("/api/notes", func(w http.ResponseWriter, r *http.Request) {
		state.mu.Lock()
		state.notes++
		state.requests++
		state.mu.Unlock()
		if !state.cookie(t, w, r) {
			return
		}
		var body map[string]string
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("note body: %v", err)
		}
		if body["title"] != "Título" {
			t.Errorf("título = %q", body["title"])
		}
		writeJSON(t, w, http.StatusCreated, map[string]any{"id": 7, "title": body["title"]})
	})

	mux.HandleFunc("/api/notes/7/blocks", func(w http.ResponseWriter, r *http.Request) {
		state.mu.Lock()
		state.blocks++
		state.requests++
		state.mu.Unlock()
		if !state.cookie(t, w, r) {
			return
		}
		var body map[string]string
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("block body: %v", err)
		}
		if body["type"] != "url" || body["url"] != "https://example.com/a" {
			t.Errorf("bloco = %+v", body)
		}
		writeJSON(t, w, http.StatusCreated, map[string]any{
			"id": 9, "note_id": 7, "type": "url", "url": body["url"],
		})
	})

	mux.HandleFunc("/api/auth/logout", func(w http.ResponseWriter, r *http.Request) {
		state.mu.Lock()
		state.logouts++
		state.requests++
		state.mu.Unlock()
		if !state.cookie(t, w, r) {
			return
		}
		w.WriteHeader(http.StatusNoContent)
	})

	server := httptest.NewServer(mux)
	t.Cleanup(server.Close)
	return state, server
}

func newTestApp(t *testing.T, server *httptest.Server, store credentials.Store, email string) (*App, *bytes.Buffer, *fakePrompt) {
	t.Helper()
	t.Setenv("NOTAI_CONFIG", filepath.Join(t.TempDir(), "config.json"))
	t.Setenv("NOTAI_PASSWORD", "segredo")
	t.Setenv("NOTAI_EMAIL", "")
	prompter := &fakePrompt{email: "ana@example.com", password: "segredo"}
	out := &bytes.Buffer{}
	application, err := New(config.Config{BaseURL: server.URL, Email: email}, store, prompter, out)
	if err != nil {
		t.Fatal(err)
	}
	return application, out, prompter
}

func TestCaptureRetriesAfterExpiredToken(t *testing.T) {
	state, server := newFakeServer(t)
	store := newMemoryStore()
	if err := store.Set("ana@example.com", "expired"); err != nil {
		t.Fatal(err)
	}
	application, _, _ := newTestApp(t, server, store, "ana@example.com")

	var notices []string
	application.Notifier = func(summary, body string, critical bool) {
		notices = append(notices, body)
	}

	captured, err := application.Capture(context.Background(), "https://example.com/a", "Título")
	if err != nil {
		t.Fatal(err)
	}
	if captured.NoteID != 7 || captured.BlockID != 9 {
		t.Fatalf("captured = %+v", captured)
	}
	state.mu.Lock()
	defer state.mu.Unlock()
	if state.logins != 1 {
		t.Fatalf("logins = %d", state.logins)
	}
	if state.notes != 2 {
		t.Fatalf("notes = %d (primeira 401 + retry)", state.notes)
	}
	if state.blocks != 1 {
		t.Fatalf("blocks = %d", state.blocks)
	}
	token, err := store.Get("ana@example.com")
	if err != nil || token != "fresh" {
		t.Fatalf("token salvo = %q, %v", token, err)
	}
	if len(notices) != 1 || !strings.Contains(notices[0], "Salvo") {
		t.Fatalf("notices = %v", notices)
	}
}

func TestCapturePromptsForEmailWhenConfigIsEmpty(t *testing.T) {
	state, server := newFakeServer(t)
	store := newMemoryStore()
	application, _, prompter := newTestApp(t, server, store, "")
	application.Notifier = func(string, string, bool) {}

	if _, err := application.Capture(context.Background(), "https://example.com/a", "Título"); err != nil {
		t.Fatal(err)
	}
	if prompter.entryCalls != 1 {
		t.Fatalf("entryCalls = %d", prompter.entryCalls)
	}
	if prompter.passCalls != 0 {
		t.Fatalf("passCalls = %d (NOTAI_PASSWORD deveria evitar o diálogo)", prompter.passCalls)
	}
	state.mu.Lock()
	logins := state.logins
	state.mu.Unlock()
	if logins != 1 {
		t.Fatalf("logins = %d", logins)
	}
	loaded, err := config.Load()
	if err != nil {
		t.Fatal(err)
	}
	if loaded.Email != "ana@example.com" {
		t.Fatalf("e-mail salvo = %q", loaded.Email)
	}
}

func TestCaptureRejectsInvalidURLBeforeAnyRequest(t *testing.T) {
	state, server := newFakeServer(t)
	store := newMemoryStore()
	application, _, _ := newTestApp(t, server, store, "ana@example.com")

	_, err := application.Capture(context.Background(), "javascript:alert(1)", "")
	if err == nil {
		t.Fatal("URL inválida deveria falhar")
	}
	state.mu.Lock()
	defer state.mu.Unlock()
	if state.requests != 0 {
		t.Fatalf("requests = %d", state.requests)
	}
}

func TestLogoutRevokesAndClears(t *testing.T) {
	state, server := newFakeServer(t)
	store := newMemoryStore()
	if err := store.Set("ana@example.com", "fresh"); err != nil {
		t.Fatal(err)
	}
	application, _, _ := newTestApp(t, server, store, "ana@example.com")

	if err := application.Logout(context.Background()); err != nil {
		t.Fatal(err)
	}
	if application.Token() {
		t.Fatal("token ainda carregado")
	}
	if _, err := store.Get("ana@example.com"); !errors.Is(err, credentials.ErrNotFound) {
		t.Fatalf("token local = %v", err)
	}
	state.mu.Lock()
	defer state.mu.Unlock()
	if state.logouts != 1 {
		t.Fatalf("logouts = %d", state.logouts)
	}
}

func TestStatusReturnsUser(t *testing.T) {
	state, server := newFakeServer(t)
	store := newMemoryStore()
	if err := store.Set("ana@example.com", "fresh"); err != nil {
		t.Fatal(err)
	}
	application, _, _ := newTestApp(t, server, store, "ana@example.com")

	user, err := application.Status(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if user.Email != "ana@example.com" || user.DisplayName != "Ana" {
		t.Fatalf("user = %+v", user)
	}
	state.mu.Lock()
	defer state.mu.Unlock()
	if state.logins != 0 {
		t.Fatalf("logins = %d", state.logins)
	}
}
