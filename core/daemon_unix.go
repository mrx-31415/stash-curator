//go:build unix

package main

import (
	"bytes"
	"fmt"
	"os"
	"syscall"
)

func workerPidIsWorker(pid int, pluginDir string) bool {
	cmdline, err := os.ReadFile(fmt.Sprintf("/proc/%d/cmdline", pid))
	if err != nil || !bytes.Contains(cmdline, []byte(pluginDir)) {
		return false
	}
	for _, arg := range bytes.Split(cmdline, []byte{0}) {
		if bytes.Equal(arg, []byte("daemon")) {
			return true
		}
	}
	return false
}

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

func procZombie(stat []byte) bool {
	end := bytes.LastIndexByte(stat, ')')
	return end >= 0 && len(stat) > end+2 && stat[end+2] == 'Z'
}

// pidAlive reports whether a non-zombie process with the given pid exists.
func pidAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	err := syscall.Kill(pid, 0)
	if err != nil && err != syscall.EPERM {
		return false
	}
	stat, err := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
	return err != nil || !procZombie(stat)
}

// daemonSysProcAttr detaches the worker into its own session so it survives
// the invoking Stash job and Stash restarts.
func daemonSysProcAttr() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{Setsid: true}
}
