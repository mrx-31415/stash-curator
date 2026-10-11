package main

import (
	"fmt"
	"testing"
)

func TestMergeLinkPage(t *testing.T) {
	for _, keepFirst := range []bool{false, true} {
		target := jvObj()
		index := map[string]int{}
		mergeLinkPage(&target, index, jvObj(jvKey("a", jvStr("1")), jvKey("b", jvStr("2"))), keepFirst)
		mergeLinkPage(&target, index, jvObj(jvKey("a", jvStr("3")), jvKey("c", jvStr("4"))), keepFirst)
		want := `{"a":"3","b":"2","c":"4"}`
		if keepFirst {
			want = `{"a":"1","b":"2","c":"4"}`
		}
		if got := target.marshalCompact(); got != want {
			t.Fatalf("keepFirst=%v: %s, want %s", keepFirst, got, want)
		}
	}
}

func BenchmarkMergeLinkPages(b *testing.B) {
	pages := make([]jVal, 48)
	for i := range pages {
		pages[i] = jvObj()
		for j := 0; j < 500; j++ {
			pages[i].obj = append(pages[i].obj, jvKey(fmt.Sprintf("s%d", i*500+j), jvStr("external")))
		}
	}
	for _, indexed := range []bool{false, true} {
		b.Run(fmt.Sprintf("indexed=%v", indexed), func(b *testing.B) {
			for b.Loop() {
				target := jvObj()
				index := map[string]int{}
				for _, page := range pages {
					if indexed {
						mergeLinkPage(&target, index, page, false)
					} else {
						for _, pair := range page.obj {
							target.set(pair.key, pair.val)
						}
					}
				}
			}
		})
	}
}
