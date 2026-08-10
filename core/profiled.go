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
	t := beginTrace(name, "operation")
	settings := pluginSettings(payload) // swallows failures, like _settings
	if !settings.get("profilingEnabled").truthy() {
		endTrace(t)
		return body(settings)
	}
	output, err := body(settings)
	if err != nil {
		t.fail(err)
	}
	endTrace(t)
	if saveErr := saveTrace(databasePath(pluginDir, payload, settings), t); saveErr != nil {
		warnLog("Could not save Curator profile: " + saveErr.Error())
	}
	return output, err
}
