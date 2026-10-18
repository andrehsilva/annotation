//go:build linux

package install

import (
	"embed"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
)

//go:embed assets/*
var assets embed.FS

const (
	appFile       = "notai-capture.desktop"
	handlerFile   = "notai-capture-handler.desktop"
	autostartFile = "notai-capture-autostart.desktop"
	iconFile      = "notai-capture.svg"
)

// DefaultPaths respeita XDG_DATA_HOME, XDG_CONFIG_HOME e XDG_BIN_HOME.
func DefaultPaths() (Paths, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return Paths{}, fmt.Errorf("descobrir home: %w", err)
	}
	data := os.Getenv("XDG_DATA_HOME")
	if data == "" {
		data = filepath.Join(home, ".local", "share")
	}
	config := os.Getenv("XDG_CONFIG_HOME")
	if config == "" {
		config = filepath.Join(home, ".config")
	}
	bin := os.Getenv("XDG_BIN_HOME")
	if bin == "" {
		bin = filepath.Join(home, ".local", "bin")
	}
	return Paths{
		Binary:    filepath.Join(bin, "notai-capture"),
		Apps:      filepath.Join(data, "applications"),
		Icon:      filepath.Join(data, "icons", "hicolor", "scalable", "apps", iconFile),
		Autostart: filepath.Join(config, "autostart"),
	}, nil
}

// Install copia o executável atual e escreve menu, handler notai://, autostart e ícone.
func Install(executable string) (Paths, error) {
	paths, err := DefaultPaths()
	if err != nil {
		return Paths{}, err
	}
	for _, dir := range []string{
		filepath.Dir(paths.Binary),
		paths.Apps,
		filepath.Dir(paths.Icon),
		paths.Autostart,
	} {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return Paths{}, fmt.Errorf("criar %s: %w", dir, err)
		}
	}
	if err := copyExecutable(executable, paths.Binary); err != nil {
		return Paths{}, err
	}
	files := []struct {
		asset string
		dest  string
	}{
		{appFile, filepath.Join(paths.Apps, appFile)},
		{handlerFile, filepath.Join(paths.Apps, handlerFile)},
		{autostartFile, filepath.Join(paths.Autostart, autostartFile)},
		{iconFile, paths.Icon},
	}
	for _, file := range files {
		if err := writeAsset(file.asset, file.dest); err != nil {
			return Paths{}, err
		}
	}
	if xdgMime, err := exec.LookPath("xdg-mime"); err == nil {
		_ = exec.Command(xdgMime, "default", handlerFile, "x-scheme-handler/notai").Run()
	}
	if update, err := exec.LookPath("update-desktop-database"); err == nil {
		_ = exec.Command(update, paths.Apps).Run()
	}
	return paths, nil
}

// Uninstall remove os arquivos instalados. Config e token ficam (use `logout` para o token).
func Uninstall() (Paths, error) {
	paths, err := DefaultPaths()
	if err != nil {
		return Paths{}, err
	}
	for _, path := range []string{
		paths.Binary,
		filepath.Join(paths.Apps, appFile),
		filepath.Join(paths.Apps, handlerFile),
		filepath.Join(paths.Autostart, autostartFile),
		paths.Icon,
	} {
		if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
			return Paths{}, fmt.Errorf("remover %s: %w", path, err)
		}
	}
	if update, err := exec.LookPath("update-desktop-database"); err == nil {
		_ = exec.Command(update, paths.Apps).Run()
	}
	return paths, nil
}

func writeAsset(name, dest string) error {
	data, err := assets.ReadFile("assets/" + name)
	if err != nil {
		return fmt.Errorf("asset %s: %w", name, err)
	}
	if err := os.WriteFile(dest, data, 0o644); err != nil {
		return fmt.Errorf("gravar %s: %w", dest, err)
	}
	return os.Chmod(dest, 0o644)
}

func copyExecutable(source, dest string) error {
	sourceFile, err := os.Open(source)
	if err != nil {
		return fmt.Errorf("abrir %s: %w", source, err)
	}
	defer sourceFile.Close()
	info, err := sourceFile.Stat()
	if err != nil {
		return fmt.Errorf("stat %s: %w", source, err)
	}
	if current, err := os.Stat(dest); err == nil && os.SameFile(info, current) {
		return nil
	}
	tmp, err := os.CreateTemp(filepath.Dir(dest), ".notai-capture-*")
	if err != nil {
		return fmt.Errorf("criar temporário em %s: %w", filepath.Dir(dest), err)
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)

	if _, err := io.Copy(tmp, sourceFile); err != nil {
		tmp.Close()
		return fmt.Errorf("copiar para %s: %w", tmpName, err)
	}
	if err := tmp.Chmod(0o755); err != nil {
		tmp.Close()
		return fmt.Errorf("chmod %s: %w", tmpName, err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("fechar %s: %w", tmpName, err)
	}
	if err := os.Rename(tmpName, dest); err != nil {
		return fmt.Errorf("mover para %s: %w", dest, err)
	}
	return nil
}
