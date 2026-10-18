// Package install copia o binário e os arquivos .desktop para os diretórios XDG.
package install

import "errors"

// ErrUnsupported aparece nos SOs sem instalador automático ainda.
var ErrUnsupported = errors.New("instalação automática não suportada neste sistema")

// Paths diz onde cada peça foi instalada.
type Paths struct {
	Binary    string
	Apps      string
	Icon      string
	Autostart string
}
