//go:build !linux && !darwin && !windows

package clipboard

import "errors"

func Read() (string, error) {
	return "", errors.New("clipboard não suportado neste sistema")
}
