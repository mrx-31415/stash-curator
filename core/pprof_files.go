// Pprof-file ops — list_pprof_files / get_pprof_file / clear_pprof_files:
// browse, download, and clear the Go CPU/heap profiles captured per
// operation when the pprofEnabled setting is on. Files live in
// <sidecar dir>/profiles (the same directory as the sidecar database) and
// are analyzed locally with `go tool pprof`. Like the profile-trace ops,
// these run without the _profiled lifecycle.
package main

import (
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// maxPprofDownloadBytes caps a single file fetch over the plugin op
// response (base64 inflates the payload by a third).
const maxPprofDownloadBytes = 32 << 20

// pprofFile mirrors one .pprof file entry in the profiles directory.
type pprofFile struct {
	name       string
	sizeBytes  int64
	modifiedMs int64
}

// pprofProfilesDir resolves the profiles directory beside the sidecar db.
func pprofProfilesDir(pluginDir string, payload, settings jVal) string {
	return filepath.Join(filepath.Dir(databasePath(pluginDir, payload, settings)), "profiles")
}

// pprofNameValid rejects anything that could escape the profiles directory.
func pprofNameValid(name string) bool {
	if name == "" || strings.ContainsAny(name, `/\`) || strings.Contains(name, "..") {
		return false
	}
	return strings.HasSuffix(name, ".pprof")
}

// listPprofFiles returns the profile files newest-first; a missing
// directory yields an empty list.
func listPprofFiles(dir string) ([]pprofFile, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var files []pprofFile
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".pprof") {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			continue
		}
		files = append(files, pprofFile{
			name:       entry.Name(),
			sizeBytes:  info.Size(),
			modifiedMs: info.ModTime().UnixMilli(),
		})
	}
	sort.Slice(files, func(i, j int) bool { return files[i].modifiedMs > files[j].modifiedMs })
	return files, nil
}

func opListPprofFiles(pluginDir string, payload jVal) (jVal, error) {
	settings := pluginSettings(payload)
	dir := pprofProfilesDir(pluginDir, payload, settings)
	files, err := listPprofFiles(dir)
	if err != nil {
		return jvNull(), err
	}
	items := jvArr()
	for _, f := range files {
		items.arr = append(items.arr, jvObj(
			jvKey("name", jvStr(f.name)),
			jvKey("size_bytes", jvInt(f.sizeBytes)),
			jvKey("modified_ms", jvInt(f.modifiedMs)),
		))
	}
	return jvObj(
		jvKey("enabled", jvBool(settings.get("pprofEnabled").truthy())),
		jvKey("directory", jvStr(dir)),
		jvKey("items", items),
	), nil
}

func opGetPprofFile(pluginDir string, payload jVal) (jVal, error) {
	settings := pluginSettings(payload)
	name := payload.get("args").get("name").asString()
	if !pprofNameValid(name) {
		return jvNull(), fmt.Errorf("invalid pprof file name")
	}
	dir := pprofProfilesDir(pluginDir, payload, settings)
	data, err := os.ReadFile(filepath.Join(dir, name))
	if err != nil {
		return jvNull(), err
	}
	if len(data) > maxPprofDownloadBytes {
		return jvNull(), fmt.Errorf("profile exceeds the %d MiB download limit", maxPprofDownloadBytes>>20)
	}
	return jvObj(
		jvKey("name", jvStr(name)),
		jvKey("size_bytes", jvInt(int64(len(data)))),
		jvKey("content_base64", jvStr(base64.StdEncoding.EncodeToString(data))),
	), nil
}

func opClearPprofFiles(pluginDir string, payload jVal) (jVal, error) {
	settings := pluginSettings(payload)
	dir := pprofProfilesDir(pluginDir, payload, settings)
	files, err := listPprofFiles(dir)
	if err != nil {
		return jvNull(), err
	}
	removed := int64(0)
	for _, f := range files {
		if err := os.Remove(filepath.Join(dir, f.name)); err == nil {
			removed++
		}
	}
	return jvObj(jvKey("removed", jvInt(removed))), nil
}
