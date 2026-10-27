package main

import "testing"

// Python builds a scene's explanation before the multi-hop blend, so a
// reached result lists multi_hop in its relationships but not its reasons.
func TestRenderSceneResultExplainsPreBlendRelationships(t *testing.T) {
	item := &similarityResult{
		entityID: "candidate", similarity: 0.6, appeal: 0.7, appealRaw: 0.4,
		relationships: []string{"shared_content", "multi_hop"},
		scene: &sceneSimilarityParts{
			content: 0.5, explained: []string{"shared_content"},
			blended: true, reached: true, reach: 0.2, via: "shared tags",
		},
	}
	renderSceneResult(item)
	reasons := item.explanation.get("reasons").arr
	if len(reasons) != 1 || reasons[0].get("code").asString() != "shared_content" {
		t.Fatalf("explanation reasons = %s", item.explanation.get("reasons").marshalCompact())
	}
	if got := item.details.get("multi_hop_via").asString(); got != "shared tags" {
		t.Fatalf("multi_hop_via = %q", got)
	}
	if got := item.details.get("score_breakdown").get("multi_hop").kind; got == jNull {
		t.Fatal("blended score_breakdown lacks multi_hop")
	}
}
