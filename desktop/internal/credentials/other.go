//go:build !linux

package credentials

// New nos sistemas sem Secret Service usa o arquivo 0600. O adaptador Windows deve trocar isto
// pelo Credential Manager/DPAPI quando existir.
func New() Store { return FileStore{} }
