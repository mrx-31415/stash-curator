// Python-compatible JSON values for the raw backend transport.
//
// The raw interface contract is byte-identical JSON vs the Python backend
// (plugin/backend.py), which serializes with
// json.dumps(obj, separators=(",", ":")): compact separators, insertion-ordered
// object keys, ensure_ascii string escaping, and Python float repr. Go's
// encoding/json cannot reproduce that (map keys sort alphabetically, HTML
// characters are escaped, floats format differently), so the backend carries
// values as an ordered node type with a purpose-built writer.
package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"sort"
	"strconv"
	"strings"
)

type jKind uint8

const (
	jNull jKind = iota
	jBool
	jNum // number; num holds the raw JSON token
	jStr
	jArr
	jObj
)

type jPair struct {
	key string
	val jVal
}

type jVal struct {
	kind jKind
	b    bool
	num  string
	s    string
	arr  []jVal
	obj  []jPair
}

func jvNull() jVal            { return jVal{kind: jNull} }
func jvBool(v bool) jVal      { return jVal{kind: jBool, b: v} }
func jvNum(token string) jVal { return jVal{kind: jNum, num: token} }
func jvStr(s string) jVal     { return jVal{kind: jStr, s: s} }
func jvInt(v int64) jVal      { return jVal{kind: jNum, num: strconv.FormatInt(v, 10)} }

// jvFloat stores a float with the exact Python repr text as its token, so the
// writer reproduces json.dumps(float) byte for byte.
func jvFloat(f float64) jVal { return jVal{kind: jNum, num: pythonFloatRepr(f)} }

func jvArr(items ...jVal) jVal { return jVal{kind: jArr, arr: items} }

func jvObj(pairs ...jPair) jVal { return jVal{kind: jObj, obj: pairs} }

func jvKey(key string, val jVal) jPair { return jPair{key: key, val: val} }

// get returns the value for key, or jvNull() when the receiver is not an
// object or the key is absent.
func (v jVal) get(key string) jVal {
	if v.kind != jObj {
		return jvNull()
	}
	for _, p := range v.obj {
		if p.key == key {
			return p.val
		}
	}
	return jvNull()
}

func (v jVal) has(key string) bool {
	if v.kind != jObj {
		return false
	}
	for _, p := range v.obj {
		if p.key == key {
			return true
		}
	}
	return false
}

// set appends or replaces a key, preserving insertion order of existing keys
// (Python dict semantics).
func (v *jVal) set(key string, val jVal) {
	if v.kind != jObj {
		return
	}
	for i := range v.obj {
		if v.obj[i].key == key {
			v.obj[i].val = val
			return
		}
	}
	v.obj = append(v.obj, jPair{key: key, val: val})
}

// mergeObjects implements {**a, **b}: b's keys replace a's values in place;
// keys only present in b are appended in b's order.
func mergeObjects(a, b jVal) jVal {
	result := jVal{kind: jObj, obj: append([]jPair(nil), a.obj...)}
	if b.kind != jObj {
		return result
	}
	for _, p := range b.obj {
		result.set(p.key, p.val)
	}
	return result
}

// deepEqual is Python dict/list equality: object key order is irrelevant.
func deepEqual(a, b jVal) bool {
	if a.kind != b.kind {
		return false
	}
	switch a.kind {
	case jNull:
		return true
	case jBool:
		return a.b == b.b
	case jNum:
		return a.num == b.num
	case jStr:
		return a.s == b.s
	case jArr:
		if len(a.arr) != len(b.arr) {
			return false
		}
		for i := range a.arr {
			if !deepEqual(a.arr[i], b.arr[i]) {
				return false
			}
		}
		return true
	case jObj:
		if len(a.obj) != len(b.obj) {
			return false
		}
		for _, p := range a.obj {
			if !deepEqual(p.val, b.get(p.key)) {
				return false
			}
		}
		return true
	}
	return false
}

// parseJSON parses one JSON value, preserving object key order and number
// tokens exactly as Python's json.loads consumes them.
func parseJSON(data []byte) (jVal, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	v, err := decodeValue(dec)
	if err != nil {
		return jVal{}, err
	}
	// Reject trailing content after the value.
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return jVal{}, errors.New("trailing data after JSON value")
		}
		return jVal{}, err
	}
	return v, nil
}

func decodeValue(dec *json.Decoder) (jVal, error) {
	tok, err := dec.Token()
	if err != nil {
		return jVal{}, err
	}
	switch t := tok.(type) {
	case nil:
		return jvNull(), nil
	case bool:
		return jvBool(t), nil
	case json.Number:
		return jvNum(string(t)), nil
	case string:
		return jvStr(t), nil
	case json.Delim:
		switch t {
		case '{':
			obj := jVal{kind: jObj}
			for dec.More() {
				keyTok, err := dec.Token()
				if err != nil {
					return jVal{}, err
				}
				key, ok := keyTok.(string)
				if !ok {
					return jVal{}, errors.New("object key is not a string")
				}
				val, err := decodeValue(dec)
				if err != nil {
					return jVal{}, err
				}
				obj.obj = append(obj.obj, jPair{key: key, val: val})
			}
			if _, err := dec.Token(); err != nil { // consume '}'
				return jVal{}, err
			}
			return obj, nil
		case '[':
			arr := jVal{kind: jArr}
			for dec.More() {
				val, err := decodeValue(dec)
				if err != nil {
					return jVal{}, err
				}
				arr.arr = append(arr.arr, val)
			}
			if _, err := dec.Token(); err != nil { // consume ']'
				return jVal{}, err
			}
			return arr, nil
		}
	}
	return jVal{}, errors.New("unexpected JSON token")
}

