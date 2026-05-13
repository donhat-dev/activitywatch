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
	powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path 'config.toml.example') { Copy-Item 'config.toml.example' 'dist/aw-odoo-sync/config.toml.example' -Force }"
else
	if [ -f "config.toml.example" ]; then \
		cp config.toml.example dist/aw-odoo-sync/config.toml.example; \
	fi
endif

clean:
	rm -rf build dist
	rm -rf aw_odoo_sync/__pycache__
