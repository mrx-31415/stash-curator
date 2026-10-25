package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"
	"time"
)

// An incremental probe walks newest-update-first and stops at its limit or at
// the first scene at or before the watermark, without asking for another page;
// a scene without a readable update time counts as changed.
func TestFetchUpdatedSinceStopsAtWatermark(t *testing.T) {
	watermark := time.Date(2026, 10, 24, 3, 0, 0, 0, time.UTC)
	updated := []string{
		watermark.Add(5 * time.Hour).Format(time.RFC3339Nano),
		"",
		watermark.Add(time.Second).Format("2006-01-02T15:04:05.00000Z"),
		watermark.Format(time.RFC3339),
		watermark.Add(-time.Hour).Format(time.RFC3339),
	}
	var pages []int
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var request struct {
			Variables struct {
				Input map[string]any `json:"input"`
			} `json:"variables"`
		}
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Fatal(err)
		}
		input := request.Variables.Input
		if input["sort"] != "UPDATED_AT" || input["updated_at"] != nil {
			t.Errorf("probe input %v, want an UPDATED_AT sort and no updated_at filter", input)
		}
		page, perPage := int(input["page"].(float64)), int(input["per_page"].(float64))
		pages = append(pages, page)
		scenes := []any{}
		for i := (page - 1) * perPage; i < min(page*perPage, len(updated)); i++ {
			scene := map[string]any{"id": fmt.Sprint("scene-", i)}
			if updated[i] != "" {
				scene["updated"] = updated[i]
			}
			scenes = append(scenes, scene)
		}
		json.NewEncoder(w).Encode(map[string]any{"data": map[string]any{
			"queryScenes": map[string]any{"count": len(updated), "scenes": scenes},
		}})
	}))
	defer server.Close()

	rows := &sceneRows{m: map[string]jVal{}}
	sources := map[string]map[string]bool{}
	spec := fetchPageSpec{source: "performers", values: []string{"p"}, limit: 2, modifier: "INCLUDES",
		sort: "UPDATED_AT", sinceMs: watermark.UnixMilli()}
	if err := fetchUpdatedSince(server.URL, "", spec, rows, sources); err != nil {
		t.Fatal(err)
	}
	if want := []string{"scene-0", "scene-1"}; !reflect.DeepEqual(rows.order, want) || !reflect.DeepEqual(pages, []int{1}) {
		t.Fatalf("limit 2: rows %v pages %v, want %v from page 1 only", rows.order, pages, want)
	}

	pages = nil
	rows = &sceneRows{m: map[string]jVal{}}
	spec.limit = 4
	if err := fetchUpdatedSince(server.URL, "", spec, rows, sources); err != nil {
		t.Fatal(err)
	}
	if want := []string{"scene-0", "scene-1", "scene-2"}; !reflect.DeepEqual(rows.order, want) || !reflect.DeepEqual(pages, []int{1}) {
		t.Fatalf("watermark: rows %v pages %v, want %v from page 1 only", rows.order, pages, want)
	}
	if !sources["scene-2"]["performers"] {
		t.Fatalf("scene-2 lost its seed source: %v", sources["scene-2"])
	}
}
