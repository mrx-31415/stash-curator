// Plugin settings application and config merge/validation — a port of
// backend.py's _apply_plugin_settings and CuratorAPI._validate_config. The
// byte-level contract is preserved: config_json is written with sorted keys
// (json.dumps(sort_keys=True)) and the merged config follows Python dict
// insertion order.
package main

import (
	"fmt"
	"strconv"
	"strings"
)

// defaultPluginConfig mirrors curator/api.py DEFAULT_PLUGIN_CONFIG in
// insertion order (get_config and config() output key order).
var defaultPluginConfig = jvObj(
	jvKey("page_size", jvInt(20)),
	jvKey("diversity_enabled", jvBool(true)),
	jvKey("sync_page_size", jvInt(250)),
	jvKey("debounce_ms", jvInt(2000)),
	jvKey("model_update_event_threshold", jvInt(5)),
	jvKey("model_update_max_wait_minutes", jvInt(30)),
	jvKey("model_update_min_interval_minutes", jvInt(60)),
	jvKey("prune_tag_name", jvStr("[Prune]")),
	jvKey("expand_horizon_days", jvInt(90)),
	jvKey("expand_gender", jvStr("FEMALE")),
	jvKey("expand_wildcard", jvBool(false)),
	jvKey("auto_tasks_enabled", jvBool(false)),
	jvKey("schedule_expand_refresh_enabled", jvBool(false)),
	jvKey("schedule_expand_refresh_interval_hours", jvInt(24)),
	jvKey("schedule_expand_refresh_at_hour", jvNull()),
	jvKey("schedule_sync_build_enabled", jvBool(false)),
	jvKey("schedule_sync_build_interval_hours", jvInt(24)),
	jvKey("schedule_sync_build_at_hour", jvNull()),
	jvKey("schedule_backup_enabled", jvBool(false)),
	jvKey("schedule_backup_interval_hours", jvInt(24)),
	jvKey("schedule_backup_at_hour", jvNull()),
)

type settingConv int

const (
	convInt settingConv = iota
	convFloat
	convStr
	convBool
)

// settingMapping mirrors backend.py's _apply_plugin_settings mapping:
// Stash setting name → (sidecar config key, converter).
var settingMapping = []struct {
	source string
	key    string
	conv   settingConv
}{
	{"pageSize", "page_size", convInt},
	{"syncPageSize", "sync_page_size", convInt},
	{"modelUpdateEventThreshold", "model_update_event_threshold", convInt},
	{"modelUpdateMaxWaitMinutes", "model_update_max_wait_minutes", convFloat},
	{"modelUpdateMinIntervalMinutes", "model_update_min_interval_minutes", convFloat},
	{"pruneTagName", "prune_tag_name", convStr},
	{"expandHorizonDays", "expand_horizon_days", convInt},
	{"expandGender", "expand_gender", convStr},
	{"expandWildcard", "expand_wildcard", convBool},
	{"autoTasksEnabled", "auto_tasks_enabled", convBool},
	{"scheduleExpandRefreshEnabled", "schedule_expand_refresh_enabled", convBool},
	{"scheduleExpandRefreshIntervalHours", "schedule_expand_refresh_interval_hours", convFloat},
	{"scheduleExpandRefreshAtHour", "schedule_expand_refresh_at_hour", convInt},
	{"scheduleSyncBuildEnabled", "schedule_sync_build_enabled", convBool},
	{"scheduleSyncBuildIntervalHours", "schedule_sync_build_interval_hours", convFloat},
	{"scheduleSyncBuildAtHour", "schedule_sync_build_at_hour", convInt},
	{"scheduleBackupEnabled", "schedule_backup_enabled", convBool},
	{"scheduleBackupIntervalHours", "schedule_backup_interval_hours", convFloat},
	{"scheduleBackupAtHour", "schedule_backup_at_hour", convInt},
}

