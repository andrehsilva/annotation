// Package tray expõe o ícone de bandeja. No Linux é SNI/D-Bus puro; os demais SOs têm adaptador.
package tray

import "errors"

// ErrAlreadyRunning evita duas bandejas no mesmo usuário.
var ErrAlreadyRunning = errors.New("a bandeja do NotAI já está rodando")

// ErrUnsupported aparece quando o SO ainda não tem adaptador de bandeja.
var ErrUnsupported = errors.New("bandeja não suportada neste sistema")

// Handlers são as ações disparadas pelo menu. Cada uma roda em goroutine própria.
type Handlers struct {
	CaptureClipboard func()
	CaptureDialog    func()
	Open             func()
	Login            func()
	Logout           func()
	Quit             func()
}