// marshalCompact serializes with Python's json.dumps(..., separators=(",", ":"))
// conventions: compact separators, insertion order, ensure_ascii escaping.
func (v jVal) marshalCompact() string {
	var b strings.Builder
	v.writeJSON(&b)
	return b.String()
}

// marshalSortedKeys serializes like json.dumps(obj, sort_keys=True): object
// keys sorted alphabetically at every depth.
func (v jVal) marshalSortedKeys() string {
	var b strings.Builder
	v.writeJSONSorted(&b)
	return b.String()
}

func (v jVal) writeJSON(b *strings.Builder) {
	switch v.kind {
	case jNull:
		b.WriteString("null")
	case jBool:
		if v.b {
			b.WriteString("true")
		} else {
			b.WriteString("false")
		}
	case jNum:
		writeJSONNumber(b, v.num)
	case jStr:
		writeJSONString(b, v.s)
	case jArr:
		b.WriteByte('[')
		for i, item := range v.arr {
			if i > 0 {
				b.WriteByte(',')
			}
			item.writeJSON(b)
		}
		b.WriteByte(']')
	case jObj:
		b.WriteByte('{')
		for i, p := range v.obj {
			if i > 0 {
				b.WriteByte(',')
			}
			writeJSONString(b, p.key)
			b.WriteByte(':')
			p.val.writeJSON(b)
		}
		b.WriteByte('}')
	}
}

// writeJSONRaw is writeJSON with raw-UTF8 string escaping (ensure_ascii=False).
func (v jVal) writeJSONRaw(b *strings.Builder) {
	switch v.kind {
	case jNull:
		b.WriteString("null")
	case jBool:
		if v.b {
			b.WriteString("true")
		} else {
			b.WriteString("false")
		}
	case jNum:
		writeJSONNumber(b, v.num)
	case jStr:
		writeJSONStringRaw(b, v.s)
	case jArr:
		b.WriteByte('[')
		for i, item := range v.arr {
			if i > 0 {
				b.WriteByte(',')
			}
			item.writeJSONRaw(b)
		}
		b.WriteByte(']')
	case jObj:
		b.WriteByte('{')
		for i, p := range v.obj {
			if i > 0 {
				b.WriteByte(',')
			}
			writeJSONStringRaw(b, p.key)
			b.WriteByte(':')
			p.val.writeJSONRaw(b)
		}
		b.WriteByte('}')
	}
}

// writeJSONStringRaw writes a string like writeJSONString but passes code
// points >= U+0080 through raw (Python ensure_ascii=False); control
// characters keep their short forms / \uXXXX escapes.
func writeJSONStringRaw(b *strings.Builder, s string) {
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		default:
			if r < 0x20 {
				fmt.Fprintf(b, `\u%04x`, r)
			} else {
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
}

func (v jVal) writeJSONSorted(b *strings.Builder) {
	switch v.kind {
	case jNull, jBool, jNum, jStr:
		v.writeJSON(b)
	case jArr:
		b.WriteByte('[')
		for i, item := range v.arr {
			if i > 0 {
				b.WriteByte(',')
			}
			item.writeJSONSorted(b)
		}
		b.WriteByte(']')
	case jObj:
		pairs := append([]jPair(nil), v.obj...)
		sort.Slice(pairs, func(i, j int) bool { return pairs[i].key < pairs[j].key })
		b.WriteByte('{')
		for i, p := range pairs {
			if i > 0 {
				b.WriteByte(',')
			}
			writeJSONString(b, p.key)
			b.WriteByte(':')
			p.val.writeJSONSorted(b)
		}
		b.WriteByte('}')
	}
}

// marshalCompactUTF8 serializes like marshalCompact but with Python's
// ensure_ascii=False: code points >= U+0080 pass through raw (control
// characters still use the short forms / \uXXXX escapes).
func (v jVal) marshalCompactUTF8() string {
	var b strings.Builder
	v.writeJSONRaw(&b)
	return b.String()
}

// writeJSONString writes a string with Python ensure_ascii escaping: control
// characters use their short forms or \u00XX, and every code point >= U+0080
// becomes \uXXXX (surrogate pairs for astral code points).
func writeJSONString(b *strings.Builder, s string) {
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\b':
			b.WriteString(`\b`)
		case '\t':
			b.WriteString(`\t`)
		case '\n':
			b.WriteString(`\n`)
		case '\f':
			b.WriteString(`\f`)
		case '\r':
			b.WriteString(`\r`)
		default:
			switch {
			case r < 0x20:
				fmt.Fprintf(b, `\u%04x`, r)
			case r < 0x80:
				b.WriteRune(r)
			case r <= 0xFFFF:
				fmt.Fprintf(b, `\u%04x`, r)
			default:
				r -= 0x10000
				fmt.Fprintf(b, `\u%04x\u%04x`, 0xD800+(r>>10), 0xDC00+(r&0x3FF))
			}
		}
	}
	b.WriteByte('"')
}

