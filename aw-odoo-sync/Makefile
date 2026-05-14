.PHONY: build test package clean typecheck

PYTHON ?= python
POETRY ?= $(PYTHON) -m poetry
PYINSTALLER ?= $(PYTHON) -m PyInstaller

build:
	$(POETRY) install

test:
	$(POETRY) run aw-odoo-sync --help
	$(MAKE) typecheck

typecheck:
	$(POETRY) run mypy aw_odoo_sync --ignore-missing-imports

package:
	$(PYINSTALLER) aw-odoo-sync.spec --clean --noconfirm
ifeq ($(OS),Windows_NT)
	powershell -NoProfile -ExecutionPolicy Bypass -Command "$$target = 'dist/aw-odoo-sync'; if ((Test-Path $$target) -and -not (Test-Path $$target -PathType Container)) { Move-Item $$target ($$target + '.bin') -Force; New-Item -ItemType Directory -Force $$target | Out-Null; Move-Item ($$target + '.bin') (Join-Path $$target 'aw-odoo-sync') -Force } else { New-Item -ItemType Directory -Force $$target | Out-Null }; if (Test-Path 'config.toml.example') { Copy-Item 'config.toml.example' 'dist/aw-odoo-sync/config.toml.example' -Force }"
else
	if [ -f "dist/aw-odoo-sync" ]; then \
		mv dist/aw-odoo-sync dist/aw-odoo-sync.bin; \
		mkdir -p dist/aw-odoo-sync; \
		mv dist/aw-odoo-sync.bin dist/aw-odoo-sync/aw-odoo-sync; \
	else \
		mkdir -p dist/aw-odoo-sync; \
	fi
	if [ -f "config.toml.example" ]; then \
		cp config.toml.example dist/aw-odoo-sync/config.toml.example; \
	fi
endif

clean:
	rm -rf build dist
	rm -rf aw_odoo_sync/__pycache__
