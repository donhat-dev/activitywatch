.PHONY: build test package clean

PYTHON ?= python
POETRY ?= $(PYTHON) -m poetry
PYINSTALLER ?= $(PYTHON) -m PyInstaller

build:
	$(POETRY) install

test:
	$(POETRY) run aw-watcher-screenshot-mini --help  # Ensures that it at least starts

package:
	$(PYINSTALLER) aw-watcher-screenshot-mini.spec --clean --noconfirm
ifeq ($(OS),Windows_NT)
	powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path 'config.toml.example') { Copy-Item 'config.toml.example' 'dist/aw-watcher-screenshot-mini/config.toml.example' -Force }; if (Test-Path 'visualization') { New-Item -ItemType Directory -Force 'dist/visualization' | Out-Null; Copy-Item 'visualization/*' 'dist/visualization' -Recurse -Force }"
else
	if [ -f "config.toml.example" ]; then \
		cp config.toml.example dist/aw-watcher-screenshot-mini/config.toml.example; \
	fi
	if [ -d "visualization" ]; then \
		mkdir -p dist/visualization; \
		cp -r visualization/* dist/visualization; \
	fi
endif

clean:
	rm -rf build dist
	rm -rf aw_watcher_screenshot_mini/__pycache__
