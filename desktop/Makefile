BINARY  := notai-capture
GO      ?= go
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)

.PHONY: build test vet install uninstall clean

build:
	CGO_ENABLED=0 $(GO) build -trimpath -ldflags "-s -w -X main.version=$(VERSION)" -o bin/$(BINARY) ./cmd/notai-capture

test:
	$(GO) test ./...

vet:
	$(GO) vet ./...

install: build
	./bin/$(BINARY) install

uninstall: build
	./bin/$(BINARY) uninstall

clean:
	rm -rf bin
