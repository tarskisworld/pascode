//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"os/user"
	"syscall"
	"unsafe"
)

var kernel = syscall.NewLazyDLL("kernel32.dll")
var lockFile = kernel.NewProc("LockFileEx")
var unlockFile = kernel.NewProc("UnlockFileEx")
var moveFile = kernel.NewProc("MoveFileExW")

func lockWorkspace(path string) (func(), error) {
	f, e := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0600)
	if e != nil {
		return nil, e
	}
	over := new(syscall.Overlapped)
	r, _, e := lockFile.Call(f.Fd(), 3, 0, 1, 0, uintptr(unsafe.Pointer(over)))
	if r == 0 {
		f.Close()
		return nil, e
	}
	return func() { unlockFile.Call(f.Fd(), 0, 1, 0, uintptr(unsafe.Pointer(over))); f.Close() }, nil
}
func secureDirectory(path string) error {
	u, e := user.Current()
	if e != nil {
		return e
	}
	cmd := exec.Command("icacls", path, "/inheritance:r", "/grant:r", "*"+u.Uid+":(OI)(CI)F", "/grant:r", "*S-1-5-18:(OI)(CI)F")
	if e = cmd.Run(); e != nil {
		return fmt.Errorf("unable to restrict state-directory ACL: %w", e)
	}
	return nil
}
func replaceConfig(from, to string) error {
	a, e := syscall.UTF16PtrFromString(from)
	if e != nil {
		return e
	}
	b, e := syscall.UTF16PtrFromString(to)
	if e != nil {
		return e
	}
	r, _, e := moveFile.Call(uintptr(unsafe.Pointer(a)), uintptr(unsafe.Pointer(b)), 1|8)
	if r == 0 {
		return e
	}
	return nil
}
