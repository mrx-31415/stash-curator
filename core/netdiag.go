// Network failure diagnostics: a typed GraphQL request error that names the
// server, operation, HTTP status and a classified cause with a hint, a small
// per-install log of recent failures for the Diagnostics report, and the
// get_connection_check operation.
package main

import (
	"bufio"
	"crypto/x509"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"time"
	"unicode/utf8"
)

// requestError is a failed Stash or Stash-box GraphQL request. The message
// keeps the historical "<Server> request failed" / "<Server> returned ..."
// wording and adds what a forum report needs to tell a refused, reset,
// timed-out or foreign response apart.
type requestError struct {
	server      string // "Stash", "StashDB" or "Stash-box"
	operation   string
	elapsed     time.Duration
	attempts    int
	cause       error  // transport failure, when no response arrived
	status      int    // HTTP status, when a response arrived
	contentType string // response Content-Type
	problem     string // what was wrong with the response
	snippet     string // start of an unexpected response body
}

func (e *requestError) Error() string {
	if e.cause != nil {
		kind := classifyNetworkError(e.cause)
		message := fmt.Sprintf("%s request failed: %v (%s, after %s%s)", e.server, e.cause, e.operation, formatElapsed(e.elapsed), e.attemptsText())
		if hint := networkHint(kind, e.server); hint != "" {
			message += ". " + hint
		}
		return message
	}
	if strings.HasPrefix(e.problem, "GraphQL error: ") {
		return e.server + " " + e.problem
	}
	verb := " returned "
	problem := strings.TrimPrefix(e.problem, "returned ")
	if problem == e.problem {
		verb = " "
	}
	details := []string{e.operation, fmt.Sprintf("HTTP %d", e.status)}
	if e.attempts > 1 {
		details = append(details, fmt.Sprintf("%d attempts", e.attempts))
	}
	if e.contentType != "" {
		details = append(details, e.contentType)
	}
	message := e.server + verb + problem + " (" + strings.Join(details, ", ") + ")"
	if e.snippet != "" {
		message += fmt.Sprintf(": %q", e.snippet)
	} else {
		message += ": empty body"
	}
	if hint := statusHint(e.status, e.server); hint != "" {
		message += ". " + hint
	}
	return message
}

func (e *requestError) Unwrap() error { return e.cause }

func (e *requestError) attemptsText() string {
	if e.attempts > 1 {
		return fmt.Sprintf(", %d attempts", e.attempts)
	}
	return ""
}

// requestRetryDelays are the pauses before each retry of a read-only query.
var requestRetryDelays = []time.Duration{250 * time.Millisecond, time.Second}

// retryable reports a failure that a moment's wait can clear: a dropped
// connection, a briefly exhausted port range, or a gateway error. Refused
// connections, timeouts and answers from the server are not retried, since
// retrying them would only repeat or lengthen the same failure.
func (e *requestError) retryable() bool {
	switch e.kind() {
	case "reset", "ports_exhausted":
		return true
	case "http_status":
		return e.status == http.StatusBadGateway || e.status == http.StatusServiceUnavailable || e.status == http.StatusGatewayTimeout
	}
	return false
}

// graphqlIsMutation reports a document whose operation is a mutation. Only
// queries are retried: a mutation that failed after reaching the server may
// already have been applied.
func graphqlIsMutation(document string) bool {
	return regexp.MustCompile(`^\s*mutation\b`).MatchString(stripGraphQLComments(document))
}

func stripGraphQLComments(document string) string {
	lines := strings.Split(document, "\n")
	for i, line := range lines {
		if index := strings.IndexByte(line, '#'); index >= 0 {
			lines[i] = line[:index]
		}
	}
	return strings.Join(lines, "\n")
}

// kind is the privacy-safe failure class kept in the recent-failure log.
func (e *requestError) kind() string {
	if e.cause != nil {
		return classifyNetworkError(e.cause)
	}
	switch {
	case strings.HasPrefix(e.problem, "GraphQL error: "):
		return "graphql_error"
	case e.status < 200 || e.status > 299:
		return "http_status"
	}
	return "unexpected_response"
}

// requestServer names the server a request went to, so a Stash-box failure
// is never reported as a Stash one.
func requestServer(category, address string) string {
	if category != "stashdb" {
		return "Stash"
	}
	if parsed, err := url.Parse(address); err == nil && strings.EqualFold(parsed.Hostname(), "stashdb.org") {
		return "StashDB"
	}
	return "Stash-box"
}

