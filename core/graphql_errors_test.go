package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// A reply that is not a GraphQL result names the server that was called, the
// HTTP status, and the start of the body, so a report shows what answered.
func TestUnexpectedGraphQLResponsesShowWhatAnswered(t *testing.T) {
	cases := []struct {
		category, body string
		status         int
		want           string
	}{
		{"stash", `{"message":"blocked by proxy"}`, http.StatusForbidden,
			`Stash GraphQL response has no data object (HTTP 403: {"message":"blocked by proxy"})`},
		{"stashdb", "<html>\n  <body>Too many requests</body>\n</html>", http.StatusTooManyRequests,
			"StashDB returned invalid JSON (HTTP 429: <html> <body>Too many requests</body> </html>)"},
		{"stash", "", http.StatusUnauthorized, "Stash returned invalid JSON (HTTP 401: empty body)"},
		{"stash", `{"data":null,"errors":[{"message":"boom"}]}`, http.StatusOK,
			`Stash GraphQL error: [{"message":"boom"}]`},
		{"stash", "[" + strings.Repeat(`"x",`, 100) + `"x"]`, http.StatusOK,
			`Stash returned a non-object GraphQL response (HTTP 200: [` + strings.Repeat(`"x",`, 49) + `"x"…)`},
	}
	for _, tc := range cases {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(tc.status)
			w.Write([]byte(tc.body))
		}))
		_, err := graphqlQueryCat(server.URL, nil, "query Probe { probe }", jvNull(), tc.category)
		server.Close()
		if err == nil || err.Error() != tc.want {
			t.Errorf("%s %d: got %v, want %s", tc.category, tc.status, err, tc.want)
		}
	}
}
