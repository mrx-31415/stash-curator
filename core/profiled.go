// Shared _profiled lifecycle for the ported backend operations.
//
// Mirrors backend.py's _profiled wrapper exactly: a trace opens before the
// settings fetch (so the settings GraphQL call records a stash span), the
// body runs inside the trace, and when profilingEnabled is on the trace is
// saved as a profile_trace row even when the body fails. Save failures only
// log a warning, matching Python.
package main

// profiledOperation runs one backend operation under the _profiled lifecycle
// from backend.py: beginTrace(name, "operation"), settings fetch, and a
// saveTrace only when the plugin's profilingEnabled setting is on.
func profiledOperation(pluginDir string, payload jVal, name string, body func(jVal) (jVal, error)) (jVal, error) {
	return profiledKind(pluginDir, payload, name, "operation", body)
}

// profiledKind is profiledOperation with an explicit trace kind; task modes
// record kind "task" (backend.py's _run_task).
func profiledKind(pluginDir string, payload jVal, name, kind string, body func(jVal) (jVal, error)) (jVal, error) {
	t := beginTrace(name, kind)
	settings := pluginSettings(payload) // swallows failures, like _settings
	// On-demand pprof capture (pprofEnabled setting): the CPU profile covers
	// the op body; the heap dump and CPU stop run after the trace is saved.
	stopCPU, dumpMem := startProfilingFor(pluginDir, payload, settings, name)
	if !settings.get("profilingEnabled").truthy() {
		endTrace(t)
		output, err := body(settings)
		stopCPU()
		dumpMem()
		return output, err
	}
	output, err := body(settings)
	if err != nil {
		t.fail(err)
	}
	endTrace(t)
	if saveErr := saveTrace(databasePath(pluginDir, payload, settings), t); saveErr != nil {
		warnLog("Could not save Curator profile: " + saveErr.Error())
	}
	stopCPU()
	dumpMem()
	return output, err
}
