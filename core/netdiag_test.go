package main

import (
	"encoding/binary"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func withoutRetryDelays(t *testing.T) {
	previous := requestRetryDelays
	requestRetryDelays = []time.Duration{0, 0}
	t.Cleanup(func() { requestRetryDelays = previous })
}

// Each failure a forum report has shown names the server and operation and
// says what kind of failure it was, so a dropped connection, a foreign
// response and an auth failure can be told apart from the message alone.
func TestRequestFailuresAreDiagnosable(t *testing.T) {
	withoutRetryDelays(t)
	pluginDir := t.TempDir()
	setNetworkFailureDir(pluginDir)
	t.Cleanup(func() { networkFailureDir = "" })

	drop := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		connection, _, _ := w.(http.Hijacker).Hijack()
		connection.Close()
	}))
	defer drop.Close()
	respond := func(status int, contentType, body string) *httptest.Server {
		return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			if contentType != "" {
				w.Header().Set("Content-Type", contentType)
			}
			w.WriteHeader(status)
			fmt.Fprint(w, body)
		}))
	}
	unauthorized := respond(http.StatusUnauthorized, "", "")
	defer unauthorized.Close()
	html := respond(http.StatusOK, "text/html", "<html>\n  <body>Router login</body>\n</html>")
	defer html.Close()
	noData := respond(http.StatusOK, "application/json", `{"extensions":{}}`)
	defer noData.Close()
	graphqlErr := respond(http.StatusUnprocessableEntity, "application/json", `{"errors":[{"message":"bad input"}]}`)
	defer graphqlErr.Close()
	listener, _ := net.Listen("tcp", "127.0.0.1:0")
	refused := "http://" + listener.Addr().String()
	listener.Close()

	cases := []struct {
		name, base, category, kind string
		want                       []string
	}{
		{"dropped", drop.URL, "stash", "reset", []string{"Stash request failed:", "(Probe, after ", ", 3 attempts)", "connection closed before a response"}},
		{"refused", refused, "stash", "refused", []string{"Stash request failed:", "check Stash's host and port"}},
		{"empty 401", unauthorized.URL, "stashdb", "http_status", []string{"Stash-box returned an error status (Probe, HTTP 401): empty body", "API key"}},
		{"html", html.URL, "stash", "unexpected_response", []string{`Stash returned invalid JSON (Probe, HTTP 200, text/html): "<html> <body>Router login</body> </html>"`, "did not come from Stash"}},
		{"no data", noData.URL, "stash", "unexpected_response", []string{`Stash GraphQL response has no data object (Probe, HTTP 200, application/json): "{\"extensions\":{}}"`}},
		{"graphql 422", graphqlErr.URL, "stash", "graphql_error", []string{`Stash GraphQL error: [{"message":"bad input"}]`}},
	}
	for _, tc := range cases {
		_, err := graphqlQueryCat(tc.base, nil, "query Probe { probe }", jvNull(), tc.category)
		if err == nil {
			t.Fatalf("%s: no error", tc.name)
		}
		t.Logf("%s: %v", tc.name, err)
		for _, want := range tc.want {
			if !strings.Contains(err.Error(), want) {
				t.Errorf("%s: %q does not contain %q", tc.name, err.Error(), want)
			}
		}
		if got := failureKind(err); got != tc.kind {
			t.Errorf("%s: kind %q, want %q", tc.name, got, tc.kind)
		}
		if got := errorTypeName(err); got != "GraphQLError" {
			t.Errorf("%s: error type %q", tc.name, got)
		}
	}

	// The failure log keeps the class of each failure but no address, body
	// or message; GraphQL errors are answers and are not logged.
	raw, err := os.ReadFile(filepath.Join(pluginDir, "data", networkFailureFile))
	if err != nil {
		t.Fatal(err)
	}
	lines := readNetworkFailures(filepath.Join(pluginDir, "data", networkFailureFile))
	if len(lines) != len(cases)-1 {
		t.Fatalf("logged %d failures, want %d:\n%s", len(lines), len(cases)-1, raw)
	}
	for _, private := range []string{"127.0.0.1", "Router login", "extensions", "bad input"} {
		if strings.Contains(string(raw), private) {
			t.Fatalf("failure log contains %q:\n%s", private, raw)
		}
	}
}

func TestRequestServerNamesStashBoxes(t *testing.T) {
	for address, want := range map[string]string{
		"https://stashdb.org/graphql": "StashDB",
		"https://fansdb.cc/graphql":   "Stash-box",
	} {
		if got := requestServer("stashdb", address); got != want {
			t.Errorf("%s: %q, want %q", address, got, want)
		}
	}
	if got := requestServer("stash", "https://stashdb.org/graphql"); got != "Stash" {
		t.Errorf("stash category named %q", got)
	}
}

