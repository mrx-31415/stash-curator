//go:build windows

package main

import (
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
)

// The IP Helper tables answer on a real Windows host, and a closed
// loopback connection shows up as TIME_WAIT on its port.
func TestSocketSummaryCountsTimeWait(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Connection", "close")
	}))
	defer server.Close()
	_, port, _ := net.SplitHostPort(server.Listener.Addr().String())
	for i := 0; i < 5; i++ {
		response, err := http.Get(server.URL)
		if err != nil {
			t.Fatal(err)
		}
		response.Body.Close()
	}
	summary := socketSummary(port)
	if summary.kind != jObj {
		t.Fatal("no socket summary")
	}
	total, onPort := pythonInt(summary.get("time_wait")), pythonInt(summary.get("time_wait_stash_port"))
	if onPort < 1 || total < onPort {
		t.Fatalf("time_wait %d, on port %s: %d", total, strconv.Quote(port), onPort)
	}
}

// A refused loopback connection carries Windows' localized-message errno,
// which must still classify as refused.
func TestWindowsRefusedConnectionIsClassified(t *testing.T) {
	listener, _ := net.Listen("tcp", "127.0.0.1:0")
	address := listener.Addr().String()
	listener.Close()
	_, err := net.Dial("tcp", address)
	if err == nil {
		t.Fatal("dial succeeded")
	}
	if kind := classifyNetworkError(err); kind != "refused" {
		t.Fatalf("kind %q for %v", kind, err)
	}
}