func formatElapsed(elapsed time.Duration) string {
	if elapsed < time.Second {
		return fmt.Sprintf("%dms", elapsed.Milliseconds())
	}
	return fmt.Sprintf("%.1fs", elapsed.Seconds())
}

// bodySnippet is the start of a response body, flattened to one line.
func bodySnippet(raw []byte) string {
	const limit = 200
	text := strings.Join(strings.Fields(string(raw)), " ")
	if len(text) <= limit {
		return text
	}
	cut := limit
	for cut > 0 && !utf8.RuneStart(text[cut]) {
		cut--
	}
	return text[:cut] + "…"
}

// Windows socket error codes. Windows reports them as syscall.Errno values
// with localized messages, so they are matched by number; the numbers do not
// collide with any Unix errno.
const (
	wsaeaddrinuse    = syscall.Errno(10048)
	wsaeaddrnotavail = syscall.Errno(10049)
	wsaenetunreach   = syscall.Errno(10051)
	wsaeconnaborted  = syscall.Errno(10053)
	wsaeconnreset    = syscall.Errno(10054)
	wsaenobufs       = syscall.Errno(10055)
	wsaetimedout     = syscall.Errno(10060)
	wsaeconnrefused  = syscall.Errno(10061)
	wsaehostunreach  = syscall.Errno(10065)
)

// classifyNetworkError maps a transport error onto a small set of kinds.
func classifyNetworkError(err error) string {
	var errno syscall.Errno
	if errors.As(err, &errno) {
		switch errno {
		case syscall.ECONNREFUSED, wsaeconnrefused:
			return "refused"
		case syscall.ECONNRESET, syscall.ECONNABORTED, syscall.EPIPE, wsaeconnreset, wsaeconnaborted:
			return "reset"
		case syscall.EADDRINUSE, syscall.EADDRNOTAVAIL, syscall.ENOBUFS, wsaeaddrinuse, wsaeaddrnotavail, wsaenobufs:
			return "ports_exhausted"
		case syscall.ETIMEDOUT, wsaetimedout:
			return "timeout"
		case syscall.ENETUNREACH, syscall.EHOSTUNREACH, wsaenetunreach, wsaehostunreach:
			return "unreachable"
		}
	}
	var dnsErr *net.DNSError
	if errors.As(err, &dnsErr) {
		return "dns"
	}
	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return "timeout"
	}
	var unknownAuthority x509.UnknownAuthorityError
	var hostname x509.HostnameError
	var invalid x509.CertificateInvalidError
	if errors.As(err, &unknownAuthority) || errors.As(err, &hostname) || errors.As(err, &invalid) {
		return "tls"
	}
	if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
		return "reset"
	}
	var urlErr *url.Error
	if errors.As(err, &urlErr) && strings.Contains(urlErr.Err.Error(), "proxyconnect") {
		return "proxy"
	}
	return "other"
}

func networkHint(kind, server string) string {
	switch kind {
	case "refused":
		if server == "Stash" {
			return "Nothing accepted the connection at Stash's address; check Stash's host and port settings"
		}
		return "The server refused the connection"
	case "reset":
		return "The connection closed before a response arrived; security software that inspects traffic, a proxy, or Stash restarting can cause this"
	case "ports_exhausted":
		return "This computer ran out of network connections; another program is opening connections rapidly (check netstat -ano for TIME_WAIT entries)"
	case "timeout":
		if server == "Stash" {
			return "Stash did not answer in time; a scan, generate or other heavy Stash task may be running"
		}
		return "The server did not answer in time"
	case "unreachable":
		return "The network route to the server is unavailable"
	case "dns":
		return "The server's host name could not be resolved"
	case "tls":
		return "The server's TLS certificate was not accepted"
	case "proxy":
		return "The configured proxy could not be reached"
	}
	return ""
}

func statusHint(status int, server string) string {
	switch {
	case status == http.StatusUnauthorized || status == http.StatusForbidden:
		if server == "Stash" {
			return "Stash rejected Curator's session; reload the page and sign in again"
		}
		return "Check the Stash-box API key in Stash settings"
	case status == http.StatusTooManyRequests:
		return "The server is rate limiting requests; try again later"
	case status >= 500:
		return "The server had an internal error or is behind an unavailable gateway"
	case status >= 200 && status <= 299 && server == "Stash":
		return "The response did not come from Stash's GraphQL API; check that nothing else answers on Stash's address"
	}
	return ""
}

