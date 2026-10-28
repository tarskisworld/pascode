//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
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
	// Set the complete DACL in one operation. icacls /grant:r would leave
	// unrelated explicit grants from an existing workspace in place.
	const script = `$path = $env:PASCODE_STATE_DIR
$userSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$systemSid = [System.Security.Principal.SecurityIdentifier]'S-1-5-18'
$full = [System.Security.AccessControl.FileSystemRights]::FullControl
$allow = [System.Security.AccessControl.AccessControlType]::Allow
$items = @(Get-Item -LiteralPath $path) + @(Get-ChildItem -LiteralPath $path -Force -Recurse)
foreach ($item in $items) {
  if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'State workspace contains a link; refusing to secure it' }
  $acl = Get-Acl -LiteralPath $item.FullName
  $acl.SetAccessRuleProtection($true, $false)
  foreach ($rule in @($acl.Access)) { $acl.RemoveAccessRuleSpecific($rule) }
  $inherit = if ($item.PSIsContainer) { [System.Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit' } else { [System.Security.AccessControl.InheritanceFlags]::None }
  $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new($userSid,$full,$inherit,[System.Security.AccessControl.PropagationFlags]::None,$allow))
  $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new($systemSid,$full,$inherit,[System.Security.AccessControl.PropagationFlags]::None,$allow))
  Set-Acl -LiteralPath $item.FullName -AclObject $acl
}`
	cmd := exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script)
	cmd.Env = append(os.Environ(), "PASCODE_STATE_DIR="+path)
	if output, e := cmd.CombinedOutput(); e != nil {
		return fmt.Errorf("unable to restrict state-directory ACL: %w: %s", e, output)
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
