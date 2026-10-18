//go:build darwin

package clipboard

import (
	"fmt"
	"os/exec"
	"strings"
)

func Read() (string, error) {
	output, err := exec.Command("pbpaste").Output()
	if err != nil {
		return "", fmt.Errorf("pbpaste: %w", err)
	}
	return strings.TrimSpace(string(output)), nil
}
