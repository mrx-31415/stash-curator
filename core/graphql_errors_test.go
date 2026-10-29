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
		want           []string
	}{
		{"stash", `{"message":"blocked by proxy"}`, http.StatusForbidden,
			[]string{"Stash returned an error status (Probe, HTTP 403", `blocked by proxy`}},
		{"stashdb", "<html>\n  <body>Too many requests</body>\n</html>", http.StatusTooManyRequests,
			[]string{"Stash-box returned an error status (Probe, HTTP 429, text/html", "<html> <body>Too many requests</body> </html>", "rate limiting"}},
		{"stash", "", http.StatusUnauthorized, []string{"Stash returned an error status (Probe, HTTP 401): empty body"}},
		{"stash", `{"data":null,"errors":[{"message":"boom"}]}`, http.StatusOK,
			[]string{`Stash GraphQL error: [{"message":"boom"}]`}},
		{"stash", "[" + strings.Repeat(`"x",`, 100) + `"x"]`, http.StatusOK,
			[]string{"Stash returned a non-object GraphQL response (Probe, HTTP 200", strings.Repeat(`\"x\",`, 40), `…"`}},
	}
	for _, tc := range cases {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(tc.status)
			w.Write([]byte(tc.body))
		}))
		_, err := graphqlQueryCat(server.URL, nil, "query Probe { probe }", jvNull(), tc.category)
		server.Close()
		if err == nil {
			t.Errorf("%s %d: no error", tc.category, tc.status)
			continue
		}
		for _, want := range tc.want {
			if !strings.Contains(err.Error(), want) {
				t.Errorf("%s %d: %q does not contain %q", tc.category, tc.status, err.Error(), want)
			}
		}
	}
}
