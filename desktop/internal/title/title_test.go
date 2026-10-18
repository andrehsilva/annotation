package title

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestForURL(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/page", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		fmt.Fprint(w, `<html><head><title>  Olá &amp; mundo
		</title></head><body>texto</body></html>`)
	})
	mux.HandleFunc("/empty", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		fmt.Fprint(w, `<html><body>sem título</body></html>`)
	})
	mux.HandleFunc("/json", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"title":"não é html"}`)
	})
	mux.HandleFunc("/status", func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "falhou", http.StatusInternalServerError)
	})

	server := httptest.NewServer(mux)
	defer server.Close()
	host := strings.Split(strings.TrimPrefix(server.URL, "http://"), ":")[0]

	cases := []struct {
		name string
		path string
		want string
	}{
		{name: "title", path: "/page", want: "Olá & mundo"},
		{name: "no title", path: "/empty", want: host},
		{name: "not html", path: "/json", want: host},
		{name: "http error", path: "/status", want: host},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := ForURL(context.Background(), server.URL+tc.path)
			if got != tc.want {
				t.Fatalf("ForURL = %q, quer %q", got, tc.want)
			}
		})
	}
}

func TestForURLConnectionErrorFallsBackToHost(t *testing.T) {
	got := ForURL(context.Background(), "http://127.0.0.1:1/artigo")
	if got != "127.0.0.1" {
		t.Fatalf("ForURL = %q", got)
	}
}

func TestTruncate(t *testing.T) {
	cases := []struct {
		in    string
		limit int
		want  string
	}{
		{"abc", 0, "abc"},
		{"abc", 3, "abc"},
		{"abc", 2, "a…"},
		{"ação", 3, "aç…"},
		{"ação", 1, "…"},
	}
	for _, tc := range cases {
		if got := Truncate(tc.in, tc.limit); got != tc.want {
			t.Fatalf("Truncate(%q, %d) = %q, quer %q", tc.in, tc.limit, got, tc.want)
		}
	}
}
