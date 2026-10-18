package link

import (
	"errors"
	"strings"
	"testing"
)

func TestValidate(t *testing.T) {
	cases := []struct {
		name    string
		input   string
		want    string
		wantErr bool
	}{
		{name: "https", input: " https://example.com/a?b=1 ", want: "https://example.com/a?b=1"},
		{name: "localhost", input: "http://localhost:8000/x", want: "http://localhost:8000/x"},
		{name: "javascript", input: "javascript:alert(1)", wantErr: true},
		{name: "file", input: "file:///etc/passwd", wantErr: true},
		{name: "empty", input: "   ", wantErr: true},
		{name: "no host", input: "https://", wantErr: true},
		{name: "scheme", input: "notai://capture?url=https%3A%2F%2Fexample.com", wantErr: true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := Validate(tc.input)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("Validate(%q) = %q, quer erro", tc.input, got)
				}
				return
			}
			if err != nil {
				t.Fatalf("Validate(%q): %v", tc.input, err)
			}
			if got != tc.want {
				t.Fatalf("Validate(%q) = %q, quer %q", tc.input, got, tc.want)
			}
		})
	}
}

func TestValidateRejectsNonHTTPWithSentinel(t *testing.T) {
	_, err := Validate("ftp://example.com/file")
	if !errors.Is(err, ErrNotHTTP) {
		t.Fatalf("err = %v, quer ErrNotHTTP", err)
	}
}

func TestParseScheme(t *testing.T) {
	capture, ok, err := ParseScheme("notai://capture?url=https%3A%2F%2Fexample.com%2Fartigo&title=Ol%C3%A1")
	if err != nil {
		t.Fatal(err)
	}
	if !ok {
		t.Fatal("ParseScheme não reconheceu notai://")
	}
	if capture.URL != "https://example.com/artigo" {
		t.Fatalf("URL = %q", capture.URL)
	}
	if capture.Title != "Olá" {
		t.Fatalf("Title = %q", capture.Title)
	}
}

func TestParseSchemeOpaque(t *testing.T) {
	capture, ok, err := ParseScheme("notai:capture?url=https%3A%2F%2Fexample.com%2Fx")
	if err != nil {
		t.Fatal(err)
	}
	if !ok || capture.URL != "https://example.com/x" {
		t.Fatalf("capture = %+v, ok = %v", capture, ok)
	}
}

func TestParseSchemeRejectsUnknownAction(t *testing.T) {
	_, ok, err := ParseScheme("notai://open?url=https%3A%2F%2Fexample.com")
	if !ok {
		t.Fatal("deveria reconhecer o esquema notai:")
	}
	if err == nil {
		t.Fatal("ação desconhecida deveria falhar")
	}
}

func TestParseSchemeRequiresURL(t *testing.T) {
	_, ok, err := ParseScheme("notai://capture?title=Sem+URL")
	if !ok {
		t.Fatal("deveria reconhecer o esquema notai:")
	}
	if err == nil {
		t.Fatal("captura sem url deveria falhar")
	}
}

func TestParseSchemeNotOurs(t *testing.T) {
	_, ok, err := ParseScheme("https://example.com")
	if ok || err != nil {
		t.Fatalf("ok = %v, err = %v", ok, err)
	}
}

func TestParseSchemeTruncatesTitle(t *testing.T) {
	title := strings.Repeat("á", 400)
	capture, _, err := ParseScheme("notai://capture?url=https%3A%2F%2Fexample.com&title=" + title)
	if err != nil {
		t.Fatal(err)
	}
	if len([]rune(capture.Title)) != 300 {
		t.Fatalf("título tem %d runas", len([]rune(capture.Title)))
	}
}
