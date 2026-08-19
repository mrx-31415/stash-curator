//go:build unix

package main

import (
	"fmt"
	"os"
	"syscall"
)

func workerFileIdentity(info os.FileInfo) string {
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return ""
	}
	return fmt.Sprintf("%d:%d", stat.Dev, stat.Ino)
}

func terminateWorker(pid int) error {
	return syscall.Kill(pid, syscall.SIGTERM)
}

func forceKillWorker(pid int) error {
	return syscall.Kill(pid, syscall.SIGKILL)
}

// pidAlive reports whether a process with the given pid exists (signal 0).
func pidAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	err := syscall.Kill(pid, 0)
	return err == nil || err == syscall.EPERM
}

// daemonSysProcAttr detaches the worker into its own session so it survives
// the invoking Stash job and Stash restarts.
func daemonSysProcAttr() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{Setsid: true}
}
