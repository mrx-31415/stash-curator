package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
)

// Stash's proxy setting reaches plugins as HTTP_PROXY; a proxy that cannot
// relay to Stash's listener closes the request ("Post .../graphql: EOF").
// Stash requests go direct, while StashDB requests keep the proxy.
func TestStashRequestsBypassProxy(t *testing.T) {
	respond := func(via string) *httptest.Server {
		return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprintf(w, `{"data":{"via":%q}}`, via)
		}))
	}
	stash, proxy := respond("stash"), respond("proxy")
	defer stash.Close()
	defer proxy.Close()
	proxyURL, _ := url.Parse(proxy.URL)
	defaultTransport := http.DefaultTransport.(*http.Transport)
	previous := defaultTransport.Proxy
	defaultTransport.Proxy = http.ProxyURL(proxyURL)
	defer func() { defaultTransport.Proxy = previous }()

	for category, want := range map[string]string{"stash": "stash", "stashdb": "proxy"} {
		data, err := graphqlQueryCat(stash.URL, nil, "query Probe { via }", jvNull(), category)
		if err != nil {
			t.Fatalf("%s: %v", category, err)
		}
		if got := data.get("via").s; got != want {
			t.Fatalf("%s request went via %q, want %q", category, got, want)
		}
	}
}
