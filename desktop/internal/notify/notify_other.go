//go:build !linux

package notify

// Send é no-op fora do Linux; o adaptador de cada SO pode trocar por toast/notificação nativa.
func Send(summary, body string, critical bool) {}
