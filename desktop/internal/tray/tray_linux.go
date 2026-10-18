//go:build linux

package tray

import (
	"context"
	"fmt"
	"log"
	"os"
	"sync"
	"time"

	"github.com/godbus/dbus/v5"
	"github.com/godbus/dbus/v5/prop"
)

const (
	appBusName = "org.notai.Capture"
	itemPath   = dbus.ObjectPath("/StatusNotifierItem")
	menuPath   = dbus.ObjectPath("/MenuBar")

	itemInterface = "org.kde.StatusNotifierItem"
	menuInterface = "com.canonical.dbusmenu"

	watcherName = "org.kde.StatusNotifierWatcher"
	watcherPath = dbus.ObjectPath("/StatusNotifierWatcher")
)

// Run registra o ícone no StatusNotifierWatcher e só volta quando o processo for encerrado.
func Run(ctx context.Context, handlers Handlers) error {
	conn, err := dbus.ConnectSessionBus()
	if err != nil {
		return fmt.Errorf("barramento de sessão: %w", err)
	}
	defer conn.Close()

	reply, err := conn.RequestName(appBusName, dbus.NameFlagDoNotQueue)
	if err != nil {
		return fmt.Errorf("registrar %s: %w", appBusName, err)
	}
	if reply != dbus.RequestNameReplyPrimaryOwner {
		return ErrAlreadyRunning
	}

	service := fmt.Sprintf("org.kde.StatusNotifierItem-%d-1", os.Getpid())
	reply, err = conn.RequestName(service, dbus.NameFlagDoNotQueue)
	if err != nil {
		return fmt.Errorf("registrar %s: %w", service, err)
	}
	if reply != dbus.RequestNameReplyPrimaryOwner {
		return ErrAlreadyRunning
	}

	quit := make(chan struct{})
	var quitOnce sync.Once
	closeQuit := func() { quitOnce.Do(func() { close(quit) }) }

	item := &statusItem{handlers: handlers}
	if err := conn.Export(item, itemPath, itemInterface); err != nil {
		return fmt.Errorf("exportar %s: %w", itemInterface, err)
	}
	if _, err := prop.Export(conn, itemPath, prop.Map{
		itemInterface: item.properties(),
	}); err != nil {
		return fmt.Errorf("propriedades da bandeja: %w", err)
	}

	menu := &dbusMenu{handlers: handlers, quit: closeQuit, revision: 1}
	if err := conn.Export(menu, menuPath, menuInterface); err != nil {
		return fmt.Errorf("exportar %s: %w", menuInterface, err)
	}
	if _, err := prop.Export(conn, menuPath, prop.Map{
		menuInterface: {
			"Version":       {Value: uint32(3), Emit: prop.EmitConst},
			"TextDirection": {Value: "ltr", Emit: prop.EmitConst},
			"Status":        {Value: "normal", Emit: prop.EmitConst},
			"IconThemePath": {Value: []string{}, Emit: prop.EmitConst},
		},
	}); err != nil {
		return fmt.Errorf("propriedades do menu: %w", err)
	}

	if err := register(conn, service); err != nil {
		return err
	}
	log.Printf("bandeja registrada como %s", service)

	select {
	case <-ctx.Done():
	case <-quit:
	}
	return nil
}

// statusItem implementa org.kde.StatusNotifierItem.
type statusItem struct {
	handlers Handlers
}

func (s *statusItem) properties() map[string]*prop.Prop {
	pixmaps := iconPixmaps()
	return map[string]*prop.Prop{
		"Category":            {Value: "ApplicationStatus", Emit: prop.EmitConst},
		"Id":                  {Value: "notai-capture", Emit: prop.EmitConst},
		"Title":               {Value: "NotAI", Emit: prop.EmitConst},
		"Status":              {Value: "Active", Emit: prop.EmitConst},
		"WindowId":            {Value: uint32(0), Emit: prop.EmitConst},
		"IconName":            {Value: "", Emit: prop.EmitConst},
		"IconPixmap":          {Value: pixmaps, Emit: prop.EmitConst},
		"OverlayIconName":     {Value: "", Emit: prop.EmitConst},
		"OverlayIconPixmap":   {Value: []iconPixmap{}, Emit: prop.EmitConst},
		"AttentionIconName":   {Value: "", Emit: prop.EmitConst},
		"AttentionIconPixmap": {Value: []iconPixmap{}, Emit: prop.EmitConst},
		"AttentionMovieName":  {Value: "", Emit: prop.EmitConst},
		"ToolTip": {Value: toolTip{
			IconPixmap: pixmaps,
			Title:      "NotAI",
			Subtitle:   "Salvar link no caderno",
		}, Emit: prop.EmitConst},
		"ItemIsMenu": {Value: true, Emit: prop.EmitConst},
		"Menu":       {Value: menuPath, Emit: prop.EmitConst},
	}
}

func (s *statusItem) Activate(x, y int32) *dbus.Error {
	s.dispatch(s.handlers.CaptureClipboard)
	return nil
}

func (s *statusItem) SecondaryActivate(x, y int32) *dbus.Error {
	s.dispatch(s.handlers.Open)
	return nil
}

func (s *statusItem) ContextMenu(x, y int32) *dbus.Error { return nil }

func (s *statusItem) Scroll(delta int32, orientation string) *dbus.Error { return nil }

func (s *statusItem) dispatch(action func()) {
	if action != nil {
		go action()
	}
}

// dbusMenu implementa com.canonical.dbusmenu com um menu estático.
type dbusMenu struct {
	handlers Handlers
	quit     func()
	revision uint32
}