// Recent failures are appended to a small JSON-lines file in the plugin data
// directory, shared by every short-lived operation process and the daemon.
// Entries hold only privacy-safe fields: no URL, address, body or message.
const (
	networkFailureFile = "curator-network-failures.jsonl"
	networkFailureKeep = 20
)

var (
	networkFailureMu  sync.Mutex
	networkFailureDir string
)

func setNetworkFailureDir(pluginDir string) {
	networkFailureMu.Lock()
	networkFailureDir = filepath.Join(pluginDir, "data")
	networkFailureMu.Unlock()
}

type networkFailure struct {
	AtMs      int64  `json:"at_ms"`
	Server    string `json:"server"`
	Operation string `json:"operation"`
	Kind      string `json:"kind"`
	Status    int    `json:"status,omitempty"`
	ElapsedMs int64  `json:"elapsed_ms"`
}

func recordRequestFailure(failure *requestError) {
	// GraphQL errors are answers from the server, and some are expected
	// (schema probes on older Stash versions); only connection and response
	// failures are logged.
	if failure.kind() == "graphql_error" {
		return
	}
	// Stash's log (or the daemon log) keeps the full message; the report
	// keeps only the privacy-safe class.
	warnLog("Curator: " + failure.Error())
	networkFailureMu.Lock()
	defer networkFailureMu.Unlock()
	if networkFailureDir == "" {
		return
	}
	entry, err := json.Marshal(networkFailure{
		AtMs: nowMs(), Server: failure.server, Operation: failure.operation,
		Kind: failure.kind(), Status: failure.status, ElapsedMs: failure.elapsed.Milliseconds(),
	})
	if err != nil {
		return
	}
	if err := os.MkdirAll(networkFailureDir, 0o755); err != nil {
		return
	}
	path := filepath.Join(networkFailureDir, networkFailureFile)
	file, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	_, _ = file.Write(append(entry, '\n'))
	info, statErr := file.Stat()
	_ = file.Close()
	// Trim occasionally rather than on every write; concurrent writers may
	// lose an entry during a trim, which is acceptable for a diagnostic log.
	if statErr == nil && info.Size() > 16*1024 {
		entries := readNetworkFailures(path)
		var out strings.Builder
		for _, line := range entries {
			out.WriteString(line)
			out.WriteByte('\n')
		}
		temporary := path + ".tmp"
		if os.WriteFile(temporary, []byte(out.String()), 0o644) == nil {
			_ = os.Rename(temporary, path)
		}
	}
}

// readNetworkFailures returns the newest valid entries, oldest first.
func readNetworkFailures(path string) []string {
	file, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer file.Close()
	var lines []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		var entry networkFailure
		if json.Unmarshal([]byte(line), &entry) != nil {
			continue
		}
		lines = append(lines, line)
		if len(lines) > networkFailureKeep {
			lines = lines[1:]
		}
	}
	return lines
}

// opGetConnectionCheck reports how this Curator process reaches Stash and the
// selected Stash-box, timing one small query to each, plus the recent failure
// log. Like get_diagnostics it is allowlisted: it reports address classes,
// variable names and timings, never addresses, URLs, keys or values.
func opGetConnectionCheck(pluginDir string, payload jVal) (jVal, error) {
	return profiledOperation(pluginDir, payload, "get_connection_check",
		func(jVal) (jVal, error) { return connectionCheckBody(pluginDir, payload), nil })
}

