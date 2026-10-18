//go:build !linux

package install

// Install fica pendente do adaptador nativo (registro no Windows, LaunchAgent no macOS).
func Install(executable string) (Paths, error) { return Paths{}, ErrUnsupported }

// Uninstall fica pendente do adaptador nativo.
func Uninstall() (Paths, error) { return Paths{}, ErrUnsupported }
