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
	if [ -f "config.toml.example" ]; then \
		cp config.toml.example dist/aw-odoo-sync/config.toml.example; \
	fi

clean:
	rm -rf build dist
	rm -rf aw_odoo_sync/__pycache__
