// Package credentials guarda o token de sessão fora do config.
package credentials

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ErrNotFound separa "ainda não fez login" de uma falha real do cofre.
var ErrNotFound = errors.New("credencial não encontrada")

// Store é o cofre por conta.
type Store interface {
	Get(email string) (string, error)
	Set(email, token string) error
	Delete(email string) error
}

// FileStore é o fallback portátil: um arquivo 0600 por e-mail.
type FileStore struct{}

func (FileStore) path(email string) (string, error) {
	dir := strings.TrimSpace(os.Getenv("XDG_STATE_HOME"))
	if dir == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", fmt.Errorf("descobrir home: %w", err)
		}
		dir = filepath.Join(home, ".local", "state")
	}
	sum := sha256.Sum256([]byte(strings.ToLower(strings.TrimSpace(email))))
	name := "token-" + hex.EncodeToString(sum[:8])
	return filepath.Join(dir, "notai-capture", name), nil
}

func (s FileStore) Get(email string) (string, error) {
	path, err := s.path(email)
	if err != nil {
		return "", err
	}
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return "", ErrNotFound
	}
	if err != nil {
		return "", err
	}
	token := strings.TrimSpace(string(data))
	if token == "" {
		return "", ErrNotFound
	}
	return token, nil
}

func (s FileStore) Set(email, token string) error {
	path, err := s.path(email)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("criar %s: %w", filepath.Dir(path), err)
	}
	if err := os.WriteFile(path, []byte(token+"\n"), 0o600); err != nil {
		return fmt.Errorf("gravar %s: %w", path, err)
	}
	return os.Chmod(path, 0o600)
}

func (s FileStore) Delete(email string) error {
	path, err := s.path(email)
	if err != nil {
		return err
	}
	if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}
