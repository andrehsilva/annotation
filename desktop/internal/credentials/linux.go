//go:build linux

package credentials

import (
	"context"
	"errors"
	"os/exec"
	"strings"
	"time"
)

const service = "notai-capture"

type linuxStore struct {
	file FileStore
}

// New usa o Secret Service (secret-tool) e cai para arquivo 0600 se ele não estiver disponível.
func New() Store { return linuxStore{} }

func (s linuxStore) Get(email string) (string, error) {
	token, err := secretLookup(email)
	if err == nil && token != "" {
		return token, nil
	}
	return s.file.Get(email)
}

func (s linuxStore) Set(email, token string) error {
	if err := secretStore(email, token); err == nil {
		return nil
	}
	return s.file.Set(email, token)
}

func (s linuxStore) Delete(email string) error {
	_ = secretClear(email)
	return s.file.Delete(email)
}

func runSecret(stdin string, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, "secret-tool", args...)
	command.WaitDelay = time.Second
	if stdin != "" {
		command.Stdin = strings.NewReader(stdin)
	}
	output, err := command.Output()
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(output)), nil
}

func secretLookup(email string) (string, error) {
	return runSecret("", "lookup", "service", service, "account", email)
}

func secretStore(email, token string) error {
	if token == "" {
		return errors.New("token vazio")
	}
	_, err := runSecret(token, "store", "--label", "NotAI Capture ("+email+")", "service", service, "account", email)
	return err
}

func secretClear(email string) error {
	_, err := runSecret("", "clear", "service", service, "account", email)
	return err
}