func TestAddressClassHidesTheAddress(t *testing.T) {
	for address, want := range map[string]string{
		"http://127.0.0.1:9999":     "loopback",
		"http://localhost:9999":     "loopback",
		"http://[::1]:9999":         "loopback",
		"http://192.168.1.20:9999":  "private",
		"http://stash.example:9999": "hostname",
		"http://8.8.8.8:9999":       "public",
	} {
		if got := addressClass(address); got != want {
			t.Errorf("%s: %q, want %q", address, got, want)
		}
	}
}

func TestFailureLogKeepsTheNewestEntries(t *testing.T) {
	pluginDir := t.TempDir()
	setNetworkFailureDir(pluginDir)
	t.Cleanup(func() { networkFailureDir = "" })
	for i := 0; i < 400; i++ {
		recordRequestFailure(&requestError{server: "Stash", operation: fmt.Sprintf("Op%d", i), status: 502})
	}
	path := filepath.Join(pluginDir, "data", networkFailureFile)
	lines := readNetworkFailures(path)
	if len(lines) != networkFailureKeep || !strings.Contains(lines[len(lines)-1], `"Op399"`) {
		t.Fatalf("kept %d entries, last %q", len(lines), lines[len(lines)-1])
	}
	if info, err := os.Stat(path); err != nil || info.Size() > 32*1024 {
		t.Fatalf("failure log was not trimmed: %v %v", info, err)
	}
}

// Read-only queries survive a dropped connection or a gateway error; a
// mutation, which may already have been applied, and a refused connection
// fail at once.
func TestTransientFailuresRetryQueriesOnly(t *testing.T) {
	withoutRetryDelays(t)
	var requests atomic.Int32
	failFirst := func(failures int32, fail func(http.ResponseWriter)) *httptest.Server {
		requests.Store(0)
		return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			if requests.Add(1) <= failures {
				fail(w)
				return
			}
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprint(w, `{"data":{"ok":true}}`)
		}))
	}
	drop := func(w http.ResponseWriter) {
		connection, _, _ := w.(http.Hijacker).Hijack()
		connection.Close()
	}
	unavailable := func(w http.ResponseWriter) { w.WriteHeader(http.StatusServiceUnavailable) }

	for _, tc := range []struct {
		name     string
		failures int32
		fail     func(http.ResponseWriter)
		document string
		ok       bool
		requests int32
	}{
		{"dropped query", 2, drop, "query Probe { ok }", true, 3},
		{"unavailable query", 1, unavailable, "query Probe { ok }", true, 2},
		{"persistent drop", 5, drop, "query Probe { ok }", false, 3},
		{"dropped mutation", 1, drop, "\nmutation Change { ok }", false, 1},
	} {
		server := failFirst(tc.failures, tc.fail)
		_, err := graphqlQuery(server.URL, nil, tc.document, jvNull())
		server.Close()
		if (err == nil) != tc.ok {
			t.Errorf("%s: error %v, want ok=%v", tc.name, err, tc.ok)
		}
		if got := requests.Load(); got != tc.requests {
			t.Errorf("%s: %d requests, want %d", tc.name, got, tc.requests)
		}
	}

	listener, _ := net.Listen("tcp", "127.0.0.1:0")
	refused := "http://" + listener.Addr().String()
	listener.Close()
	_, err := graphqlQuery(refused, nil, "query Probe { ok }", jvNull())
	if err == nil || strings.Contains(err.Error(), "attempts") {
		t.Fatalf("refused connection was retried: %v", err)
	}
}

func TestCountTimeWaitReadsTCPTables(t *testing.T) {
	row := func(layout tcpLayout, state uint32, local, remote uint16) []byte {
		buffer := make([]byte, layout.size)
		binary.LittleEndian.PutUint32(buffer, state)
		binary.BigEndian.PutUint16(buffer[layout.localPort:], local)
		binary.BigEndian.PutUint16(buffer[layout.remotePort:], remote)
		return buffer
	}
	for _, layout := range []tcpLayout{tcpRowLayout, tcp6RowLayout} {
		rows := [][]byte{
			row(layout, tcpTimeWait, 51000, 9999),
			row(layout, tcpTimeWait, 9999, 51001),
			row(layout, tcpTimeWait, 51002, 443),
			row(layout, 5, 51003, 9999), // ESTABLISHED
		}
		table := binary.LittleEndian.AppendUint32(nil, uint32(len(rows)))
		for _, r := range rows {
			table = append(table, r...)
		}
		total, onStash := countTimeWait(table, layout, 9999)
		if total != 3 || onStash != 2 {
			t.Errorf("layout %+v: %d TIME_WAIT, %d on Stash's port; want 3 and 2", layout, total, onStash)
		}
		if total, _ := countTimeWait(table[:len(table)-1], layout, 9999); total != 3 {
			t.Errorf("layout %+v: truncated table counted %d", layout, total)
		}
	}
}
