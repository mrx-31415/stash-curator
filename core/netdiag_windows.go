//go:build windows

package main

import (
	"strconv"
	"syscall"
	"unsafe"
)

var (
	iphlpapi     = syscall.NewLazyDLL("iphlpapi.dll")
	getTCPTable  = iphlpapi.NewProc("GetTcpTable")
	getTCP6Table = iphlpapi.NewProc("GetTcp6Table")
	errNoBuffer  = uintptr(122)
)

// socketSummary counts TIME_WAIT TCP sockets, in total and on Stash's port.
// Windows has a small ephemeral port range, and a high count is what turns
// rapid connection churn by any program into "Only one usage of each socket
// address" failures. The IP Helper tables are used rather than netstat,
// whose state names are localized.
func socketSummary(port string) jVal {
	stashPort, _ := strconv.Atoi(port)
	total, onStash := int64(0), int64(0)
	ok := false
	for _, table := range []struct {
		proc   *syscall.LazyProc
		layout tcpLayout
	}{{getTCPTable, tcpRowLayout}, {getTCP6Table, tcp6RowLayout}} {
		rows, err := readTCPTable(table.proc)
		if err != nil {
			continue
		}
		ok = true
		t, s := countTimeWait(rows, table.layout, stashPort)
		total += t
		onStash += s
	}
	if !ok {
		return jvNull()
	}
	return jvObj(
		jvKey("time_wait", jvInt(total)),
		jvKey("time_wait_stash_port", jvInt(onStash)),
	)
}

func readTCPTable(proc *syscall.LazyProc) ([]byte, error) {
	if err := proc.Find(); err != nil {
		return nil, err
	}
	size := uint32(0)
	buffer := []byte(nil)
	for attempt := 0; attempt < 4; attempt++ {
		var pointer uintptr
		if len(buffer) > 0 {
			pointer = uintptr(unsafe.Pointer(&buffer[0]))
		}
		result, _, _ := proc.Call(pointer, uintptr(unsafe.Pointer(&size)), 0)
		if result == 0 {
			return buffer, nil
		}
		if result != errNoBuffer {
			return nil, syscall.Errno(result)
		}
		buffer = make([]byte, size+1024)
		size = uint32(len(buffer))
	}
	return nil, syscall.Errno(errNoBuffer)
}