func connectionCheckBody(pluginDir string, payload jVal) jVal {
	base, headers := stashConnection(payload)
	stashCheck := jvObj(
		jvKey("address", jvStr(addressClass(base))),
		jvKey("scheme", jvStr(urlScheme(base))),
		jvKey("session_cookie", jvBool(headers["Cookie"] != "")),
	)
	started := time.Now()
	data, err := graphqlQuery(base, headers, `query CuratorConnectionCheck { version { version } }`, jvNull())
	stashCheck.set("elapsed_ms", jvInt(time.Since(started).Milliseconds()))
	if err != nil {
		stashCheck.set("ok", jvBool(false))
		stashCheck.set("error", jvStr(failureKind(err)))
	} else {
		stashCheck.set("ok", jvBool(true))
		if version := data.get("version").get("version"); version.kind == jStr {
			stashCheck.set("stash_version", version)
		}
	}

	boxCheck := jvObj(jvKey("server", jvStr(requestServer("stashdb", stashdbEndpoint))))
	if isThePornDB(stashdbEndpoint) {
		boxCheck.set("checked", jvBool(false))
	} else if boxURL, apiKey, err := stashdbClient(payload); err != nil {
		boxCheck.set("configured", jvBool(false))
	} else {
		boxCheck.set("configured", jvBool(true))
		probe, _ := http.NewRequest(http.MethodPost, boxURL, nil)
		proxied := false
		if probe != nil {
			if proxy, err := http.ProxyFromEnvironment(probe); err == nil && proxy != nil {
				proxied = true
			}
		}
		boxCheck.set("via_proxy", jvBool(proxied))
		started := time.Now()
		_, err := stashdbQuery(boxURL, apiKey, `query CuratorConnectionCheck { __typename }`, jvNull())
		boxCheck.set("elapsed_ms", jvInt(time.Since(started).Milliseconds()))
		boxCheck.set("ok", jvBool(err == nil))
		if err != nil {
			boxCheck.set("error", jvStr(failureKind(err)))
		}
	}

	proxyNames := jvArr()
	for _, name := range []string{"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"} {
		if os.Getenv(name) != "" {
			proxyNames.arr = append(proxyNames.arr, jvStr(name))
		}
	}
	failures := jvArr()
	for _, line := range readNetworkFailures(filepath.Join(pluginDir, "data", networkFailureFile)) {
		if parsed, err := parseJSON([]byte(line)); err == nil {
			failures.arr = append(failures.arr, parsed)
		}
	}
	result := jvObj(
		jvKey("os", jvStr(runtime.GOOS)),
		jvKey("arch", jvStr(runtime.GOARCH)),
		jvKey("stash", stashCheck),
		jvKey("stash_box", boxCheck),
		jvKey("proxy_variables", proxyNames),
		jvKey("recent_failures", failures),
	)
	if sockets := socketSummary(stashPort(base)); sockets.kind != jNull {
		result.set("sockets", sockets)
	}
	return result
}

func failureKind(err error) string {
	var failure *requestError
	if errors.As(err, &failure) {
		return failure.kind()
	}
	return "other"
}

func urlScheme(address string) string {
	if parsed, err := url.Parse(address); err == nil {
		return parsed.Scheme
	}
	return ""
}

func stashPort(address string) string {
	if parsed, err := url.Parse(address); err == nil {
		return parsed.Port()
	}
	return ""
}

// addressClass describes Stash's address without revealing it.
func addressClass(address string) string {
	parsed, err := url.Parse(address)
	if err != nil {
		return "invalid"
	}
	host := parsed.Hostname()
	if strings.EqualFold(host, "localhost") {
		return "loopback"
	}
	ip := net.ParseIP(host)
	switch {
	case ip == nil:
		return "hostname"
	case ip.IsLoopback():
		return "loopback"
	case ip.IsPrivate() || ip.IsLinkLocalUnicast():
		return "private"
	}
	return "public"
}

// Windows IP Helper TCP tables (GetTcpTable, GetTcp6Table), parsed here so
// the layout is tested on every platform.
const tcpTimeWait = uint32(11) // MIB_TCP_STATE_TIME_WAIT

type tcpLayout struct{ size, localPort, remotePort int }

var (
	tcpRowLayout  = tcpLayout{size: 20, localPort: 8, remotePort: 16}  // MIB_TCPROW
	tcp6RowLayout = tcpLayout{size: 52, localPort: 24, remotePort: 48} // MIB_TCP6ROW
)

// countTimeWait walks a MIB_TCPTABLE or MIB_TCP6TABLE: a row count followed
// by fixed-size rows whose first field is the state; ports sit in the low 16
// bits in network byte order.
func countTimeWait(table []byte, layout tcpLayout, port int) (int64, int64) {
	if len(table) < 4 {
		return 0, 0
	}
	count := int(binary.LittleEndian.Uint32(table))
	var total, onStash int64
	for row := 0; row < count; row++ {
		offset := 4 + row*layout.size
		if offset+layout.size > len(table) {
			break
		}
		if binary.LittleEndian.Uint32(table[offset:]) != tcpTimeWait {
			continue
		}
		total++
		local := int(binary.BigEndian.Uint16(table[offset+layout.localPort:]))
		remote := int(binary.BigEndian.Uint16(table[offset+layout.remotePort:]))
		if port > 0 && (local == port || remote == port) {
			onStash++
		}
	}
	return total, onStash
}
