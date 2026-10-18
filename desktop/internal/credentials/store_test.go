package credentials

import (
	"errors"
	"os"
	"testing"
)

func TestFileStoreRoundTrip(t *testing.T) {
	t.Setenv("XDG_STATE_HOME", t.TempDir())
	store := FileStore{}

	if _, err := store.Get("ana@example.com"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("Get vazio = %v, quer ErrNotFound", err)
	}
	if err := store.Set("ana@example.com", "token-1"); err != nil {
		t.Fatal(err)
	}
	got, err := store.Get("ana@example.com")
	if err != nil {
		t.Fatal(err)
	}
	if got != "token-1" {
		t.Fatalf("Get = %q", got)
	}
	path, err := store.path("ana@example.com")
	if err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("permissão = %o", info.Mode().Perm())
	}
	if err := store.Set("outra@example.com", "token-2"); err != nil {
		t.Fatal(err)
	}
	second, err := store.Get("outra@example.com")
	if err != nil || second != "token-2" {
		t.Fatalf("segunda conta = %q, %v", second, err)
	}
	if err := store.Delete("ana@example.com"); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Get("ana@example.com"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("após Delete = %v, quer ErrNotFound", err)
	}
	if err := store.Delete("ana@example.com"); err != nil {
		t.Fatalf("Delete idempotente: %v", err)
	}
}
