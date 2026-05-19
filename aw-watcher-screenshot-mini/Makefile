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
	powershell -NoProfile -ExecutionPolicy Bypass -Command '$$target = "dist/aw-watcher-screenshot-mini"; if ((Test-Path $$target) -and -not (Test-Path $$target -PathType Container)) { Move-Item $$target ($$target + ".bin") -Force; New-Item -ItemType Directory -Force $$target | Out-Null; Move-Item ($$target + ".bin") (Join-Path $$target "aw-watcher-screenshot-mini") -Force } else { New-Item -ItemType Directory -Force $$target | Out-Null }; if (Test-Path "config.toml.example") { Copy-Item "config.toml.example" "dist/aw-watcher-screenshot-mini/config.toml.example" -Force }; if (Test-Path "visualization") { New-Item -ItemType Directory -Force "dist/visualization" | Out-Null; Copy-Item "visualization/*" "dist/visualization" -Recurse -Force }'
else
	if [ -f "dist/aw-watcher-screenshot-mini" ]; then \
		mv dist/aw-watcher-screenshot-mini dist/aw-watcher-screenshot-mini.bin; \
		mkdir -p dist/aw-watcher-screenshot-mini; \
		mv dist/aw-watcher-screenshot-mini.bin dist/aw-watcher-screenshot-mini/aw-watcher-screenshot-mini; \
	else \
		mkdir -p dist/aw-watcher-screenshot-mini; \
	fi
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