func convertSetting(v jVal, conv settingConv) (jVal, error) {
	switch conv {
	case convInt:
		n, err := pythonIntErr(v)
		if err != nil {
			return jvNull(), err
		}
		return jvInt(n), nil
	case convFloat:
		f, err := pythonFloat(v)
		if err != nil {
			return jvNull(), err
		}
		return jvFloat(f), nil
	case convStr:
		return jvStr(v.asString()), nil
	case convBool:
		return jvBool(v.truthy()), nil
	}
	return jvNull(), fmt.Errorf("unknown setting conversion")
}

// pythonIntErr implements Python's int() on decoded JSON values: ints
// verbatim, floats truncated toward zero, strings parsed, booleans 1/0.
func pythonIntErr(v jVal) (int64, error) {
	switch v.kind {
	case jNum:
		if !strings.ContainsAny(v.num, ".eE") {
			return strconv.ParseInt(v.num, 10, 64)
		}
		f, err := strconv.ParseFloat(v.num, 64)
		if err != nil {
			return 0, fmt.Errorf("invalid literal for int(): %s", v.num)
		}
		return int64(f), nil
	case jStr:
		n, err := strconv.ParseInt(strings.TrimSpace(v.s), 10, 64)
		if err != nil {
			return 0, fmt.Errorf("invalid literal for int() with base 10: %q", v.s)
		}
		return n, nil
	case jBool:
		if v.b {
			return 1, nil
		}
		return 0, nil
	}
	return 0, fmt.Errorf("int() argument must be a number or string")
}

// pythonInt is pythonIntErr with errors collapsed to zero (callers that only
// accept well-formed payloads).
func pythonInt(v jVal) int64 {
	n, _ := pythonIntErr(v)
	return n
}

func pythonFloat(v jVal) (float64, error) {
	switch v.kind {
	case jNum:
		return strconv.ParseFloat(v.num, 64)
	case jStr:
		return strconv.ParseFloat(strings.TrimSpace(v.s), 64)
	case jBool:
		if v.b {
			return 1, nil
		}
		return 0, nil
	}
	return 0, fmt.Errorf("could not convert value to float")
}

// applyPluginSettings mirrors backend.py's _apply_plugin_settings.
func applyPluginSettings(db dbx, settings jVal, nowMs int64) error {
	if settings.kind != jObj {
		return nil
	}
	overrides := jvObj()
	for _, item := range settingMapping {
		v := settings.get(item.source)
		if v.kind == jNull || (v.kind == jStr && v.s == "") {
			continue // settings.get(source) not in (None, "")
		}
		converted, err := convertSetting(v, item.conv)
		if err != nil {
			return err
		}
		overrides.set(item.key, converted)
	}
	if settings.has("diversityDisabled") {
		overrides.set("diversity_enabled", jvBool(!settings.get("diversityDisabled").truthy()))
	}
	if len(overrides.obj) == 0 {
		return nil
	}
	var configJSON string
	var updatedAtMs int64
	err := db.QueryRow(`SELECT config_json, updated_at_ms FROM curator_config WHERE singleton=1`).
		Scan(&configJSON, &updatedAtMs)
	if err != nil {
		return err
	}
	current, err := parseJSON([]byte(configJSON))
	if err != nil {
		return err
	}
	merged := mergeObjects(current, overrides)
	effective := mergeObjects(defaultPluginConfig, current)
	validated := mergeObjects(effective, overrides)
	if err := validateConfig(validated); err != nil {
		return err
	}
	if deepEqual(merged, current) {
		return nil
	}
	_, err = db.Exec(`UPDATE curator_config SET config_json=?, updated_at_ms=? WHERE singleton=1`,
		merged.marshalSortedKeys(), nowMs)
	return err
}

// sidecarConfig mirrors CuratorAPI.config(): {**DEFAULT_PLUGIN_CONFIG, **stored}.
func sidecarConfig(db dbx) (jVal, error) {
	var configJSON string
	var updatedAtMs int64
	err := db.QueryRow(`SELECT config_json, updated_at_ms FROM curator_config WHERE singleton=1`).
		Scan(&configJSON, &updatedAtMs)
	if err != nil {
		return jvNull(), err
	}
	stored, err := parseJSON([]byte(configJSON))
	if err != nil {
		return jvNull(), err
	}
	config := mergeObjects(defaultPluginConfig, stored)
	return jvObj(
		jvKey("schema_version", jvInt(1)),
		jvKey("config", config),
		jvKey("updated_at_ms", jvInt(updatedAtMs)),
	), nil
}

