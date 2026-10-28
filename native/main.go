package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"syscall"
	"time"
)

var version = "0.2.0-dev"

type options struct {
	command, project, output, bindings, state string
	json, help, showVersion                   bool
	args                                      []string
}
type app struct {
	ctx      context.Context
	out, err io.Writer
	config   config
	docker   string
}
type config struct {
	Schema   int    `json:"schema"`
	Image    string `json:"image"`
	Platform string `json:"platform"`
	Archive  string `json:"archive,omitempty"`
	SHA256   string `json:"sha256,omitempty"`
}
type usageError string

func (e usageError) Error() string { return string(e) }
func usage(s string) error         { return usageError(s) }
func parse(args []string) (o options, err error) {
	for i := 0; i < len(args); i++ {
		s := args[i]
		if s == "--" {
			o.args = append(o.args, args[i+1:]...)
			break
		}
		if strings.HasPrefix(s, "--") && strings.Contains(s, "=") {
			p := strings.SplitN(s, "=", 2)
			if p[0] == "--json" || p[0] == "--help" || p[0] == "--version" {
				return o, usage("flag does not take a value")
			}
			args = append(append(append([]string{}, args[:i]...), p...), args[i+1:]...)
			s = p[0]
		}
		switch s {
		case "--json":
			o.json = true
		case "--help", "-h":
			o.help = true
		case "--version", "-V":
			o.showVersion = true
		case "--project", "-C", "--output", "-o", "--bindings", "--state-dir":
			if i+1 == len(args) || args[i+1] == "" {
				return o, usage("option needs a value")
			}
			i++
			var dst *string
			switch s {
			case "--project", "-C":
				dst = &o.project
			case "--output", "-o":
				dst = &o.output
			case "--bindings":
				dst = &o.bindings
			case "--state-dir":
				dst = &o.state
			}
			if *dst != "" {
				return o, usage("option specified twice")
			}
			*dst = args[i]
		default:
			if strings.HasPrefix(s, "-") {
				return o, usage("unknown option")
			}
			o.args = append(o.args, s)
		}
	}
	if o.showVersion {
		o.command = "version"
		o.args = nil
		return o, nil
	}
	o.command = "help"
	if len(o.args) > 0 {
		o.command = o.args[0]
		o.args = o.args[1:]
	}
	if o.command == "help" {
		o.help = true
		if len(o.args) > 1 {
			return o, usage("help accepts one command")
		}
		if len(o.args) == 1 {
			o.command = o.args[0]
			o.args = nil
		}
	}
	switch o.command {
	case "help", "version", "doctor", "setup", "completion", "validate", "map", "bindings", "plan", "apply", "verify":
	default:
		return o, usage("unknown command")
	}
	return
}
func homeDir() (string, error) {
	if p := os.Getenv("PASCODE_HOME"); p != "" {
		return filepath.Abs(p)
	}
	if exe, e := os.Executable(); e == nil {
		locations := []string{filepath.Dir(exe)}
		if resolved, resolveErr := filepath.EvalSymlinks(exe); resolveErr == nil && resolved != exe {
			locations = append(locations, filepath.Dir(resolved))
		}
		for _, location := range locations {
			if b, readErr := os.ReadFile(filepath.Join(location, ".pascode-home")); readErr == nil {
				p := strings.TrimSpace(string(b))
				if !filepath.IsAbs(p) {
					return "", fmt.Errorf("invalid installed configuration path")
				}
				return filepath.Clean(p), nil
			} else if !os.IsNotExist(readErr) {
				return "", readErr
			}
		}
	}
	p, e := os.UserHomeDir()
	return filepath.Join(p, ".pascode"), e
}
func loadConfig(preferRelease bool) (config, error) {
	var c config
	home, e := homeDir()
	if e != nil {
		return c, e
	}
	paths := []string{filepath.Join(home, "config.json")}
	exe, e := os.Executable()
	if e == nil {
		if resolved, resolveErr := filepath.EvalSymlinks(exe); resolveErr == nil {
			exe = resolved
		}
		paths = append(paths, filepath.Join(filepath.Dir(exe), "engine.json"))
	}
	if preferRelease && len(paths) == 2 {
		paths[0], paths[1] = paths[1], paths[0]
	}
	for _, p := range paths {
		b, e := os.ReadFile(p)
		if os.IsNotExist(e) {
			continue
		}
		if e != nil {
			return c, e
		}
		if e = json.Unmarshal(b, &c); e != nil {
			return c, fmt.Errorf("invalid runtime configuration: %w", e)
		}
		if c.Schema != 1 {
			return c, fmt.Errorf("unsupported configuration schema")
		}
		if c.Archive != "" && !filepath.IsAbs(c.Archive) {
			c.Archive = filepath.Join(filepath.Dir(p), c.Archive)
		}
		return c, validateConfig(c)
	}
	// Import only the immutable image identifier from the old shell pin. Never
	// execute shell configuration or read target authentication from a project.
	if b, e := os.ReadFile(filepath.Join(home, "runtime.env")); e == nil {
		for _, line := range strings.Split(string(b), "\n") {
			if strings.HasPrefix(line, "PASCODE_IMAGE=") {
				c = config{Schema: 1, Image: strings.Trim(strings.TrimSpace(strings.TrimPrefix(line, "PASCODE_IMAGE=")), "\"'"), Platform: "linux/" + runtime.GOARCH}
				return c, validateConfig(c)
			}
		}
	}
	return c, fmt.Errorf("no engine configured; run pascodectl setup from an installed release")
}
func (a app) run(name string, args []string, env []string) error {
	cidPath := ""
	ownerLabel := ""
	if name == a.docker && len(args) > 0 && args[0] == "run" {
		dir, e := os.MkdirTemp("", "pascode-container-")
		if e != nil {
			return e
		}
		defer os.RemoveAll(dir)
		cidPath = filepath.Join(dir, "cid")
		ownerBytes := make([]byte, 16)
		if _, e = rand.Read(ownerBytes); e != nil {
			return e
		}
		ownerLabel = "pascode.owner=" + hex.EncodeToString(ownerBytes)
		args = append([]string{"run", "--cidfile", cidPath, "--label", ownerLabel}, args[1:]...)
	}
	cmd := exec.CommandContext(a.ctx, name, args...)
	cmd.Stdout = a.out
	cmd.Stderr = a.err
	cmd.Stdin = os.Stdin
	if env != nil {
		cmd.Env = env
	}
	e := cmd.Run()
	if a.ctx.Err() != nil && cidPath != "" {
		ownedID := ""
		if b, readErr := os.ReadFile(cidPath); readErr == nil {
			cid := strings.TrimSpace(string(b))
			if regexp.MustCompile(`^[a-f0-9]{64}$`).MatchString(cid) {
				ownedID = cid
			}
		}
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if ownedID == "" {
			for ctx.Err() == nil {
				query := exec.CommandContext(ctx, a.docker, "ps", "-aq", "--filter", "label="+ownerLabel)
				found, queryErr := query.Output()
				if queryErr != nil {
					return fmt.Errorf("cancelled; unable to inspect owned containers: %w", queryErr)
				}
				if ids := strings.Fields(string(found)); len(ids) > 0 {
					ownedID = ids[0]
					break
				}
				time.Sleep(100 * time.Millisecond)
			}
		}
		if ownedID != "" {
			if stopErr := exec.CommandContext(ctx, a.docker, "rm", "--force", ownedID).Run(); stopErr != nil {
				return fmt.Errorf("cancelled; unable to stop the owned container: %w", stopErr)
			}
		}
	}
	return e
}
func (a app) capture(name string, args ...string) (string, error) {
	cmd := exec.CommandContext(a.ctx, name, args...)
	cmd.Stderr = io.Discard
	b, e := cmd.Output()
	return strings.TrimSpace(string(b)), e
}
func (a app) execute(o options) error {
	if o.showVersion {
		if o.json {
			return json.NewEncoder(a.out).Encode(map[string]string{"name": "pascodectl", "version": version})
		}
		fmt.Fprintln(a.out, "pascodectl", version)
		return nil
	}
	if o.help {
		fmt.Fprint(a.out, helpText)
		return nil
	}
	if o.command == "version" {
		if len(o.args) > 0 || o.project+o.output+o.bindings+o.state != "" {
			return usage("version accepts no paths")
		}
		if o.json {
			return json.NewEncoder(a.out).Encode(map[string]string{"name": "pascodectl", "version": version})
		}
		fmt.Fprintln(a.out, "pascodectl", version)
		return nil
	}
	if o.command == "completion" {
		if len(o.args) != 1 || o.project+o.output+o.bindings+o.state != "" || o.json {
			return usage("use completion bash, zsh or powershell")
		}
		switch o.args[0] {
		case "bash":
			fmt.Fprintln(a.out, `complete -W 'help version doctor setup validate map bindings plan apply verify completion' pascodectl`)
		case "zsh":
			fmt.Fprintln(a.out, `#compdef pascodectl
_arguments '1:command:(help version doctor setup validate map bindings plan apply verify completion)' '*:path:_files'`)
		case "powershell":
			fmt.Fprintln(a.out, `Register-ArgumentCompleter -Native -CommandName pascodectl -ScriptBlock { param($wordToComplete) 'help','version','doctor','setup','validate','map','bindings','plan','apply','verify','completion' | Where-Object { $_ -like "$wordToComplete*" } }`)
		default:
			return usage("unsupported completion shell")
		}
		return nil
	}
	var e error
	a.config, e = loadConfig(o.command == "setup")
	if o.command == "doctor" {
		if len(o.args) > 0 || o.project+o.output+o.bindings+o.state != "" {
			return usage("doctor accepts no paths")
		}
		configured := e == nil
		_, look := exec.LookPath(a.docker)
		server, connected := a.capture(a.docker, "info", "--format", "{{.OSType}}")
		linux := connected == nil && server == "linux"
		image := false
		if configured && linux {
			_, err := a.capture(a.docker, "image", "inspect", a.config.Image)
			image = err == nil
		}
		ready := configured && look == nil && linux && image
		if o.json {
			json.NewEncoder(a.out).Encode(map[string]any{"ready": ready, "checks": map[string]bool{"configured": configured, "docker_cli": look == nil, "linux_daemon": linux, "pinned_local_image": image}})
		} else {
			fmt.Fprintf(a.out, "Ready: %t (configuration=%t, Docker CLI=%t, Linux daemon=%t, pinned image=%t)\n", ready, configured, look == nil, linux, image)
		}
		if !ready {
			return errors.New("install/start a Linux container runtime, then run setup")
		}
		return nil
	}
	if e != nil {
		return e
	}
	if o.command == "setup" {
		if len(o.args) > 0 || o.project+o.output+o.bindings+o.state != "" || o.json {
			return usage("setup accepts no paths or JSON option")
		}
		return a.setup()
	}
	if o.json && o.command != "validate" && o.command != "map" {
		return usage("JSON is supported for version, doctor, validate and map")
	}
	return a.executeEngine(o)
}

