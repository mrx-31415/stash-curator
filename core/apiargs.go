// Argument coercion for the ported API operations, mirroring backend.py's
// _api shell: Python str()/int()/float()/bool() semantics on JSON values,
// _string_list validation with Python's exact error messages, and the
// exclude_scene_ids set coercion every op shares.
package main

import (
	"fmt"
	"strings"
)

// stringList mirrors backend.py's _string_list: None -> (), a list of at
// most 50 strings of at most 100 characters, else the exact ValueError
// messages.
func stringList(v jVal) ([]string, error) {
	if v.kind == jNull {
		return nil, nil
	}
	if v.kind != jArr || len(v.arr) > 50 {
		return nil, fmt.Errorf("filter values must be a list of at most 50 strings")
	}
	result := make([]string, len(v.arr))
	for i, item := range v.arr {
		if item.kind != jStr || len(item.s) > 100 {
			return nil, fmt.Errorf("filter values must be strings up to 100 characters")
		}
		result[i] = item.s
	}
	return result, nil
}

// excludeSceneIDs mirrors backend.py's get_slate/get_similar argument
// handling: the value must be a list, and the exclusion set is
// {str(value) for value in excluded}.
func excludeSceneIDs(v jVal) (map[string]bool, error) {
	if v.kind == jNull {
		return map[string]bool{}, nil
	}
	if v.kind != jArr {
		return nil, fmt.Errorf("exclude_scene_ids must be a list")
	}
	result := make(map[string]bool, len(v.arr))
	for _, item := range v.arr {
		result[item.asString()] = true
	}
	return result, nil
}

// argsInt mirrors Python's `int(args.get(key) or fallback)`.
func argsInt(args jVal, key string, fallback int64) int64 {
	v := args.get(key)
	if !v.truthy() {
		return fallback
	}
	return pythonInt(v)
}

// argsString mirrors Python's `str(args.get(key) or fallback)`.
func argsString(args jVal, key string, fallback string) string {
	v := args.get(key)
	if !v.truthy() {
		return fallback
	}
	return v.asString()
}

// argsOptionalString mirrors Python's `str(args[key]) if args.get(key) else None`.
func argsOptionalString(args jVal, key string) jVal {
	v := args.get(key)
	if !v.truthy() {
		return jvNull()
	}
	return jvStr(v.asString())
}

// argsFloat mirrors Python's `float(args.get(key) or fallback)`.
func argsFloat(args jVal, key string, fallback float64) float64 {
	v := args.get(key)
	if !v.truthy() {
		return fallback
	}
	f, err := pythonFloat(v)
	if err != nil {
		return fallback
	}
	return f
}

// argsBool mirrors Python's `bool(args.get(key, default))`.
func argsBool(args jVal, key string, def bool) bool {
	v := args.get(key)
	if v.kind == jNull {
		return def
	}
	return v.truthy()
}

// isList mirrors Python's isinstance(value, list).
func isList(v jVal) bool { return v.kind == jArr }

// pythonLower mirrors Python's str.casefold() on a string value (ASCII here;
// casefold is used only against SQL-provided lane/job strings).
func pythonLower(s string) string { return strings.ToLower(s) }
