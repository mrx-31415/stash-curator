// Raw-plugin backend transport: stdin JSON → dispatch → stdout JSON.
//
// Mirrors plugin/backend.py's wire contract exactly: one JSON object on
// stdin, one {"output": ...} object on stdout on success, {"error": ...} on
// failure with a non-zero exit status, and stderr progress markers of the
// form \x01{level}\x02{message} (level "p" for progress, "i"/"w"/"e" for
// log lines). Every operation, task mode, and the entity-sync hook mode runs
// natively in the binary; unknown operations and task modes error with the
// Python backend's exact messages.
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
	if mode == "daemon" {
		// Worker mode is not a Stash request: no stdin protocol, no output.
		// The daemon exits on its own after an idle period.
		runDaemon(pluginDir)
		return
	}
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
		if mode == "entity-sync" {
			// Stash entity hooks run inline in the mutation path and must
			// never take the task path: no curator_job row, no
			// single-running-job guard, no model build. The hook result is
			// written like any other output.
			writeOutput(runEntityHook(pluginDir, payload))
			return
		}
		// Task modes run under the _profiled "task" lifecycle.
		output, err := runTask(pluginDir, payload, mode)
		if err != nil {
			writeError(err.Error())
		}
		writeOutput(output)
		return
	}
	output, err := dispatch(pluginDir, payload)
	if err != nil {
		writeError(err.Error())
	}
	writeOutput(output)
}

// writeOutput emits {"output": <value>}\n, matching backend.py's success
// path (json.dumps({"output": output}, separators=(",", ":"))).
func writeOutput(output jVal) {
	var b strings.Builder
	b.WriteString(`{"output":`)
	output.writeJSON(&b)
	b.WriteString("}\n")
	if _, err := os.Stdout.WriteString(b.String()); err != nil {
		fail("write output: %v", err)
	}
}

// taskModeNative reports whether the binary serves a task mode natively;
// unknown modes error like Python's "unknown Curator task" (runTaskMode).
func taskModeNative(mode string) bool {
	switch mode {
	case "backup", "compact", "vacuum", "prepare", "sync-plays", "expand-refresh",
		"build", "update-model", "sync-build", "full-sync-build":
		return true
	}
	return false
}

// dispatch implements backend.py's dispatch(): every operation the frontend
// or Stash can invoke runs natively; an unknown operation errors with
// Python's exact message.
func dispatch(pluginDir string, payload jVal) (jVal, error) {
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
	case "get_score_review":
		return opGetScoreReview(pluginDir, payload)
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
	case "list_pprof_files":
		return opListPprofFiles(pluginDir, payload)
	case "get_pprof_file":
		return opGetPprofFile(pluginDir, payload)
	case "get_pprof_summary":
		return opGetPprofSummary(pluginDir, payload)
	case "clear_pprof_files":
		return opClearPprofFiles(pluginDir, payload)
	case "get_external_tag_choices":
		return opGetExternalTagChoices(pluginDir, payload)
	case "get_scene_tag_choices":
		return opGetSceneTagChoices(pluginDir, payload)
	case "get_scene_description_tokens":
		return opGetSceneDescriptionTokens(pluginDir, payload)
	case "submit_term_preferences":
		return opSubmitTermPreferences(pluginDir, payload)
	case "get_inspector_entity":
		return opGetInspectorEntity(pluginDir, payload)
	case "get_tag_sentiment_follow_up":
		return opGetTagSentimentFollowUp(pluginDir, payload)
	case "get_curation_batch":
		return opGetCurationBatch(pluginDir, payload)
	case "submit_curation_ratings":
		return opSubmitCurationRatings(pluginDir, payload)
	case "get_curation_verdict":
		return opGetCurationVerdict(pluginDir, payload)
	case "get_tag_context_candidates":
		return opGetTagContextCandidates(pluginDir, payload)
	case "get_curation_picks":
		return opGetCurationPicks(pluginDir, payload)
	case "submit_curation_picks":
		return opSubmitCurationPicks(pluginDir, payload)
	case "get_curation_pair_verdict":
		return opGetCurationPairVerdict(pluginDir, payload)
	case "get_curation_impact":
		return opGetCurationImpact(pluginDir, payload)
	case "reset":
		return opReset(pluginDir, payload)
	case "cancel_job":
		return opCancelJob(pluginDir, payload)
	default:
		return jvNull(), fmt.Errorf("unknown Curator API operation: %s", operation)
	}
}
