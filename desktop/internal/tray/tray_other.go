//go:build !linux

package tray

import "context"

// Run fica sem efeito até existir o adaptador nativo (Shell_NotifyIcon no Windows, NSStatusItem
// no macOS). A CLI continua funcionando nesses sistemas.
func Run(ctx context.Context, handlers Handlers) error {
	return ErrUnsupported
}
