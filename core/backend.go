// Raw-plugin backend transport: stdin JSON → dispatch → stdout JSON.
//
// Mirrors plugin/backend.py's wire contract exactly: one JSON object on
// stdin, one {"output": ...} object on stdout on success, {"error": ...} on
// failure with a non-zero exit status, and stderr progress markers of the
// form \x01{level}\x02{message} (level "p" for progress, "i"/"w"/"e" for
// log lines). The binary implements the ported Slice-0 operations itself;
// every other operation, task mode, and the entity-sync hook mode is
// delegated to the bundled backend.py with the same argv/stdin contract
// (fallback.go).
package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// resolvePluginDir mirrors backend.py's PLUGIN_DIR: argv[1] resolved to a
// real path, or the directory of the running binary when absent.
func resolvePluginDir(arg string) string {
	if arg != "" {
		return realpath(arg)
	}
	exe, err := os.Executable()
	if err != nil {
		return "."
	}
	return realpath(filepath.Dir(exe))
}

// realpath approximates Python's Path.resolve(): absolute + symlinks resolved.
func realpath(path string) string {
	abs, err := filepath.Abs(path)
	if err != nil {
		abs = filepath.Clean(path)
	}
	if resolved, err := filepath.EvalSymlinks(abs); err == nil {
		return resolved
	}
	return filepath.Clean(abs)
}

// writeError emits {"error": <message>} and exits 1, matching backend.py's
// failure path (str(error) plus SystemExit(1)).
func writeError(message string) {
	fmt.Printf(`{"error":%s}`+"\n", marshalJSONString(message))
	os.Exit(1)
}

func marshalJSONString(s string) string {
	var b strings.Builder
	writeJSONString(&b, s)
	return b.String()
}

func runBackend(pluginDir, mode string) {
	pluginDir = resolvePluginDir(pluginDir)
	payloadBytes, err := io.ReadAll(os.Stdin)
	if err != nil {
		writeError("could not read plugin input: " + err.Error())
	}
	payload, err := parseJSON(payloadBytes)
	if err != nil {
		writeError(err.Error())
	}
	if payload.kind != jObj {
		writeError("plugin input must be an object")
	}

	if mode != "" {
		// Task modes run under the _profiled "task" lifecycle. The
		// entity-sync hook mode and unported task modes keep the Python
		// fallback.
		if mode == "entity-sync" || !taskModeNative(mode) {
			fallbackToPython(pluginDir, mode, payloadBytes)
		}
		output, err := runTask(pluginDir, payload, mode)
		if err != nil {
			writeError(err.Error())
		}
		var b strings.Builder
		b.WriteString(`{"output":`)
		output.writeJSON(&b)
		b.WriteString("}\n")
		if _, err := os.Stdout.WriteString(b.String()); err != nil {
			fail("write output: %v", err)
		}
		return
	}
	output, err := dispatch(pluginDir, payload, payloadBytes)
	if err != nil {
		writeError(err.Error())
	}
	var b strings.Builder
	b.WriteString(`{"output":`)
	output.writeJSON(&b)
	b.WriteString("}\n")
	if _, err := os.Stdout.WriteString(b.String()); err != nil {
		fail("write output: %v", err)
	}
}

// taskModeNative reports whether the binary serves a task mode natively; the
// rest keep the Python fallback (backend.go's runBackend consults it).
func taskModeNative(mode string) bool {
	switch mode {
	case "backup", "compact", "vacuum", "prepare", "sync-plays", "expand-refresh":
		return true
	}
	return false
}

// dispatch implements backend.py's dispatch(): the ported operations run
// natively; anything else falls back to the Python backend with the raw
// payload bytes (fallbackToPython never returns).
func dispatch(pluginDir string, payload jVal, raw []byte) (jVal, error) {
	args := payload.get("args")
	operation := "health"
	if args.kind == jObj {
		// Python: str((payload.get("args") or {}).get("operation") or "health")
		if op := args.get("operation"); op.truthy() {
			operation = op.asString()
		}
	}
	switch operation {
	case "health":
		return opHealth(pluginDir, payload)
	case "round_trip":
		return opRoundTrip(pluginDir, payload)
	case "get_config":
		return opGetConfig(pluginDir, payload)
	case "get_job_status":
		return opGetJobStatus(pluginDir, payload)
	case "get_slate":
		return opGetSlate(pluginDir, payload)
	case "replace_item":
		return opReplaceItem(pluginDir, payload)
	case "get_similar":
		return opGetSimilar(pluginDir, payload)
	case "get_explanation":
		return opGetExplanation(pluginDir, payload)
	case "get_recommendation_history":
		return opGetRecommendationHistory(pluginDir, payload)
	case "get_shortlist":
		return opGetShortlist(pluginDir, payload)
	case "get_feedback_history":
		return opGetFeedbackHistory(pluginDir, payload)
	case "get_taste_profile":
		return opGetTasteProfile(pluginDir, payload)
	case "get_diagnostics":
		return opGetDiagnostics(pluginDir, payload)
	case "get_expand":
		return opGetExpand(pluginDir, payload)
	case "get_performer_hunt":
		return opGetPerformerHunt(pluginDir, payload)
	case "get_external_similar":
		return opGetExternalSimilar(pluginDir, payload)
	case "send_whisparr":
		return opSendWhisparr(pluginDir, payload)
	case "list_backups", "create_backup", "restore_backup", "delete_backup":
		return opBackupControl(pluginDir, payload)
	case "update_shortlist":
		return opUpdateShortlist(pluginDir, payload)
	case "submit_feedback":
		return opSubmitFeedback(pluginDir, payload)
	case "correct_feedback":
		return opCorrectFeedback(pluginDir, payload)
	case "submit_tag_preferences":
		return opSubmitTagPreferences(pluginDir, payload)
	case "submit_events":
		return opSubmitEvents(pluginDir, payload)
	case "update_config":
		return opUpdateConfig(pluginDir, payload)
	case "get_pruning_queue":
		return opGetPruningQueue(pluginDir, payload)
	case "get_prune_candidates":
		return opGetPruneCandidates(pluginDir, payload)
	case "dismiss_prune_candidate":
		return opDismissPruneCandidate(pluginDir, payload)
	case "set_prune_tag":
		return opSetPruneTag(pluginDir, payload)
	case "update_pruning":
		return opUpdatePruning(pluginDir, payload)
	case "get_exclusions":
		return opGetExclusions(pluginDir, payload)
	case "reverse_exclusion":
		return opReverseExclusion(pluginDir, payload)
	case "list_profiles":
		return opListProfiles(pluginDir, payload)
	case "get_profile":
		return opGetProfile(pluginDir, payload)
	case "clear_profiles":
		return opClearProfiles(pluginDir, payload)
	default:
		fallbackToPython(pluginDir, "", raw)
	}
	return jvNull(), nil // unreachable; fallbackToPython exits
}