// writeJSONNumber reproduces Python: integer tokens pass through verbatim
// (json.loads keeps them int), float tokens are parsed to float64 and
// re-rendered with repr(), and overflow to infinity becomes the bare word
// "Infinity" exactly like json.dumps(float('inf')).
func writeJSONNumber(b *strings.Builder, token string) {
	if !strings.ContainsAny(token, ".eE") {
		b.WriteString(token)
		return
	}
	f, err := strconv.ParseFloat(token, 64)
	if err != nil && errors.Is(err, strconv.ErrRange) {
		if math.IsInf(f, 1) {
			b.WriteString("Infinity")
			return
		}
		if math.IsInf(f, -1) {
			b.WriteString("-Infinity")
			return
		}
	}
	if err != nil {
		b.WriteString(token)
		return
	}
	b.WriteString(pythonFloatRepr(f))
}

// pythonFloatRepr reproduces CPython's repr() for float
// (float_repr_style='short'): the shortest round-tripping digit string, then
// fixed notation when the decimal exponent is in [-4, 15], else scientific
// notation with a two-digit-minimum exponent.
func pythonFloatRepr(f float64) string {
	if math.IsInf(f, 1) {
		return "Infinity"
	}
	if math.IsInf(f, -1) {
		return "-Infinity"
	}
	if math.IsNaN(f) {
		return "NaN"
	}
	neg := f < 0 || (f == 0 && math.Signbit(f))
	abs := math.Abs(f)
	sci := strconv.FormatFloat(abs, 'e', -1, 64) // e.g. "1e+03", "1.2345e-07"
	e := strings.IndexByte(sci, 'e')
	mant := sci[:e]
	exp, _ := strconv.Atoi(sci[e+1:])
	var digits strings.Builder
	for i := range len(mant) {
		if c := mant[i]; c >= '0' && c <= '9' {
			digits.WriteByte(c)
		}
	}
	d := digits.String()
	var out strings.Builder
	if neg {
		out.WriteByte('-')
	}
	if exp >= -4 && exp <= 15 {
		switch {
		case exp >= 0 && exp+1 >= len(d):
			out.WriteString(d)
			for range exp + 1 - len(d) {
				out.WriteByte('0')
			}
			out.WriteString(".0")
		case exp >= 0:
			out.WriteString(d[:exp+1])
			out.WriteByte('.')
			out.WriteString(d[exp+1:])
		default:
			out.WriteString("0.")
			for range -(exp + 1) {
				out.WriteByte('0')
			}
			out.WriteString(d)
		}
	} else {
		out.WriteByte(d[0])
		if len(d) > 1 {
			out.WriteByte('.')
			out.WriteString(d[1:])
		}
		out.WriteByte('e')
		if exp < 0 {
			out.WriteByte('-')
			exp = -exp
		} else {
			out.WriteByte('+')
		}
		if exp < 10 {
			out.WriteByte('0')
		}
		out.WriteString(strconv.Itoa(exp))
	}
	return out.String()
}

// truthy implements Python's bool() on decoded JSON values.
func (v jVal) truthy() bool {
	switch v.kind {
	case jNull:
		return false
	case jBool:
		return v.b
	case jNum:
		f, err := strconv.ParseFloat(v.num, 64)
		return err != nil || f != 0
	case jStr:
		return v.s != ""
	case jArr:
		return len(v.arr) > 0
	case jObj:
		return len(v.obj) > 0
	}
	return false
}

// asString implements Python's str() for scalar JSON values.
func (v jVal) asString() string {
	switch v.kind {
	case jStr:
		return v.s
	case jNum:
		return v.num // integer tokens verbatim; float tokens are already repr-shaped
	case jBool:
		if v.b {
			return "True"
		}
		return "False"
	case jNull:
		return "None"
	}
	return v.marshalCompact()
}

// kindName mirrors Python's type(value).__name__ for decoded JSON values.
func (v jVal) kindName() string {
	switch v.kind {
	case jObj:
		return "dict"
	case jArr:
		return "list"
	case jStr:
		return "str"
	case jBool:
		return "bool"
	case jNull:
		return "NoneType"
	}
	if strings.ContainsAny(v.num, ".eE") {
		return "float"
	}
	return "int"
}

// pyRound implements Python's round() (round half to even) for float64 inputs.
func pyRound(f float64) int64 {
	whole, frac := math.Modf(f)
	i := int64(whole)
	absFrac := math.Abs(frac)
	if absFrac > 0.5 || (absFrac == 0.5 && i%2 != 0) {
		if f >= 0 {
			i++
		} else {
			i--
		}
	}
	return i
}
