package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadMissingUsesDefault(t *testing.T) {
	t.Setenv("NOTAI_CONFIG", filepath.Join(t.TempDir(), "config.json"))
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.BaseURL != DefaultBaseURL {
		t.Fatalf("BaseURL = %q", cfg.BaseURL)
	}
	if cfg.Email != "" || cfg.NoteID != 0 {
		t.Fatalf("config inesperada: %+v", cfg)
	}
}

func TestSaveNormalizesAndProtects(t *testing.T) {
	path := filepath.Join(t.TempDir(), "sub", "config.json")
	t.Setenv("NOTAI_CONFIG", path)

	cfg := Config{
		BaseURL: "https://NotAI.Example/path?x=1#frag",
		Email:   "  Ana@Example.COM ",
		NoteID:  7,
	}
	saved, err := Save(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if saved != path {
		t.Fatalf("saved = %q, quer %q", saved, path)
	}
	loaded, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if loaded.BaseURL != "https://notai.example" {
		t.Fatalf("BaseURL carregada = %q", loaded.BaseURL)
	}
	if loaded.Email != "ana@example.com" {
		t.Fatalf("Email = %q", loaded.Email)
	}
	if loaded.NoteID != 7 {
		t.Fatalf("NoteID = %d", loaded.NoteID)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("permissão = %o", info.Mode().Perm())
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "token") || strings.Contains(string(data), "senha") {
		t.Fatalf("config não pode guardar segredo: %s", data)
	}
}

func TestNormalizeEmptyAndNegative(t *testing.T) {
	cfg := Config{BaseURL: "  ", Email: "X@Y", NoteID: -1}
	cfg.Normalize()
	if cfg.BaseURL != DefaultBaseURL {
		t.Fatalf("BaseURL = %q", cfg.BaseURL)
	}
	if cfg.Email != "x@y" {
		t.Fatalf("Email = %q", cfg.Email)
	}
	if cfg.NoteID != 0 {
		t.Fatalf("NoteID = %d", cfg.NoteID)
	}
}
