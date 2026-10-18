//go:build linux

package tray

import "math"

// iconPixmap é o (iiay) que o StatusNotifierItem espera: ARGB32 em ordem de rede.
type iconPixmap struct {
	Width  int32
	Height int32
	Data   []byte
}

// toolTip é o (sa(iiay)ss) do SNI.
type toolTip struct {
	IconName   string
	IconPixmap []iconPixmap
	Title      string
	Subtitle   string
}

var glyphN = []string{
	"10001",
	"11001",
	"10101",
	"10011",
	"10001",
	"10001",
	"10001",
}

func iconPixmaps() []iconPixmap {
	return []iconPixmap{drawIcon(22), drawIcon(48)}
}

func drawIcon(size int32) iconPixmap {
	data := make([]byte, int(size)*int(size)*4)
	radius := float64(size) / 5
	for y := int32(0); y < size; y++ {
		for x := int32(0); x < size; x++ {
			if insideRounded(x, y, size, radius) {
				setPixel(data, size, x, y, 0x1f, 0x6f, 0xeb)
			}
		}
	}
	scale := size / 10
	if scale < 1 {
		scale = 1
	}
	glyphWidth := int32(len(glyphN[0])) * scale
	glyphHeight := int32(len(glyphN)) * scale
	offsetX := (size - glyphWidth) / 2
	offsetY := (size - glyphHeight) / 2
	for row, line := range glyphN {
		for column, cell := range line {
			if cell != '1' {
				continue
			}
			for dy := int32(0); dy < scale; dy++ {
				for dx := int32(0); dx < scale; dx++ {
					setPixel(data, size,
						offsetX+int32(column)*scale+dx,
						offsetY+int32(row)*scale+dy,
						0xff, 0xff, 0xff)
				}
			}
		}
	}
	return iconPixmap{Width: size, Height: size, Data: data}
}

func insideRounded(x, y, size int32, radius float64) bool {
	fx, fy := float64(x)+0.5, float64(y)+0.5
	centerX := math.Min(math.Max(fx, radius), float64(size)-radius)
	centerY := math.Min(math.Max(fy, radius), float64(size)-radius)
	dx, dy := fx-centerX, fy-centerY
	return dx*dx+dy*dy <= radius*radius
}

func setPixel(data []byte, size, x, y int32, red, green, blue byte) {
	if x < 0 || y < 0 || x >= size || y >= size {
		return
	}
	offset := (int(y)*int(size) + int(x)) * 4
	data[offset] = 0xff
	data[offset+1] = red
	data[offset+2] = green
	data[offset+3] = blue
}
