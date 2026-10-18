//go:build linux

package tray

import (
	"testing"
	"time"

	"github.com/godbus/dbus/v5"
)

func waitSignal(t *testing.T, channel <-chan struct{}, what string) {
	t.Helper()
	select {
	case <-channel:
	case <-time.After(time.Second):
		t.Fatalf("%s não aconteceu", what)
	}
}

func TestMenuLayoutAndProperties(t *testing.T) {
	menu := &dbusMenu{handlers: Handlers{}, quit: func() {}, revision: 1}

	revision, root, dbusErr := menu.GetLayout(0, -1, nil)
	if dbusErr != nil {
		t.Fatal(dbusErr)
	}
	if revision != 1 {
		t.Fatalf("revision = %d", revision)
	}
	if len(root.Children) != 6 {
		t.Fatalf("itens = %d", len(root.Children))
	}
	if root.Properties["children-display"].Value() != "submenu" {
		t.Fatalf("children-display = %v", root.Properties["children-display"].Value())
	}

	label, dbusErr := menu.GetProperty(1, "label")
	if dbusErr != nil {
		t.Fatal(dbusErr)
	}
	if label.Value() != "Salvar link do clipboard" {
		t.Fatalf("label = %v", label.Value())
	}
	kind, dbusErr := menu.GetProperty(3, "type")
	if dbusErr != nil {
		t.Fatal(dbusErr)
	}
	if kind.Value() != "separator" {
		t.Fatalf("type = %v", kind.Value())
	}
	if _, dbusErr := menu.GetProperty(99, "label"); dbusErr == nil {
		t.Fatal("id inexistente deveria devolver erro")
	}

	updates, dbusErr := menu.GetGroupProperties([]int32{1, 3}, nil)
	if dbusErr != nil {
		t.Fatal(dbusErr)
	}
	if len(updates) != 2 || updates[0].ID != 1 || updates[1].ID != 3 {
		t.Fatalf("updates = %+v", updates)
	}
}

func TestMenuEventsDispatch(t *testing.T) {
	captured := make(chan struct{}, 1)
	quitCalled := make(chan struct{}, 1)
	quit := make(chan struct{}, 1)
	menu := &dbusMenu{
		handlers: Handlers{
			CaptureClipboard: func() { captured <- struct{}{} },
			Quit:             func() { quitCalled <- struct{}{} },
		},
		quit:     func() { quit <- struct{}{} },
		revision: 1,
	}

	if dbusErr := menu.Event(1, "clicked", dbus.MakeVariant(""), 0); dbusErr != nil {
		t.Fatal(dbusErr)
	}
	waitSignal(t, captured, "captura")

	if dbusErr := menu.Event(6, "clicked", dbus.MakeVariant(""), 0); dbusErr != nil {
		t.Fatal(dbusErr)
	}
	waitSignal(t, quitCalled, "Quit")
	waitSignal(t, quit, "fechamento da bandeja")

	if dbusErr := menu.Event(1, "hovered", dbus.MakeVariant(""), 0); dbusErr != nil {
		t.Fatal(dbusErr)
	}
	select {
	case <-captured:
		t.Fatal("evento que não é clicked não deveria capturar")
	case <-time.After(50 * time.Millisecond):
	}
}

func TestMenuAboutToShow(t *testing.T) {
	menu := &dbusMenu{handlers: Handlers{}, quit: func() {}, revision: 1}
	show, dbusErr := menu.AboutToShow(0)
	if dbusErr != nil || show {
		t.Fatalf("AboutToShow = %v, %v", show, dbusErr)
	}
	updates, errors, dbusErr := menu.AboutToShowGroup([]int32{1})
	if dbusErr != nil || len(updates) != 0 || len(errors) != 0 {
		t.Fatalf("AboutToShowGroup = %v, %v, %v", updates, errors, dbusErr)
	}
}

func TestIconPixmaps(t *testing.T) {
	pixmaps := iconPixmaps()
	if len(pixmaps) != 2 {
		t.Fatalf("pixmaps = %d", len(pixmaps))
	}
	for _, pixmap := range pixmaps {
		if pixmap.Width != pixmap.Height {
			t.Fatalf("ícone não quadrado: %dx%d", pixmap.Width, pixmap.Height)
		}
		want := int(pixmap.Width) * int(pixmap.Height) * 4
		if len(pixmap.Data) != want {
			t.Fatalf("bytes = %d, quer %d", len(pixmap.Data), want)
		}
		if pixmap.Data[0] != 0 {
			t.Fatalf("canto deveria ser transparente: %x", pixmap.Data[0])
		}
		center := (int(pixmap.Height/2)*int(pixmap.Width) + int(pixmap.Width/2)) * 4
		if pixmap.Data[center] != 0xff {
			t.Fatalf("centro transparente")
		}
	}
}