const helpText = `Usage: pascodectl [OPTIONS] COMMAND [PROJECT_ROOT] [OUTPUT_OR_STATE] [BINDINGS]

Commands: validate, map, bindings, plan, apply, verify, version, doctor, setup,
          completion bash|zsh|powershell, help
Options: --project/-C PATH, --output/-o PATH, --bindings FILE, --state-dir PATH,
         --json, --help/-h, --version/-V
Without a project path, discover .pascode/jira-as-code or jira-as-code in ancestors.
Validate/map/bindings are offline. Plan/apply/verify require explicit target auth,
private state and bindings. Setup only loads a verified local engine archive.
Docker must run Linux containers. No host Bash, Python, Terraform or Go is needed.
`

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	o, e := parse(os.Args[1:])
	a := app{ctx: ctx, out: os.Stdout, err: os.Stderr, docker: "docker"}
	if e == nil {
		e = a.execute(o)
	}
	if e != nil {
		if o.json {
			json.NewEncoder(os.Stderr).Encode(map[string]string{"error": e.Error()})
		} else {
			fmt.Fprintln(os.Stderr, "pascodectl:", e)
		}
		code := 1
		var u usageError
		if errors.As(e, &u) {
			code = 2
		}
		var x *exec.ExitError
		if errors.As(e, &x) {
			code = x.ExitCode()
			if code < 0 {
				code = 130
			}
		}
		if ctx.Err() != nil {
			code = 130
		}
		os.Exit(code)
	}
}
