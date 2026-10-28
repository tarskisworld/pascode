package main

import (
	"archive/tar"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func testArchive(t *testing.T, arch string, count int) (string, string) {
	t.Helper()
	config := []byte(fmt.Sprintf(`{"architecture":%q,"os":"linux"}`, arch))
	sum := sha256.Sum256(config)
	id := hex.EncodeToString(sum[:])
	path := filepath.Join(t.TempDir(), "engine.tar.gz")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	g := gzip.NewWriter(f)
	w := tar.NewWriter(g)
	manifest := "["
	for i := 0; i < count; i++ {
		if i > 0 {
			manifest += ","
		}
		manifest += fmt.Sprintf(`{"Config":%q}`, id+".json")
	}
	manifest += "]"
	for name, data := range map[string][]byte{"manifest.json": []byte(manifest), id + ".json": config} {
		if err := w.WriteHeader(&tar.Header{Name: name, Mode: 0644, Size: int64(len(data))}); err != nil {
			t.Fatal(err)
		}
		if _, err := w.Write(data); err != nil {
			t.Fatal(err)
		}
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	if err := g.Close(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	return path, "sha256:" + id
}

func TestEngineArchiveBinding(t *testing.T) {
	path, image := testArchive(t, "amd64", 1)
	if err := checkEngineArchive(path, image, "amd64"); err != nil {
		t.Fatal(err)
	}
	if err := checkEngineArchive(path, "sha256:"+fmt.Sprintf("%064d", 0), "amd64"); err == nil {
		t.Fatal("accepted wrong image ID")
	}
	if err := checkEngineArchive(path, image, "arm64"); err == nil {
		t.Fatal("accepted wrong architecture")
	}
	multiple, image := testArchive(t, "amd64", 2)
	if err := checkEngineArchive(multiple, image, "amd64"); err == nil {
		t.Fatal("accepted multiple manifests")
	}
}