// validateConfig mirrors CuratorAPI._validate_config, including the exact
// error messages the Python side raises.
func validateConfig(values jVal) error {
	if v := values.get("diversity_enabled"); v.kind != jNull && v.kind != jBool {
		return fmt.Errorf("diversity_enabled must be true or false")
	}
	for _, key := range []string{"schedule_expand_refresh_at_hour", "schedule_sync_build_at_hour", "schedule_backup_at_hour"} {
		v := values.get(key)
		if v.kind == jNull {
			continue
		}
		if !isJSONInt(v) || pythonInt(v) < 0 || pythonInt(v) > 23 {
			return fmt.Errorf("%s must be an integer from 0 to 23", key)
		}
	}
	for _, key := range []string{"page_size", "sync_page_size"} {
		v := values.get(key)
		if v.kind == jNull {
			continue
		}
		if !isJSONInt(v) {
			return fmt.Errorf("%s must be an integer from 1 to 500", key)
		}
		n := pythonInt(v)
		if n < 1 || n > 500 {
			return fmt.Errorf("%s must be an integer from 1 to 500", key)
		}
	}
	if v := values.get("debounce_ms"); v.kind != jNull {
		if !isJSONInt(v) {
			return fmt.Errorf("debounce_ms must be an integer from 0 to 60000")
		}
		n := pythonInt(v)
		if n < 0 || n > 60_000 {
			return fmt.Errorf("debounce_ms must be an integer from 0 to 60000")
		}
	}
	if v := values.get("model_update_event_threshold"); v.kind != jNull {
		if !isJSONInt(v) {
			return fmt.Errorf("model_update_event_threshold must be an integer from 1 to 100")
		}
		n := pythonInt(v)
		if n < 1 || n > 100 {
			return fmt.Errorf("model_update_event_threshold must be an integer from 1 to 100")
		}
	}
	for _, key := range []string{"model_update_max_wait_minutes", "model_update_min_interval_minutes"} {
		v := values.get(key)
		if v.kind == jNull {
			continue
		}
		if !isJSONNumber(v) {
			return fmt.Errorf("%s must be between 1 and 1440", key)
		}
		f, err := pythonFloat(v)
		if err != nil || f < 1 || f > 24*60 {
			return fmt.Errorf("%s must be between 1 and 1440", key)
		}
	}
	if v := values.get("prune_tag_name"); v.kind != jNull {
		if v.kind != jStr || strings.TrimSpace(v.s) == "" || len(v.s) > 100 {
			return fmt.Errorf("prune_tag_name must be a non-empty string up to 100 characters")
		}
	}
	if v := values.get("expand_horizon_days"); v.kind != jNull {
		if !isJSONInt(v) {
			return fmt.Errorf("expand_horizon_days must be an integer from 1 to 3650")
		}
		n := pythonInt(v)
		if n < 1 || n > 3650 {
			return fmt.Errorf("expand_horizon_days must be an integer from 1 to 3650")
		}
	}
	if v := values.get("expand_gender"); v.kind != jNull && v.kind != jStr {
		return fmt.Errorf("expand_gender must be a string")
	}
	if v := values.get("expand_wildcard"); v.kind != jNull && v.kind != jBool {
		return fmt.Errorf("expand_wildcard must be true or false")
	}
	return nil
}

// isJSONInt distinguishes integer JSON tokens from float tokens the way
// Python's json.loads does (int vs float).
func isJSONInt(v jVal) bool {
	return v.kind == jNum && !strings.ContainsAny(v.num, ".eE")
}

func isJSONNumber(v jVal) bool {
	return v.kind == jNum
}
