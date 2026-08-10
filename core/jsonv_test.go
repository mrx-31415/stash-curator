package main

import (
	"math"
	"testing"
)

// Float repr expectations verified against CPython 3.12 repr() (float_repr_style='short').
func TestPythonFloatRepr(t *testing.T) {
	cases := []struct {
		input  float64
		expect string
	}{
		{0.0, "0.0"},
		{math.Copysign(0, -1), "-0.0"},
		{1.0, "1.0"},
		{0.5, "0.5"},
		{1000.0, "1000.0"},
		{1000.5, "1000.5"},
		{123456789.0, "123456789.0"},
		{1e15, "1000000000000000.0"},
		{1e16, "1e+16"},
		{1.5e16, "1.5e+16"},
		{2.5e15, "2500000000000000.0"},
		{0.1, "0.1"},
		{0.0001, "0.0001"},
		{1e-5, "1e-05"},
		{1e-100, "1e-100"},
		{1.2345678901234567e-5, "1.2345678901234568e-05"},
		{0.30000000000000004, "0.30000000000000004"},
		{3.141592653589793, "3.141592653589793"},
		{1e20, "1e+20"},
		{0.00015, "0.00015"},
		{123.456, "123.456"},
		{2.0, "2.0"},
		{7e22, "7e+22"},
		{0.7, "0.7"},
		{2.5, "2.5"},
		{-2.5, "-2.5"},
		{1e21, "1e+21"},
		{1e-9, "1e-09"},
		{4.9406564584124654e-324, "5e-324"},
		{1.7976931348623157e308, "1.7976931348623157e+308"},
		{0.000001, "1e-06"},
		{0.00001, "1e-05"},
		{0.0001, "0.0001"},
	}
	for _, c := range cases {
		if got := pythonFloatRepr(c.input); got != c.expect {
			t.Errorf("pythonFloatRepr(%v) = %q, want %q", c.input, got, c.expect)
		}
	}
}

// String escaping follows json.dumps ensure_ascii=True.
func TestWriteJSONString(t *testing.T) {
	// Input contains: quote, backslash, control chars, DEL, and non-ASCII.
	input := "\"\\\n\t\r\b\f\x01\x7f" + "é中😀"
	expect := `"\"\\\n\t\r\b\f\u0001` + "\x7f" + `\u00e9\u4e2d\ud83d\ude00"` // DEL byte left literal, like Python
	if got := marshalJSONString(input); got != expect {
		t.Errorf("writeJSONString = %s, want %s", got, expect)
	}
}

func TestMarshalCompactPreservesOrder(t *testing.T) {
	v := jvObj(
		jvKey("b", jvInt(2)),
		jvKey("a", jvInt(1)),
		jvKey("nested", jvObj(
			jvKey("z", jvBool(true)),
			jvKey("y", jvNull()),
			jvKey("list", jvArr(jvStr("x"), jvInt(3), jvFloat(0.5))),
		)),
	)
	got := v.marshalCompact()
	expect := `{"b":2,"a":1,"nested":{"z":true,"y":null,"list":["x",3,0.5]}}`
	if got != expect {
		t.Errorf("marshalCompact = %s, want %s", got, expect)
	}
}

func TestMarshalSortedKeys(t *testing.T) {
	v := jvObj(
		jvKey("page_size", jvInt(20)),
		jvKey("diversity_enabled", jvBool(true)),
	)
	got := v.marshalSortedKeys()
	expect := `{"diversity_enabled":true,"page_size":20}`
	if got != expect {
		t.Errorf("marshalSortedKeys = %s, want %s", got, expect)
	}
}

// Numbers round-trip the way Python's json.loads + json.dumps do: ints stay
// verbatim, floats re-render via repr (so "0.10" becomes "0.1"), overflow
// becomes the bare Infinity word.
func TestWriteJSONNumber(t *testing.T) {
	cases := []struct {
		token  string
		expect string
	}{
		{"1", "1"},
		{"-42", "-42"},
		{"1.0", "1.0"},
		{"0.10", "0.1"},
		{"1e3", "1000.0"},
		{"1e16", "1e+16"},
		{"0.0001", "0.0001"},
		{"1e999", "Infinity"},
		{"-1e999", "-Infinity"},
		{"1e-999", "0.0"},
		{"123456789012345678901234567890", "123456789012345678901234567890"},
	}
	for _, c := range cases {
		got := jvNum(c.token).marshalCompact()
		if got != c.expect {
			t.Errorf("number %s = %s, want %s", c.token, got, c.expect)
		}
	}
}

func TestParseJSONPreservesOrderAndNumbers(t *testing.T) {
	raw := `{"zeta":1,"alpha":{"num":0.10,"str":"s","nul":null,"arr":[true,1e3]},"flag":false}`
	v, err := parseJSON([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	// Object key order preserved.
	keys := []string{}
	for _, p := range v.obj {
		keys = append(keys, p.key)
	}
	if len(keys) != 3 || keys[0] != "zeta" || keys[1] != "alpha" || keys[2] != "flag" {
		t.Fatalf("key order = %v", keys)
	}
	// Float token re-rendered through repr (Python behavior).
	got := v.marshalCompact()
	expect := `{"zeta":1,"alpha":{"num":0.1,"str":"s","nul":null,"arr":[true,1000.0]},"flag":false}`
	if got != expect {
		t.Errorf("round trip = %s, want %s", got, expect)
	}
}

func TestDeepEqualIgnoresObjectKeyOrder(t *testing.T) {
	a := jvObj(jvKey("x", jvInt(1)), jvKey("y", jvArr(jvStr("s"))))
	b := jvObj(jvKey("y", jvArr(jvStr("s"))), jvKey("x", jvInt(1)))
	if !deepEqual(a, b) {
		t.Error("deepEqual should ignore object key order")
	}
	c := jvObj(jvKey("x", jvInt(2)), jvKey("y", jvArr(jvStr("s"))))
	if deepEqual(a, c) {
		t.Error("deepEqual should notice value changes")
	}
}

func TestPyRound(t *testing.T) {
	cases := []struct {
		input  float64
		expect int64
	}{
		{30.0 * 60_000, 1_800_000},
		{0.5, 0},
		{1.5, 2},
		{2.5, 2},
		{3.5, 4},
		{-2.5, -2},
		{1.25, 1},
		{1.75, 2},
	}
	for _, c := range cases {
		if got := pyRound(c.input); got != c.expect {
			t.Errorf("pyRound(%v) = %d, want %d", c.input, got, c.expect)
		}
	}
}

func TestMergeObjects(t *testing.T) {
	def := jvObj(jvKey("a", jvInt(1)), jvKey("b", jvInt(2)))
	stored := jvObj(jvKey("b", jvInt(9)), jvKey("c", jvInt(3)))
	merged := mergeObjects(def, stored)
	expect := `{"a":1,"b":9,"c":3}`
	if got := merged.marshalCompact(); got != expect {
		t.Errorf("mergeObjects = %s, want %s", got, expect)
	}
}
