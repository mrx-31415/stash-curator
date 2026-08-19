//go:build windows

package main

import (
	"bytes"
	"os"
	"os/exec"
	"strconv"
	"syscall"
)

func workerFileIdentity(os.FileInfo) string { return "" }

func terminateWorker(pid int) error {
	process, err := os.FindProcess(pid)
	if err != nil {
		return err
	}
	return process.Kill()
}

func forceKillWorker(pid int) error {
	return terminateWorker(pid)
}

// pidAlive reports whether a process with the given pid exists. Windows has
// no signal(0); probe the tasklist instead. The "no tasks" info line never
// contains the pid, so matching the pid text is locale-independent.
func pidAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	out, err := exec.Command("tasklist", "/FI", "PID eq "+strconv.Itoa(pid), "/NH").Output()
	if err != nil {
		return false
	}
	return bytes.Contains(out, []byte(strconv.Itoa(pid)))
}

// daemonSysProcAttr gives the worker its own process group so it survives
// the invoking Stash job.
func daemonSysProcAttr() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{CreationFlags: syscall.CREATE_NEW_PROCESS_GROUP}
}
