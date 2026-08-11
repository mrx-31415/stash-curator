// Entity-hook mode — a port of plugin/backend.py's _run_entity_hook: enqueue
// a changed entity after a Stash create/update/destroy hook. Hooks run inline
// inside Stash's mutation path, so this stays tiny: one bounded write, no
// GraphQL fetch, no curator_job row, no model build. The fetch and upsert
// happen in the drain that precedes a preference rebuild (tasks.go's
// drainPendingEntityChanges). Stash logs hook failures without failing the
// mutation; this logs and returns a neutral result instead of raising.
package main

import (
	"context"
	"database/sql"
	"strings"
)

// hookEntityTypes mirrors backend.py's _HOOK_ENTITY_TYPES. Tag merges are
// left to the next regular sync: a merge re-links many scenes that a single
// tag upsert cannot refresh.
var hookEntityTypes = map[string]string{
	"Scene.Create.Post":      "scene",
	"Scene.Update.Post":      "scene",
	"Scene.Destroy.Post":     "scene",
	"Performer.Create.Post":  "performer",
	"Performer.Update.Post":  "performer",
	"Performer.Destroy.Post": "performer",
	"Studio.Create.Post":     "studio",
	"Studio.Update.Post":     "studio",
	"Studio.Destroy.Post":    "studio",
	"Tag.Create.Post":        "tag",
	"Tag.Update.Post":        "tag",
	"Tag.Destroy.Post":       "tag",
}

// runEntityHook mirrors _run_entity_hook: it never raises; every failure
// logs a warning and returns {"handled": false, "reason": ...}.
func runEntityHook(pluginDir string, payload jVal) jVal {
	settings := pluginSettings(payload)
	args := payload.get("args")
	hookContext := args.get("hookContext")
	if hookContext.kind != jObj {
		return jvObj(
			jvKey("handled", jvBool(false)),
			jvKey("reason", jvStr("missing hookContext")),
		)
	}
	hookType := pythonStrOrEmpty(hookContext.get("type"))
	entityType, known := hookEntityTypes[hookType]
	if !known {
		return jvObj(
			jvKey("handled", jvBool(false)),
			jvKey("hook_type", jvStr(hookType)),
		)
	}
	entityID := pythonStrOrEmpty(hookContext.get("id"))
	if entityID == "" {
		return jvObj(
			jvKey("handled", jvBool(false)),
			jvKey("hook_type", jvStr(hookType)),
			jvKey("reason", jvStr("missing entity id")),
		)
	}
	operation := "upsert"
	if strings.HasSuffix(hookType, ".Destroy.Post") {
		operation = "delete"
	}
	db, err := openSidecar(pluginDir, payload, settings, false)
	if err != nil {
		warnLog("Curator entity hook failed: " + err.Error())
		return neutralHookResult(err)
	}
	defer db.Close()
	now := nowMs()
	err = withTxn(db, func(conn *sql.Conn) error {
		ctx := context.Background()
		if _, err := conn.ExecContext(ctx, `
INSERT INTO pending_entity_change(
    entity_type, entity_id, operation, created_at_ms
) VALUES (?, ?, ?, ?)
ON CONFLICT(entity_type, entity_id) DO UPDATE SET
    operation=excluded.operation, created_at_ms=excluded.created_at_ms`,
			entityType, entityID, operation, now); err != nil {
			return err
		}
		return coordinatorRequest(conn, "entity_hook", now)
	})
	if err != nil {
		warnLog("Curator entity hook failed: " + err.Error())
		return neutralHookResult(err)
	}
	return jvObj(
		jvKey("handled", jvBool(true)),
		jvKey("hook_type", jvStr(hookType)),
		jvKey("entity_type", jvStr(entityType)),
		jvKey("entity_id", jvStr(entityID)),
		jvKey("enqueued", jvBool(true)),
	)
}

// neutralHookResult mirrors the _run_entity_hook except-branch: a warning was
// already logged; the hook returns a neutral, non-raising result with the
// error message truncated to 500 characters like backend.py's str(error)[:500].
func neutralHookResult(err error) jVal {
	message := err.Error()
	if len(message) > 500 {
		message = message[:500]
	}
	return jvObj(
		jvKey("handled", jvBool(false)),
		jvKey("reason", jvStr(message)),
	)
}
