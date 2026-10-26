package main

import (
	"bytes"
	"context"
	"encoding/csv"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

const testImage = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

func TestMain(m *testing.M) {
	if os.Getenv("PASCODE_FAKE_DOCKER") == "1" && len(os.Args) > 1 &&
		(os.Args[1] == "info" || os.Args[1] == "run" || os.Args[1] == "rm" || os.Args[1] == "image" || os.Args[1] == "load") {
		args := os.Args[1:]
		b, _ := json.Marshal(args)
		if f := os.Getenv("PASCODE_TEST_LOG"); f != "" {
			os.WriteFile(f, b, 0600)
		}
		if len(args) > 0 && args[0] == "info" {
			os.Stdout.WriteString("linux\n")
		}
		if len(args) > 0 && args[0] == "run" && os.Getenv("PASCODE_TEST_CANCEL") == "1" {
			for i, s := range args {
				if s == "--cidfile" && i+1 < len(args) {
					os.WriteFile(args[i+1], []byte(strings.Repeat("a", 64)), 0600)
				}
			}
			time.Sleep(30 * time.Second)
		}
		os.Exit(0)
	}
	os.Exit(m.Run())
}
func TestParseAndMetadata(t *testing.T) {
	for _, args := range [][]string{{"version", "--json"}, {"--version"}, {"apply", "--version"}, {"help", "validate"}, {"validate", "--project=a path", "--json"}, {"map", "a path", "output", "bindings"}} {
		o, e := parse(args)
		if e != nil {
			t.Fatal(e)
		}
		if args[0] == "validate" && o.project != "a path" {
			t.Fatal(o)
		}
		if len(args) == 2 && args[0] == "apply" && !o.showVersion {
			t.Fatal("global version flag did not short-circuit apply")
		}
	}
	for _, args := range [][]string{{"--bad"}, {"wat"}, {"validate", "--project"}, {"--project", "a", "--project", "b", "validate"}} {
		if _, e := parse(args); e == nil {
			t.Fatal(args)
		}
	}
	var out bytes.Buffer
	a := app{ctx: context.Background(), out: &out, err: &out, docker: "unavailable-docker"}
	if e := a.execute(options{command: "version", json: true}); e != nil {
		t.Fatal(e)
	}
	var metadata map[string]string
	if e := json.Unmarshal(out.Bytes(), &metadata); e != nil || metadata["version"] != version {
		t.Fatal(out.String(), e)
	}
}
func TestMountCSV(t *testing.T) {
	source := filepath.Join(t.TempDir(), "space, and \"quote\"")
	s := mountArg(source, "/inputs", true)
	r, e := csv.NewReader(strings.NewReader(s)).Read()
	if e != nil || r[1] != "src="+source || r[3] != "readonly" {
		t.Fatal(s, r, e)
	}
}
func TestProjectDiscoveryAndExplicitPrecedence(t *testing.T) {
	root := t.TempDir()
	p := filepath.Join(root, "project")
	nested := filepath.Join(p, "nested")
	os.MkdirAll(nested, 0755)
	os.MkdirAll(filepath.Join(p, ".pascode", "jira-as-code"), 0755)
	old, _ := os.Getwd()
	os.Chdir(nested)
	t.Cleanup(func() { os.Chdir(old) })
	got, e := projectPath("")
	expected, _ := canonical(filepath.Join(p, ".pascode"))
	if e != nil || got != expected {
		t.Fatal(got, e)
	}
	explicit := filepath.Join(root, "explicit")
	os.MkdirAll(filepath.Join(explicit, "jira-as-code"), 0755)
	got, e = projectPath(explicit)
	expected, _ = canonical(explicit)
	if e != nil || got != expected {
		t.Fatal(got, e)
	}
}
func TestConfigurationNeverExecutesShell(t *testing.T) {
	home := t.TempDir()
	t.Setenv("PASCODE_HOME", home)
	payload := "PASCODE_IMAGE=" + testImage + "\r\necho unsafe > \"$PASCODE_HOME/marker\"\n"
	os.WriteFile(filepath.Join(home, "runtime.env"), []byte(payload), 0600)
	c, e := loadConfig(false)
	if e != nil || c.Image != testImage {
		t.Fatal(c, e)
	}
	if _, e = os.Stat(filepath.Join(home, "marker")); !os.IsNotExist(e) {
		t.Fatal("executed shell")
	}
	os.WriteFile(filepath.Join(home, "config.json"), []byte(`{"schema":99}`), 0600)
	if _, e = loadConfig(false); e == nil {
		t.Fatal("accepted unknown schema")
	}
}
func TestLockHelper(t *testing.T) {
	if p := os.Getenv("PASCODE_TEST_LOCK"); p != "" {
		unlock, e := lockWorkspace(p)
		if e == nil {
			unlock()
			os.Exit(17)
		}
		os.Exit(0)
	}
}
func TestCrossProcessLock(t *testing.T) {
	path := filepath.Join(t.TempDir(), "lock")
	unlock, e := lockWorkspace(path)
	if e != nil {
		t.Fatal(e)
	}
	cmd := exec.Command(os.Args[0], "-test.run=^TestLockHelper$")
	cmd.Env = append(os.Environ(), "PASCODE_TEST_LOCK="+path)
	if b, e := cmd.CombinedOutput(); e != nil {
		t.Fatalf("lock not exclusive: %s %v", b, e)
	}
	unlock()
	again, e := lockWorkspace(path)
	if e != nil {
		t.Fatal(e)
	}
	again()
}
func TestOfflineDockerContract(t *testing.T) {
	root := t.TempDir()
	project := filepath.Join(root, "project with spaces")
	os.MkdirAll(filepath.Join(project, "jira-as-code"), 0755)
	log := filepath.Join(root, "args.json")
	t.Setenv("PASCODE_FAKE_DOCKER", "1")
	t.Setenv("PASCODE_TEST_LOG", log)
	var out bytes.Buffer
	a := app{ctx: context.Background(), out: &out, err: &out, docker: os.Args[0], config: config{Schema: 1, Image: testImage, Platform: "linux/amd64"}}
	if e := a.executeEngine(options{command: "validate", project: project}); e != nil {
		t.Fatal(e)
	}
	b, _ := os.ReadFile(log)
	var args []string
	json.Unmarshal(b, &args)
	joined := strings.Join(args, " ")
	for _, want := range []string{"--network none", "--pull never", "--read-only", "--cap-drop ALL", "no-new-privileges", "--cidfile", "/runtime/runner.py validate --root /inputs"} {
		if !strings.Contains(joined, want) {
			t.Fatal(want, joined)
		}
	}
	if strings.Contains(joined, "docker.sock") || strings.Contains(joined, "JIRA_API_TOKEN") {
		t.Fatal("offline worker received credentials or socket")
	}
}
func TestCancelledOwnedContainerRemoved(t *testing.T) {
	t.Setenv("PASCODE_FAKE_DOCKER", "1")
	t.Setenv("PASCODE_TEST_CANCEL", "1")
	log := filepath.Join(t.TempDir(), "args")
	t.Setenv("PASCODE_TEST_LOG", log)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	var out bytes.Buffer
	a := app{ctx: ctx, out: &out, err: &out, docker: os.Args[0]}
	done := make(chan error, 1)
	go func() { done <- a.run(a.docker, []string{"run", "--rm", testImage}, nil) }()
	deadline := time.Now().Add(15 * time.Second)
	started := false
	for time.Now().Before(deadline) {
		b, _ := os.ReadFile(log)
		var args []string
		_ = json.Unmarshal(b, &args)
		for i, s := range args {
			if s == "--cidfile" && i+1 < len(args) {
				if _, e := os.Stat(args[i+1]); e == nil {
					started = true
				}
			}
		}
		if started {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	cancel()
	if !started {
		<-done
		t.Fatal("test child did not create its owned container marker")
	}
	if e := <-done; e == nil {
		t.Fatal("cancellation succeeded")
	}
	b, _ := os.ReadFile(log)
	if !strings.Contains(string(b), `"rm","--force"`) {
		t.Fatal("owned container not removed", string(b))
	}
}
func TestEnvironmentRedaction(t *testing.T) {
	env := cleanEnvironment([]string{"TF_LOG=DEBUG", "TF_CLI_ARGS_apply=-lock=false", "TF_WORKSPACE=other", "TF_VAR_unrelated=secret", "JIRA_API_TOKEN=old", "PATH=keep"}, map[string]string{"JIRA_API_TOKEN": "selected"})
	s := strings.Join(env, "\n")
	if strings.Contains(s, "DEBUG") || strings.Contains(s, "old") || strings.Contains(s, "other") || strings.Contains(s, "secret") || !strings.Contains(s, "selected") || !strings.Contains(s, "PATH=keep") {
		t.Fatal("incorrect environment filtering")
	}
}
func TestPrivateStateRejectsGit(t *testing.T) {
	root := t.TempDir()
	os.Mkdir(filepath.Join(root, ".git"), 0755)
	state := filepath.Join(root, "state")
	os.Mkdir(state, 0700)
	binding := filepath.Join(root, "bindings.json")
	os.WriteFile(binding, []byte("{}"), 0600)
	a := app{ctx: context.Background()}
	e := a.deployment(options{command: "plan", state: state, bindings: binding}, root)
	var u usageError
	if !errors.As(e, &u) {
		t.Fatal(e)
	}
}
func TestExistingDeploymentStateIsRestricted(t *testing.T) {
	root := t.TempDir()
	state := filepath.Join(root, "state")
	if e := os.Mkdir(state, 0755); e != nil {
		t.Fatal(e)
	}
	if e := os.WriteFile(filepath.Join(state, ".pascodectl-workspace"), nil, 0600); e != nil {
		t.Fatal(e)
	}
	bindings := filepath.Join(root, "bindings.json")
	if e := os.WriteFile(bindings, []byte("{}"), 0600); e != nil {
		t.Fatal(e)
	}
	a := app{ctx: context.Background()}
	_ = a.deployment(options{command: "plan", state: state, bindings: bindings}, root)
	if runtime.GOOS != "windows" {
		if info, e := os.Stat(state); e != nil || info.Mode().Perm() != 0700 {
			t.Fatalf("state directory remains accessible: %v %v", info, e)
		}
	}
}
func TestUnreadablePlatformMarkerFailsClosed(t *testing.T) {
	root := t.TempDir()
	state := filepath.Join(root, "state")
	if e := os.Mkdir(state, 0700); e != nil {
		t.Fatal(e)
	}
	if e := os.WriteFile(filepath.Join(state, ".pascodectl-workspace"), nil, 0600); e != nil {
		t.Fatal(e)
	}
	if e := os.Mkdir(filepath.Join(state, ".pascodectl-platform"), 0700); e != nil {
		t.Fatal(e)
	}
	bindings := filepath.Join(root, "bindings.json")
	if e := os.WriteFile(bindings, []byte("{}"), 0600); e != nil {
		t.Fatal(e)
	}
	a := app{ctx: context.Background()}
	if e := a.deployment(options{command: "plan", state: state, bindings: bindings}, root); e == nil || !strings.Contains(e.Error(), "platform marker") {
		t.Fatalf("unreadable marker was accepted: %v", e)
	}
}
