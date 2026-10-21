package main

import (
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
)

var immutableImage = regexp.MustCompile(`^(sha256:[a-f0-9]{64}|[a-zA-Z0-9][a-zA-Z0-9./:_-]*@sha256:[a-f0-9]{64})$`)

func validateConfig(c config) error {
	if !immutableImage.MatchString(c.Image) || (c.Platform != "linux/amd64" && c.Platform != "linux/arm64") {
		return fmt.Errorf("engine must have an immutable Linux image and supported architecture")
	}
	return nil
}
func canonical(p string) (string, error) {
	p, e := filepath.Abs(p)
	if e != nil {
		return "", e
	}
	return filepath.EvalSymlinks(p)
}
func isDir(p string) bool { s, e := os.Stat(p); return e == nil && s.IsDir() }
func projectPath(p string) (string, error) {
	if p == "" {
		var e error
		p, e = os.Getwd()
		if e != nil {
			return "", e
		}
		for {
			if isDir(filepath.Join(p, ".pascode", "jira-as-code")) {
				p = filepath.Join(p, ".pascode")
				break
			}
			if isDir(filepath.Join(p, "jira-as-code")) {
				break
			}
			parent := filepath.Dir(p)
			if parent == p {
				return "", usage("no project found; use --project PATH")
			}
			p = parent
		}
	}
	if !isDir(filepath.Join(p, "jira-as-code")) && isDir(filepath.Join(p, ".pascode", "jira-as-code")) {
		p = filepath.Join(p, ".pascode")
	}
	if !isDir(filepath.Join(p, "jira-as-code")) {
		return "", usage("project must contain jira-as-code")
	}
	return canonical(p)
}
func mountArg(source, target string, readonly bool) string {
	var b strings.Builder
	w := csv.NewWriter(&b)
	fields := []string{"type=bind", "src=" + source, "dst=" + target}
	if readonly {
		fields = append(fields, "readonly")
	}
	_ = w.Write(fields)
	w.Flush()
	return strings.TrimSuffix(b.String(), "\n")
}
func (a app) base(offline bool) []string {
	args := []string{"run", "--rm", "--pull", "never", "--platform", a.config.Platform, "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", containerUser()}
	if offline {
		args = append(args, "--network", "none")
	}
	return args
}
func (a app) python(args, mounts []string, offline bool, env []string) error {
	d := a.base(offline)
	d = append(d, "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONPATH=/runtime:/app")
	d = append(d, mounts...)
	d = append(d, "--entrypoint", "python", a.config.Image)
	d = append(d, args...)
	return a.run(a.docker, d, env)
}
func (a app) setup() error {
	server, e := a.capture(a.docker, "info", "--format", "{{.OSType}}")
	if e != nil || server != "linux" {
		return fmt.Errorf("start Docker Desktop or another accessible Linux-container daemon before setup")
	}
	if _, e = a.capture(a.docker, "image", "inspect", a.config.Image); e != nil {
		if a.config.Archive == "" || len(a.config.SHA256) != 64 {
			return fmt.Errorf("engine is absent and no verified release archive is configured")
		}
		f, e := os.Open(a.config.Archive)
		if e != nil {
			return e
		}
		h := sha256.New()
		_, e = io.Copy(h, f)
		f.Close()
		if e != nil {
			return e
		}
		if hex.EncodeToString(h.Sum(nil)) != a.config.SHA256 {
			return fmt.Errorf("engine archive checksum mismatch")
		}
		loaded, loadErr := a.capture(a.docker, "load", "--input", a.config.Archive)
		if loadErr != nil {
			return fmt.Errorf("failed to load verified engine archive: %w", loadErr)
		}
		if _, e = a.capture(a.docker, "image", "inspect", a.config.Image); e != nil {
			// Some Docker versions rewrite image metadata while importing an
			// archive, changing its local ID. The checked archive still pins
			// the bytes; store the actual local ID for later immutable runs.
			match := regexp.MustCompile(`(?m)^Loaded image ID: (sha256:[a-f0-9]{64})$`).FindStringSubmatch(loaded)
			if len(match) != 2 {
				return fmt.Errorf("Docker loaded the engine but did not report an image ID")
			}
			a.config.Image = match[1]
		}
		actual, e := a.capture(a.docker, "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", a.config.Image)
		if e != nil || actual != a.config.Platform {
			return fmt.Errorf("loaded image platform does not match the release")
		}
	}
	home, e := homeDir()
	if e != nil {
		return e
	}
	if e = os.MkdirAll(home, 0700); e != nil {
		return e
	}
	b, e := json.MarshalIndent(a.config, "", "  ")
	if e != nil {
		return e
	}
	f, e := os.CreateTemp(home, ".config-*")
	if e != nil {
		return e
	}
	name := f.Name()
	defer os.Remove(name)
	if e = f.Chmod(0600); e == nil {
		_, e = f.Write(append(b, '\n'))
	}
	if closeErr := f.Close(); e == nil {
		e = closeErr
	}
	if e != nil {
		return e
	}
	if e = replaceConfig(name, filepath.Join(home, "config.json")); e != nil {
		return e
	}
	fmt.Fprintln(a.out, "Configured the pinned engine for this user. Run pascodectl doctor.")
	return nil
}
func (a app) executeEngine(o options) error {
	if o.project == "" && len(o.args) > 0 {
		o.project = o.args[0]
		o.args = o.args[1:]
	}
	project, e := projectPath(o.project)
	if e != nil {
		return e
	}
	take := func(dst *string) {
		if *dst == "" && len(o.args) > 0 {
			*dst = o.args[0]
			o.args = o.args[1:]
		}
	}
	switch o.command {
	case "validate":
		if len(o.args) > 0 || o.output+o.bindings+o.state != "" {
			return usage("validate accepts only a project")
		}
	case "map", "bindings":
		if o.state != "" {
			return usage("offline commands do not accept state")
		}
		take(&o.output)
		if o.command == "map" {
			take(&o.bindings)
		}
		if len(o.args) > 0 || (o.bindings != "" && o.output == "") || (o.command == "bindings" && (o.output == "" || o.bindings != "")) {
			return usage("invalid output or bindings arguments")
		}
	case "plan", "apply", "verify":
		if o.output != "" {
			return usage("deployment requires state rather than output")
		}
		take(&o.state)
		take(&o.bindings)
		if len(o.args) > 0 || o.state == "" || o.bindings == "" {
			return usage("deployment requires a private state directory and bindings file")
		}
		return a.deployment(o, project)
	}
	mounts := []string{"--mount", mountArg(project, "/inputs", true)}
	args := []string{"/runtime/runner.py", o.command, "--root", "/inputs"}
	if o.command == "bindings" {
		args = []string{"/runtime/bindings.py", "--root", "/inputs", "--output", "/output/bindings.json"}
	}
	if o.output != "" {
		if e = os.MkdirAll(o.output, 0755); e != nil {
			return e
		}
		output, e := canonical(o.output)
		if e != nil {
			return e
		}
		mounts = append(mounts, "--mount", mountArg(output, "/output", false))
		if o.command == "map" {
			args = append(args, "--output", "/output")
		}
	}
	if o.bindings != "" {
		bindings, e := canonical(o.bindings)
		if e != nil {
			return e
		}
		s, e := os.Stat(bindings)
		if e != nil || !s.Mode().IsRegular() {
			return usage("bindings must be a regular file")
		}
		mounts = append(mounts, "--mount", mountArg(bindings, "/bindings/input.json", true))
		args = append(args, "--bindings", "/bindings/input.json")
	}
	return a.python(args, mounts, true, nil)
}
func insideGit(p string) bool {
	for {
		if _, e := os.Lstat(filepath.Join(p, ".git")); e == nil {
			return true
		}
		parent := filepath.Dir(p)
		if parent == p {
			return false
		}
		p = parent
	}
}
func (a app) deployment(o options, project string) error {
	bindings, e := canonical(o.bindings)
	if e != nil {
		return e
	}
	s, e := os.Stat(bindings)
	if e != nil || !s.Mode().IsRegular() {
		return usage("bindings must be a regular file")
	}
	state, e := filepath.Abs(o.state)
	if e != nil {
		return e
	}
	if e = os.MkdirAll(state, 0700); e != nil {
		return e
	}
	state, e = canonical(state)
	if e != nil {
		return e
	}
	if insideGit(state) {
		return usage("deployment state must be outside Git repositories")
	}
	marker := filepath.Join(state, ".pascodectl-workspace")
	if _, e = os.Stat(marker); os.IsNotExist(e) {
		entries, e := os.ReadDir(state)
		if e != nil {
			return e
		}
		if len(entries) != 0 {
			return usage("use an empty dedicated deployment directory")
		}
		if e = secureDirectory(state); e != nil {
			return e
		}
		if e = os.WriteFile(marker, []byte{}, 0600); e != nil {
			return e
		}
	}
	unlock, e := lockWorkspace(filepath.Join(state, ".pipeline.lock"))
	if e != nil {
		return fmt.Errorf("another pipeline may be using this state: %w", e)
	}
	defer unlock()
	platformMarker := filepath.Join(state, ".pascodectl-platform")
	if b, e := os.ReadFile(platformMarker); e == nil && strings.TrimSpace(string(b)) != runtime.GOOS {
		return usage("do not share deployment state between host operating systems")
	}
	if _, e = os.Stat(platformMarker); os.IsNotExist(e) {
		if runtime.GOOS != "linux" {
			entries, _ := os.ReadDir(state)
			if len(entries) > 2 {
				return usage("existing legacy state requires a separately reviewed platform migration")
			}
		}
		if e = os.WriteFile(platformMarker, []byte(runtime.GOOS+"\n"), 0600); e != nil {
			return e
		}
	}
	mode := os.Getenv("PASCODE_AUTH_MODE")
	if mode != "api_token_bootstrap" && mode != "api_service_account_override" {
		return usage("select PASCODE_AUTH_MODE explicitly")
	}
	email, base, token := os.Getenv("JIRA_API_EMAIL"), os.Getenv("JIRA_API_BASE_URL"), os.Getenv("JIRA_API_TOKEN")
	if email == "" || base == "" {
		return usage("JIRA_API_EMAIL and JIRA_API_BASE_URL are required")
	}
	if ref := os.Getenv("PASCODE_JIRA_TOKEN_SECRET_REF"); ref != "" {
		token, e = a.capture("gopass", "show", "-o", ref)
		if e != nil {
			return fmt.Errorf("unable to read the selected credential reference")
		}
		token = strings.NewReplacer("\r", "", "\n", "").Replace(token)
	}
	if token == "" {
		return usage("provide a runtime token or selected secret reference")
	}
	extra := map[string]string{"PASCODE_AUTH_MODE": mode, "JIRA_API_EMAIL": email, "JIRA_API_BASE_URL": base, "JIRA_API_TOKEN": token, "TF_IN_AUTOMATION": "1", "TF_INPUT": "0", "TF_VAR_jira_api_base_url": base, "TF_VAR_jira_admin_email": email, "TF_VAR_jira_admin_token": token}
	env := cleanEnvironment(os.Environ(), extra)
	mounts := []string{"--mount", mountArg(project, "/inputs", true), "--mount", mountArg(bindings, "/bindings/input.json", true), "--mount", mountArg(state, "/work", false)}
	for _, key := range []string{"PASCODE_AUTH_MODE", "JIRA_API_EMAIL", "JIRA_API_TOKEN", "JIRA_API_BASE_URL"} {
		mounts = append(mounts, "--env", key)
	}
	worker := func(command string) error {
		return a.python([]string{"/runtime/deployment.py", command, "--root", "/inputs", "--workdir", "/work", "--bindings", "/bindings/input.json"}, mounts, false, env)
	}
	if o.command == "verify" {
		return worker("verify")
	}
	prepare := "prepare"
	if o.command == "apply" {
		prepare = "prepare-apply"
	}
	if e = worker(prepare); e != nil {
		return e
	}
	terraform := func(args ...string) error {
		if binary := os.Getenv("PASCODE_TERRAFORM_BINARY"); binary != "" {
			return a.run(binary, append([]string{"-chdir=" + filepath.Join(state, "terraform")}, args...), env)
		}
		d := a.base(false)
		d = append(d, "--tmpfs", "/tmp:rw,nosuid,nodev", "--env", "HOME=/tmp", "--mount", mountArg(filepath.Join(state, "terraform"), "/work", false), "--workdir", "/work")
		for _, key := range []string{"TF_IN_AUTOMATION", "TF_INPUT", "TF_VAR_jira_api_base_url", "TF_VAR_jira_admin_email", "TF_VAR_jira_admin_token"} {
			d = append(d, "--env", key)
		}
		d = append(d, "--entrypoint", "terraform", a.config.Image)
		return a.run(a.docker, append(d, args...), env)
	}
	if e = terraform("init", "-input=false"); e != nil {
		return e
	}
	if o.command == "plan" {
		return terraform("plan", "-input=false")
	}
	if e = terraform("apply", "-input=false", "-auto-approve"); e != nil {
		return e
	}
	return worker("rest")
}
func cleanEnvironment(env []string, extra map[string]string) []string {
	result := []string{}
	for _, entry := range env {
		key := strings.SplitN(entry, "=", 2)[0]
		if _, ok := extra[key]; ok {
			continue
		}
		if key == "JIRA_API_KEY" || key == "JIRA_DEFAULT_PROJECT_LEAD_ACCOUNT_ID" || strings.HasPrefix(key, "TF_LOG") || strings.HasPrefix(key, "TF_CLI_ARGS") || key == "TF_DATA_DIR" || key == "TF_WORKSPACE" {
			continue
		}
		result = append(result, entry)
	}
	for k, v := range extra {
		result = append(result, k+"="+v)
	}
	return result
}
func containerUser() string {
	if runtime.GOOS == "windows" {
		return "10001:10001"
	}
	return strconv.Itoa(os.Getuid()) + ":" + strconv.Itoa(os.Getgid())
}