type layoutItem struct {
	ID         int32
	Properties map[string]dbus.Variant
	Children   []dbus.Variant
}

type propertyUpdate struct {
	ID         int32
	Properties map[string]dbus.Variant
}

type menuEvent struct {
	ID        int32
	EventID   string
	Data      dbus.Variant
	Timestamp uint32
}

func (m *dbusMenu) GetLayout(parentID, depth int32, propertyNames []string) (uint32, layoutItem, *dbus.Error) {
	if parentID == 0 {
		return m.revision, m.root(), nil
	}
	return m.revision, layoutItem{
		ID:         parentID,
		Properties: m.propertiesOf(parentID),
		Children:   []dbus.Variant{},
	}, nil
}

func (m *dbusMenu) GetGroupProperties(ids []int32, propertyNames []string) ([]propertyUpdate, *dbus.Error) {
	if len(ids) == 0 {
		ids = []int32{0, 1, 2, 3, 4, 5, 6}
	}
	updates := make([]propertyUpdate, 0, len(ids))
	for _, id := range ids {
		updates = append(updates, propertyUpdate{ID: id, Properties: m.propertiesOf(id)})
	}
	return updates, nil
}

func (m *dbusMenu) GetProperty(id int32, name string) (dbus.Variant, *dbus.Error) {
	if value, ok := m.propertiesOf(id)[name]; ok {
		return value, nil
	}
	return dbus.MakeVariant(""), dbus.NewError("org.freedesktop.DBus.Error.InvalidArgs", []any{
		"propriedade desconhecida: " + name,
	})
}

func (m *dbusMenu) Event(id int32, eventID string, data dbus.Variant, timestamp uint32) *dbus.Error {
	if eventID != "clicked" {
		return nil
	}
	switch id {
	case 1:
		m.dispatch(m.handlers.CaptureClipboard)
	case 2:
		m.dispatch(m.handlers.CaptureDialog)
	case 4:
		m.dispatch(m.handlers.Open)
	case 5:
		m.dispatch(m.handlers.Login)
	case 6:
		go func() {
			if m.handlers.Quit != nil {
				m.handlers.Quit()
			}
			if m.quit != nil {
				m.quit()
			}
		}()
	}
	return nil
}

func (m *dbusMenu) EventGroup(events []menuEvent) *dbus.Error {
	for _, event := range events {
		_ = m.Event(event.ID, event.EventID, event.Data, event.Timestamp)
	}
	return nil
}

func (m *dbusMenu) AboutToShow(id int32) (bool, *dbus.Error) { return false, nil }

func (m *dbusMenu) AboutToShowGroup(ids []int32) ([]int32, []int32, *dbus.Error) {
	return []int32{}, []int32{}, nil
}

func (m *dbusMenu) dispatch(action func()) {
	if action != nil {
		go action()
	}
}

func (m *dbusMenu) root() layoutItem {
	return layoutItem{
		ID:         0,
		Properties: map[string]dbus.Variant{"children-display": dbus.MakeVariant("submenu")},
		Children: []dbus.Variant{
			dbus.MakeVariant(labelItem(1, "Salvar link do clipboard")),
			dbus.MakeVariant(labelItem(2, "Salvar link…")),
			dbus.MakeVariant(separatorItem(3)),
			dbus.MakeVariant(labelItem(4, "Abrir NotAI")),
			dbus.MakeVariant(labelItem(5, "Entrar…")),
			dbus.MakeVariant(labelItem(6, "Sair")),
		},
	}
}

func (m *dbusMenu) propertiesOf(id int32) map[string]dbus.Variant {
	switch id {
	case 0:
		return map[string]dbus.Variant{"children-display": dbus.MakeVariant("submenu")}
	case 1:
		return labelProperties("Salvar link do clipboard")
	case 2:
		return labelProperties("Salvar link…")
	case 3:
		return map[string]dbus.Variant{
			"type":    dbus.MakeVariant("separator"),
			"visible": dbus.MakeVariant(true),
		}
	case 4:
		return labelProperties("Abrir NotAI")
	case 5:
		return labelProperties("Entrar…")
	case 6:
		return labelProperties("Sair")
	default:
		return map[string]dbus.Variant{}
	}
}

func labelItem(id int32, label string) layoutItem {
	return layoutItem{ID: id, Properties: labelProperties(label), Children: []dbus.Variant{}}
}

func labelProperties(label string) map[string]dbus.Variant {
	return map[string]dbus.Variant{
		"label":   dbus.MakeVariant(label),
		"enabled": dbus.MakeVariant(true),
		"visible": dbus.MakeVariant(true),
		"type":    dbus.MakeVariant("standard"),
	}
}

func separatorItem(id int32) layoutItem {
	return layoutItem{
		ID: id,
		Properties: map[string]dbus.Variant{
			"type":    dbus.MakeVariant("separator"),
			"visible": dbus.MakeVariant(true),
		},
		Children: []dbus.Variant{},
	}
}

// register tenta de novo por alguns segundos: no login o autostart pode rodar antes de a extensão
// AppIndicator publicar o watcher.
func register(conn *dbus.Conn, service string) error {
	watcher := conn.Object(watcherName, watcherPath)
	var last error
	for attempt := 0; attempt < 10; attempt++ {
		call := watcher.Call("org.kde.StatusNotifierWatcher.RegisterStatusNotifierItem", 0, service)
		if call.Err == nil {
			return nil
		}
		last = call.Err
		time.Sleep(500 * time.Millisecond)
	}
	return fmt.Errorf("StatusNotifierWatcher indisponível (instale a extensão AppIndicator): %w", last)
}
