// Package config lê e grava o arquivo de configuração do notai-capture.
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

const (
	// DefaultBaseURL aponta para o backend local (uvicorn). Em produção, use o domínio do app.
	DefaultBaseURL = "http://localhost:8000"

	dirName  = "notai-capture"
	fileName = "config.json"
)

// Config é o que fica no disco: nenhum segredo aqui. O token mora no cofre do sistema.
type Config struct {
	BaseURL string `json:"base_url"`
	Email   string `json:"email"`
	// NoteID > 0 faz as capturas entrarem nessa nota em vez de criar uma nota por link.
	NoteID int64 `json:"note_id,omitempty"`
}

// Path devolve o caminho do config. NOTAI_CONFIG tem precedência (útil em testes).
func Path() (string, error) {
	if path := strings.TrimSpace(os.Getenv("NOTAI_CONFIG")); path != "" {
		return path, nil
	}
	dir := strings.TrimSpace(os.Getenv("XDG_CONFIG_HOME"))
	if dir == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", fmt.Errorf("descobrir home: %w", err)
		}
		dir = filepath.Join(home, ".config")
	}
	return filepath.Join(dir, dirName, fileName), nil
}

// Load devolve a configuração padrão quando o arquivo ainda não existe.
func Load() (Config, error) {
	path, err := Path()
	if err != nil {
		return Config{}, err
	}
	cfg := Config{BaseURL: DefaultBaseURL}
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		cfg.Normalize()
		return cfg, nil
	}
	if err != nil {
		return Config{}, fmt.Errorf("ler %s: %w", path, err)
	}
	if len(strings.TrimSpace(string(data))) > 0 {
		if err := json.Unmarshal(data, &cfg); err != nil {
			return Config{}, fmt.Errorf("config %s: %w", path, err)
		}
	}
	cfg.Normalize()
	return cfg, nil
}

// Normalize deixa a base como origem (sem caminho, query ou credenciais) e o e-mail em minúsculas.
func (c *Config) Normalize() {
	c.BaseURL = strings.TrimSpace(c.BaseURL)
	if c.BaseURL == "" {
		c.BaseURL = DefaultBaseURL
	}
	if parsed, err := url.Parse(c.BaseURL); err == nil && parsed.Host != "" &&
		(parsed.Scheme == "http" || parsed.Scheme == "https") {
		parsed.Host = strings.ToLower(parsed.Host)
		parsed.Path, parsed.RawQuery, parsed.Fragment, parsed.User = "", "", "", nil
		c.BaseURL = strings.TrimRight(parsed.String(), "/")
	}
	c.Email = strings.ToLower(strings.TrimSpace(c.Email))
	if c.NoteID < 0 {
		c.NoteID = 0
	}
}

// Save grava o config com permissão 0600, de forma atômica.
func Save(c Config) (string, error) {
	c.Normalize()
	path, err := Path()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return "", fmt.Errorf("criar %s: %w", filepath.Dir(path), err)
	}
	data, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return "", err
	}
	data = append(data, '\n')
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return "", fmt.Errorf("gravar %s: %w", tmp, err)
	}
	if err := os.Rename(tmp, path); err != nil {
		return "", fmt.Errorf("mover %s: %w", tmp, err)
	}
	return path, nil
}
