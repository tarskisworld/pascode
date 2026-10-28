// Build verified, platform-specific native release archives with no third-party
// dependencies. Run from the native module; container tooling is provided locally.
package main

import (
	"archive/tar"
	"archive/zip"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

func main() {
	if e := build(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
func hash(path string) (string, error) {
	f, e := os.Open(path)
	if e != nil {
		return "", e
	}
	defer f.Close()
	h := sha256.New()
	_, e = io.Copy(h, f)
	return hex.EncodeToString(h.Sum(nil)), e
}
func copyFile(source, target string) error {
	sourceAbs, e := filepath.Abs(source)
	if e != nil {
		return e
	}
	targetAbs, e := filepath.Abs(target)
	if e != nil {
		return e
	}
	if sourceAbs == targetAbs {
		return fmt.Errorf("engine source and destination must differ")
	}
	f, e := os.Open(source)
	if e != nil {
		return e
	}
	defer f.Close()
	o, e := os.Create(target)
	if e != nil {
		return e
	}
	_, e = io.Copy(o, f)
	closeErr := o.Close()
	if e != nil {
		return e
	}
	return closeErr
}
func build() error {
	image := flag.String("image", "", "immutable engine image")
	arch := flag.String("arch", "amd64", "engine and launcher architecture")
	engine := flag.String("engine", "", "saved gzip engine archive")
	output := flag.String("output", "../build/native-assets", "output directory")
	flag.Parse()
	v, e := os.ReadFile("../NATIVE_VERSION")
	if e != nil {
		return e
	}
	version := strings.TrimSpace(string(v))
	if !regexp.MustCompile(`^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$`).MatchString(version) {
		return fmt.Errorf("invalid native version")
	}
	if !regexp.MustCompile(`^sha256:[a-f0-9]{64}$`).MatchString(*image) || (*arch != "amd64" && *arch != "arm64") {
		return fmt.Errorf("invalid immutable image or architecture")
	}
	if e = os.MkdirAll(*output, 0755); e != nil {
		return e
	}
	engineName := "engine_linux_" + *arch + ".tar.gz"
	engineTarget := filepath.Join(*output, engineName)
	if e = copyFile(*engine, engineTarget); e != nil {
		return e
	}
	engineHash, e := hash(engineTarget)
	if e != nil {
		return e
	}
	cfg := map[string]any{"schema": 1, "image": *image, "platform": "linux/" + *arch, "archive": engineName, "sha256": engineHash}
	configBytes, _ := json.MarshalIndent(cfg, "", "  ")
	readme := []byte("P as code native " + version + "\nRequires an accessible Linux-container runtime. Run version, setup and doctor.\nNo host Bash/Python/Terraform/Go required.\n")
	tmp, e := os.MkdirTemp("", "pascode-package-")
	if e != nil {
		return e
	}
	defer os.RemoveAll(tmp)
	files := []string{engineName}
	for _, system := range []string{"linux", "darwin", "windows"} {
		binary := "pascodectl"
		if system == "windows" {
			binary += ".exe"
		}
		target := filepath.Join(tmp, binary)
		cmd := exec.Command("go", "build", "-trimpath", "-ldflags", "-s -w -X main.version="+version, "-o", target, ".")
		cmd.Env = append(os.Environ(), "GOOS="+system, "GOARCH="+*arch, "CGO_ENABLED=0")
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		if e = cmd.Run(); e != nil {
			return e
		}
		data, e := os.ReadFile(target)
		if e != nil {
			return e
		}
		members := []member{{binary, data, 0755}, {"engine.json", append(configBytes, '\n'), 0644}, {"README.md", readme, 0644}}
		name := "pascodectl_" + version + "_" + system + "_" + *arch
		if system == "windows" {
			name += ".zip"
			e = writeZip(filepath.Join(*output, name), members)
		} else {
			name += ".tar.gz"
			e = writeTar(filepath.Join(*output, name), members)
		}
		if e != nil {
			return e
		}
		files = append(files, name)
	}
	manifest, e := os.Create(filepath.Join(*output, "SHA256SUMS-"+*arch))
	if e != nil {
		return e
	}
	defer manifest.Close()
	for _, name := range files {
		sum, e := hash(filepath.Join(*output, name))
		if e != nil {
			return e
		}
		if _, e = fmt.Fprintf(manifest, "%s  %s\n", sum, name); e != nil {
			return e
		}
	}
	return manifest.Sync()
}

type member struct {
	name string
	data []byte
	mode int64
}

func writeTar(path string, members []member) error {
	f, e := os.Create(path)
	if e != nil {
		return e
	}
	g := gzip.NewWriter(f)
	t := tar.NewWriter(g)
	for _, m := range members {
		if e = t.WriteHeader(&tar.Header{Name: m.name, Mode: m.mode, Size: int64(len(m.data)), ModTime: time.Unix(0, 0)}); e != nil {
			return e
		}
		if _, e = t.Write(m.data); e != nil {
			return e
		}
	}
	if e = t.Close(); e != nil {
		return e
	}
	if e = g.Close(); e != nil {
		return e
	}
	return f.Close()
}
func writeZip(path string, members []member) error {
	f, e := os.Create(path)
	if e != nil {
		return e
	}
	z := zip.NewWriter(f)
	for _, m := range members {
		header := &zip.FileHeader{Name: m.name, Method: zip.Deflate}
		header.SetMode(os.FileMode(m.mode))
		header.SetModTime(time.Date(1980, 1, 1, 0, 0, 0, 0, time.UTC))
		w, e := z.CreateHeader(header)
		if e != nil {
			return e
		}
		if _, e = w.Write(m.data); e != nil {
			return e
		}
	}
	if e = z.Close(); e != nil {
		return e
	}
	return f.Close()
}
