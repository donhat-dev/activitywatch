# =====================================
# Makefile for the ActivityWatch bundle
# =====================================
#
# [GUIDE] How to install from source:
#  - https://activitywatch.readthedocs.io/en/latest/installing-from-source.html
#
# We recommend creating and activating a Python virtualenv before building.
# Instructions on how to do this can be found in the guide linked above.
.PHONY: build build-submodules install-tauri-python-modules install test clean clean_all package package-win package-bundle-win package-installer-win install-python-modules-win package-watchers-win package-installer-win-quick package-win-no-rust package-dmg-unsigned

PYTHON ?= python3

ifeq ($(OS),Windows_NT)
	HOST_OS := Windows
	SHELL := bash
else
	SHELL := /usr/bin/env bash
	HOST_OS := $(shell uname -s)
endif

POETRY ?= poetry
PYINSTALLER ?= $(PYTHON) -m PyInstaller
include tauri-watchers.mk
CUSTOM_WATCHERS ?= aw-watcher-screenshot-mini
CUSTOM_RUST_WATCHERS ?=

ifeq ($(TAURI_BUILD),true)
	SUBMODULES := aw-core aw-client aw-server aw-server-rust $(TAURI_WATCHERS) aw-tauri
	# Include awatcher on Linux (Wayland-compatible window watcher)
	ifeq ($(HOST_OS),Linux)
		SUBMODULES := $(SUBMODULES) awatcher
	endif
else
	SUBMODULES := aw-core aw-client aw-qt aw-server aw-server-rust
endif

# Exclude aw-server-rust if SKIP_SERVER_RUST is true
ifeq ($(SKIP_SERVER_RUST),true)
	SUBMODULES := $(filter-out aw-server-rust,$(SUBMODULES))
endif
# Include extras if AW_EXTRAS is true
ifeq ($(AW_EXTRAS),true)
	ifeq ($(TAURI_BUILD),true)
		SUBMODULES := $(SUBMODULES) aw-notify
	else
		SUBMODULES := $(SUBMODULES) aw-notify aw-watcher-input aw-odoo-sync
	endif
endif
# Exclude aw-notify (Rust) when SKIP_SERVER_RUST is true
ifeq ($(SKIP_SERVER_RUST),true)
	SUBMODULES := $(filter-out aw-notify,$(SUBMODULES))
endif

# A function that checks if a target exists in a Makefile
# Usage: $(call has_target,<dir>,<target>)
define has_target
$(if $(filter Windows_NT,$(OS)),$(shell cmd /c "make -q -C $1 $2 >NUL 2>&1 && echo $1 || (if not errorlevel 2 echo $1)"),$(shell make -q -C $1 $2 >/dev/null 2>&1; if [ $$? -eq 0 -o $$? -eq 1 ]; then echo $1; fi))
endef

# Submodules with test/package/lint/typecheck targets
TESTABLES := $(foreach dir,$(SUBMODULES),$(call has_target,$(dir),test))
PACKAGEABLES := $(foreach dir,$(SUBMODULES),$(call has_target,$(dir),package))
LINTABLES := $(foreach dir,$(SUBMODULES),$(call has_target,$(dir),lint))
TYPECHECKABLES := $(foreach dir,$(SUBMODULES),$(call has_target,$(dir),typecheck))

# When building with Tauri, aw-server-rust is built as aw-sync only (not full server),
# so exclude it from the standard package target
ifeq ($(TAURI_BUILD),true)
	PACKAGEABLES := $(filter-out aw-server-rust aw-server aw-tauri $(TAURI_WATCHERS), $(PACKAGEABLES))
endif

# Build mode: release vs debug
ifeq ($(RELEASE), false)
	targetdir := debug
else
	targetdir := release
endif

# The `build` target
# ------------------
#
# What it does:
#  - Installs all the Python modules
#  - Builds the web UI and bundles it with aw-server
build: aw-core/.git
#	needed due to https://github.com/pypa/setuptools/issues/1963
#	would ordinarily be specified in pyproject.toml, but is not respected due to https://github.com/pypa/setuptools/issues/1963
	$(PYTHON) -m pip install "setuptools>49.1.1"
ifeq ($(TAURI_BUILD),true)
	$(MAKE) install-tauri-python-modules PYTHON=$(PYTHON)
endif
	$(MAKE) build-submodules SKIP_WEBUI=$(SKIP_WEBUI)
#   The below is needed due to: https://github.com/ActivityWatch/activitywatch/issues/173
	$(MAKE) --directory=aw-client build PYTHON=$(PYTHON) POETRY=$(POETRY)
	$(MAKE) --directory=aw-core build PYTHON=$(PYTHON) POETRY=$(POETRY)
#	Needed to ensure that the server has the correct version set
	$(PYTHON) -c "import aw_server; print(aw_server.__version__)"

install-tauri-python-modules: aw-core/.git aw-client/.git
	$(PYTHON) -m pip install -e ./aw-core -e ./aw-client
	$(PYTHON) -c "import aw_client.odoo_config; print('aw_client.odoo_config import OK')"

ifeq ($(OS),Windows_NT)
build-submodules:
	powershell -NoProfile -Command "$$mods = '$(SUBMODULES)'.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries); $$tauriWatchers = @{}; '$(TAURI_WATCHERS)'.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object { $$tauriWatchers[$$_] = $$true }; foreach ($$m in $$mods) { Write-Host \"Building $$m\"; if ($$m -eq 'aw-server-rust' -and '$(TAURI_BUILD)' -eq 'true') { & '$(MAKE)' \"--directory=$$m\" aw-sync \"SKIP_WEBUI=$(SKIP_WEBUI)\" \"PYTHON=$(PYTHON)\" \"POETRY=$(POETRY)\" } elseif ($$m -eq 'aw-tauri' -and '$(TAURI_BUILD)' -eq 'true') { & '$(MAKE)' \"--directory=$$m\" build \"SKIP_WEBUI=$(SKIP_WEBUI)\" \"PYTHON=$(PYTHON)\" \"POETRY=$(POETRY)\" \"TAURI_WATCHERS=$(TAURI_WATCHERS)\" } else { & '$(MAKE)' \"--directory=$$m\" build \"SKIP_WEBUI=$(SKIP_WEBUI)\" \"PYTHON=$(PYTHON)\" \"POETRY=$(POETRY)\" }; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; if ('$(TAURI_BUILD)' -eq 'true' -and $$tauriWatchers.ContainsKey($$m)) { Write-Host \"Packaging $$m for Tauri\"; & '$(MAKE)' \"--directory=$$m\" package \"PYTHON=$(PYTHON)\" \"POETRY=$(POETRY)\"; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE } } }"
else
build-submodules:
	@for module in $(SUBMODULES); do \
		echo "Building $$module"; \
		if [ "$$module" = "aw-server-rust" ] && [ "$(TAURI_BUILD)" = "true" ]; then \
			$(MAKE) --directory=$$module aw-sync SKIP_WEBUI=$(SKIP_WEBUI) PYTHON=$(PYTHON) POETRY=$(POETRY) || { echo "Error in $$module aw-sync"; exit 2; }; \
		elif [ "$$module" = "aw-tauri" ] && [ "$(TAURI_BUILD)" = "true" ]; then \
			$(MAKE) --directory=$$module build SKIP_WEBUI=$(SKIP_WEBUI) PYTHON=$(PYTHON) POETRY=$(POETRY) TAURI_WATCHERS="$(TAURI_WATCHERS)" TAURI_BUNDLES="$(TAURI_BUNDLES)" || { echo "Error in $$module build"; exit 2; }; \
		else \
			$(MAKE) --directory=$$module build SKIP_WEBUI=$(SKIP_WEBUI) PYTHON=$(PYTHON) POETRY=$(POETRY) || { echo "Error in $$module build"; exit 2; }; \
		fi; \
		if [ "$(TAURI_BUILD)" = "true" ] && echo " $(TAURI_WATCHERS) " | grep -q " $$module "; then \
			echo "Packaging $$module for Tauri"; \
			$(MAKE) install-tauri-python-modules PYTHON=$(PYTHON) || { echo "Error refreshing local Python modules before packaging $$module"; exit 2; }; \
			$(MAKE) --directory=$$module package PYTHON=$(PYTHON) POETRY=$(POETRY) || { echo "Error in $$module package"; exit 2; }; \
		fi; \
	done
ifneq ($(TAURI_BUILD),true)
	@for module in $(CUSTOM_WATCHERS); do \
		echo "Building custom watcher $$module"; \
		$(MAKE) --directory=$$module build PYTHON=$(PYTHON) POETRY=$(POETRY) || { echo "Error in $$module build"; exit 2; }; \
	done
endif
endif


# Install
# -------
#
# Installs things like desktop/menu shortcuts.
# Might in the future configure autostart on the system.
ifneq ($(TAURI_BUILD),true)
install:
	make --directory=aw-qt install
# Installation is already happening in the `make build` step currently.
# We might want to change this.
# We should also add some option to install as user (pip3 install --user)
endif

# Update
# ------
#
# Pulls the latest version, updates all the submodules, then runs `make build`.
update:
	git pull
	git submodule update --init --recursive
	make build


lint:
	@for module in $(LINTABLES); do \
		echo "Linting $$module"; \
		make --directory=$$module lint || { echo "Error in $$module lint"; exit 2; }; \
	done

typecheck:
	@for module in $(TYPECHECKABLES); do \
		echo "Typechecking $$module"; \
		make --directory=$$module typecheck || { echo "Error in $$module typecheck"; exit 2; }; \
	done

# Uninstall
# ---------
#
# Uninstalls all the Python modules.
uninstall:
	modules=$$(pip3 list --format=legacy | grep 'aw-' | grep -o '^aw-[^ ]*'); \
	for module in $$modules; do \
		echo "Uninstalling $$module"; \
		pip3 uninstall -y $$module; \
	done

test:
	@for module in $(TESTABLES); do \
		echo "Running tests for $$module"; \
		$(MAKE) -C $$module test POETRY=$(POETRY) || { echo "Error in $$module tests"; exit 2; }; \
	done

test-integration:
	# TODO: Move "integration tests" to aw-client
	# FIXME: For whatever reason the script stalls on Appveyor
	#        Example: https://ci.appveyor.com/project/ErikBjare/activitywatch/build/1.0.167/job/k1ulexsc5ar5uv4v
	# aw-server-python
	@echo "== Integration testing aw-server =="
	@pytest ./scripts/tests/integration_tests.py ./aw-server/tests/ -v

%/.git:
	git submodule update --init --recursive

ifeq ($(TAURI_BUILD),true)
	ICON := "aw-tauri/src-tauri/icons/icon.png"
else
	ICON := "aw-qt/media/logo/logo.png"
endif

ISCC ?= iscc
ISCC_FALLBACK ?= C:\Program Files (x86)\Inno Setup 6\ISCC.exe

aw-qt/media/logo/logo.icns:
	mkdir -p build/MyIcon.iconset
	sips -z 16 16     $(ICON) --out build/MyIcon.iconset/icon_16x16.png
	sips -z 32 32     $(ICON) --out build/MyIcon.iconset/icon_16x16@2x.png
	sips -z 32 32     $(ICON) --out build/MyIcon.iconset/icon_32x32.png
	sips -z 64 64     $(ICON) --out build/MyIcon.iconset/icon_32x32@2x.png
	sips -z 128 128   $(ICON) --out build/MyIcon.iconset/icon_128x128.png
	sips -z 256 256   $(ICON) --out build/MyIcon.iconset/icon_128x128@2x.png
	sips -z 256 256   $(ICON) --out build/MyIcon.iconset/icon_256x256.png
	sips -z 512 512   $(ICON) --out build/MyIcon.iconset/icon_256x256@2x.png
	sips -z 512 512   $(ICON) --out build/MyIcon.iconset/icon_512x512.png
	cp				  $(ICON)       build/MyIcon.iconset/icon_512x512@2x.png
	iconutil -c icns build/MyIcon.iconset
	rm -R build/MyIcon.iconset
	mv build/MyIcon.icns aw-qt/media/logo/logo.icns

ifeq ($(TAURI_BUILD),true)
dist/activitywatch/aw-tauri:
	$(MAKE) package TAURI_BUILD=true

dist/ActivityWatch.app: aw-qt/media/logo/logo.icns dist/activitywatch/aw-tauri
	TAURI_WATCHERS="$(TAURI_WATCHERS)" scripts/package/build_app_tauri.sh
else
dist/ActivityWatch.app: aw-qt/media/logo/logo.icns
	$(PYINSTALLER) --clean --noconfirm aw.spec
endif

dist/ActivityWatch.dmg: dist/ActivityWatch.app
	# NOTE: This does not codesign the dmg, that is done in the CI config
	$(PYTHON) -m pip install dmgbuild
	dmgbuild -s scripts/package/dmgbuild-settings.py -D app=dist/ActivityWatch.app "ActivityWatch" dist/ActivityWatch.dmg

dist/notarize:
	./scripts/notarize.sh

package-dmg-unsigned: dist/ActivityWatch.dmg
	$(eval VERSION := $(shell scripts/package/getversion.sh))
	$(eval ARCH := $(shell uname -m))
	mv dist/ActivityWatch.dmg dist/activitywatch-$(VERSION)-macos-$(ARCH)-unsigned.dmg
	@echo "Built unsigned DMG: dist/activitywatch-$(VERSION)-macos-$(ARCH)-unsigned.dmg"

ifeq ($(OS),Windows_NT)
package: package-win

package-win: package-bundle-win package-installer-win

install-python-modules-win:
	@echo [stage] install-python-modules-win begin
	powershell -NoProfile -Command "$$py = Resolve-Path 'venv/Scripts/python.exe'; $$mods = @('aw-core','aw-client','aw-qt','aw-server','aw-watcher-input','aw-odoo-sync'); $$custom = '$(CUSTOM_WATCHERS)'.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries); foreach ($$m in $$mods) { Write-Host \"[stage] poetry install $$m\"; Push-Location $$m; & $$py -m poetry install; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; Pop-Location }; Write-Host '[stage] pip editable install core modules'; & $$py -m pip install -e .\aw-core -e .\aw-client -e .\aw-server -e .\aw-qt; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; Write-Host '[stage] pip editable install packaged watchers'; & $$py -m pip install -e .\aw-watcher-input --no-deps; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; & $$py -m pip install 'Pillow>=9.0,<12'; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; & $$py -m pip install -e .\aw-watcher-screenshot-mini; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; & $$py -m pip install -e .\aw-odoo-sync --no-deps; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; & $$py -m pip install 'chardet>=3.0.2,<6'; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; foreach ($$m in $$custom) { if (-not (Test-Path (Join-Path $$m 'dist'))) { Write-Host \"[stage] custom watcher $$m has no dist yet; it will be built in the bundle step\" } }; $$webuiRoot = Resolve-Path 'aw-server/aw-webui'; $$staticDir = Join-Path (Resolve-Path 'aw-server') 'aw_server/static'; New-Item -ItemType Directory -Force $$staticDir | Out-Null; if ('$(SKIP_WEBUI)' -ne 'true') { Write-Host '[stage] building aw-server web UI'; Push-Location $$webuiRoot; & npm ci; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; & npm run build; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; Pop-Location; Remove-Item (Join-Path $$staticDir '*') -Recurse -Force -ErrorAction SilentlyContinue; Copy-Item (Join-Path $$webuiRoot 'dist/*') $$staticDir -Recurse -Force; if (-not (Test-Path (Join-Path $$staticDir 'index.html'))) { throw 'aw-server web UI build did not produce index.html' } } else { Write-Host '[stage] skipping aw-server web UI build because SKIP_WEBUI=true' }"
	@echo [stage] install-python-modules-win end

package-bundle-win: install-python-modules-win
	@echo [stage] package-bundle-win begin
	@if not exist dist mkdir dist
	if exist dist\activitywatch rmdir /s /q dist\activitywatch
	@echo [stage] clean pycache begin
	powershell -NoProfile -Command "Get-ChildItem -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Write-Host 'Cleaned __pycache__ dirs'"
	@echo [stage] pyinstaller aw.spec begin
	powershell -NoProfile -Command "$$env:SKIP_SERVER_RUST = '$(SKIP_SERVER_RUST)'; venv\Scripts\python.exe -m PyInstaller --clean --noconfirm aw.spec --distpath dist --workpath build\pyinstaller"
	@echo [stage] pyinstaller standalone aw-qt begin
	powershell -NoProfile -Command "Push-Location 'aw-qt'; ..\venv\Scripts\python.exe -m PyInstaller aw-qt.spec --clean --noconfirm --distpath ..\dist --workpath ..\build\pyinstaller-aw-qt-standalone; Pop-Location"
	@echo [stage] bundle layout copy begin
	powershell -NoProfile -Command "$$bundle = 'dist/activitywatch'; $$qtRoot = Join-Path $$bundle 'aw-qt'; New-Item -ItemType Directory -Force $$qtRoot | Out-Null; Copy-Item 'dist/aw-qt/*' $$qtRoot -Recurse -Force; Get-ChildItem 'dist/aw-server' | Where-Object { $$_.Name -ne 'aw-server.exe' } | ForEach-Object { Copy-Item $$_.FullName $$qtRoot -Recurse -Force }; foreach ($$dir in @('aw-server')) { Copy-Item \"dist/$$dir\" $$qtRoot -Recurse -Force }; foreach ($$disabled in @('aw-watcher-afk','aw-watcher-window')) { $$disabledTarget = Join-Path $$qtRoot $$disabled; if (Test-Path $$disabledTarget) { Remove-Item $$disabledTarget -Recurse -Force } }; $$inputTarget = Join-Path $$qtRoot 'aw-watcher-input'; if (Test-Path $$inputTarget) { Remove-Item $$inputTarget -Recurse -Force }; New-Item -ItemType Directory -Force $$inputTarget | Out-Null; if (Test-Path 'aw-watcher-input/dist/aw-watcher-input') { Copy-Item 'aw-watcher-input/dist/aw-watcher-input/*' $$inputTarget -Recurse -Force } elseif (Test-Path 'dist/aw-watcher-input') { Copy-Item 'dist/aw-watcher-input/*' $$inputTarget -Recurse -Force }; if (Test-Path 'aw-watcher-input/config.toml.example') { Copy-Item 'aw-watcher-input/config.toml.example' (Join-Path $$inputTarget 'config.toml.example') -Force }; $$syncTarget = Join-Path $$qtRoot 'aw-odoo-sync'; if (Test-Path $$syncTarget) { Remove-Item $$syncTarget -Recurse -Force }; New-Item -ItemType Directory -Force $$syncTarget | Out-Null; if (Test-Path 'aw-odoo-sync/dist/aw-odoo-sync') { Copy-Item 'aw-odoo-sync/dist/aw-odoo-sync/*' $$syncTarget -Recurse -Force } elseif (Test-Path 'dist/aw-odoo-sync') { Copy-Item 'dist/aw-odoo-sync/*' $$syncTarget -Recurse -Force }; if (Test-Path 'aw-odoo-sync/config.toml.example') { Copy-Item 'aw-odoo-sync/config.toml.example' (Join-Path $$syncTarget 'config.toml.example') -Force }"
	@echo [stage] force aw-qt overlay begin
	powershell -NoProfile -Command "$$qtRoot = 'dist/activitywatch/aw-qt'; Copy-Item 'dist/aw-qt/aw-qt.exe' (Join-Path $$qtRoot 'aw-qt.exe') -Force; if (Test-Path (Join-Path $$qtRoot 'aw_qt')) { Remove-Item (Join-Path $$qtRoot 'aw_qt') -Recurse -Force }; Copy-Item 'dist/aw-qt/aw_qt' $$qtRoot -Recurse -Force; if (Test-Path (Join-Path $$qtRoot 'PyQt6')) { Remove-Item (Join-Path $$qtRoot 'PyQt6') -Recurse -Force }; Copy-Item 'dist/aw-qt/PyQt6' $$qtRoot -Recurse -Force; Copy-Item 'dist/aw-qt/python3.dll' (Join-Path $$qtRoot 'python3.dll') -Force"
	@echo [stage] rebuild aw-odoo-sync begin
	powershell -NoProfile -Command "$$py = Resolve-Path 'venv/Scripts/python.exe'; Push-Location 'aw-odoo-sync'; & $$py -m PyInstaller 'aw-odoo-sync.spec' --distpath 'dist' --workpath '../build/pyinstaller-aw-odoo-sync' --clean --noconfirm; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; Pop-Location; $$syncTarget = 'dist/activitywatch/aw-qt/aw-odoo-sync'; if (Test-Path $$syncTarget) { Remove-Item $$syncTarget -Recurse -Force }; Copy-Item 'aw-odoo-sync/dist/aw-odoo-sync' 'dist/activitywatch/aw-qt' -Recurse -Force; if (Test-Path 'aw-odoo-sync/config.toml.example') { Copy-Item 'aw-odoo-sync/config.toml.example' (Join-Path $$syncTarget 'config.toml.example') -Force }"
	@echo [stage] custom watcher package begin CUSTOM_WATCHERS=$(CUSTOM_WATCHERS)
	powershell -NoProfile -Command "$$py = Resolve-Path 'venv/Scripts/python.exe'; $$qtRoot = 'dist/activitywatch/aw-qt'; $$custom = '$(CUSTOM_WATCHERS)'.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries); foreach ($$m in $$custom) { $$spec = Join-Path $$m ($$m + '.spec'); if (-not (Test-Path $$spec)) { throw ('Missing spec file for ' + $$m + ': ' + $$spec) }; Write-Host \"Packaging $$m\"; Push-Location $$m; & $$py -m PyInstaller ($$m + '.spec') --clean --noconfirm; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; Pop-Location; $$targetDir = Join-Path $$qtRoot $$m; if (Test-Path $$targetDir) { Remove-Item $$targetDir -Recurse -Force }; Copy-Item (Join-Path $$m ('dist/' + $$m)) $$qtRoot -Recurse -Force; $$visSrc = Join-Path $$m 'visualization'; $$visDst = Join-Path $$targetDir 'visualization'; if (Test-Path $$visSrc) { New-Item -ItemType Directory -Force $$visDst | Out-Null; Copy-Item (Join-Path $$visSrc '*') $$visDst -Recurse -Force }; $$configExample = Join-Path $$m 'config.toml.example'; if (Test-Path $$configExample) { Copy-Item $$configExample (Join-Path $$targetDir 'config.toml.example') -Force } }"
	@echo [stage] custom rust watcher package begin CUSTOM_RUST_WATCHERS=$(CUSTOM_RUST_WATCHERS)
	powershell -NoProfile -Command "$$qtRoot = 'dist/activitywatch/aw-qt'; $$rustWatchers = '$(CUSTOM_RUST_WATCHERS)'.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries); foreach ($$m in $$rustWatchers) { if (-not $$m) { continue }; Write-Host \"Building Rust watcher $$m\"; Push-Location $$m; cargo build --release; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; Pop-Location; $$targetDir = Join-Path $$qtRoot $$m; New-Item -ItemType Directory -Force $$targetDir | Out-Null; $$exeName = $$m + '.exe'; Copy-Item (Join-Path $$m ('target/release/' + $$exeName)) $$targetDir -Force; $$configExample = Join-Path $$m 'config.toml.example'; if (Test-Path $$configExample) { Copy-Item $$configExample (Join-Path $$targetDir 'config.toml.example') -Force } }"
	@echo [stage] remove disabled watcher dirs begin
	powershell -NoProfile -Command "$$qtRoot = 'dist/activitywatch/aw-qt'; foreach ($$disabled in @('aw-watcher-afk','aw-watcher-window')) { $$disabledTarget = Join-Path $$qtRoot $$disabled; if (Test-Path $$disabledTarget) { Remove-Item $$disabledTarget -Recurse -Force; Write-Host \"Removed $$disabledTarget\" } }"
	@echo [stage] package-bundle-win end

package-installer-win: package-bundle-win
	powershell -NoProfile -Command "$$line = Get-Content 'aw-server/aw_server/__about__.py' | Where-Object { $$_ -match '__version__\s*=' } | Select-Object -First 1; if (-not $$line) { throw 'Could not determine version' }; $$version = ($$line.Split('=')[1]).Trim().Trim('\"'); if ($$version.StartsWith('v')) { $$version = $$version.Substring(1) }; $$env:AW_VERSION = $$version; $$iscc = '$(ISCC)'; if ($$iscc -eq 'iscc' -and (Test-Path '$(ISCC_FALLBACK)')) { $$iscc = '$(ISCC_FALLBACK)' }; if (-not (Test-Path $$iscc)) { throw \"ISCC not found at $$iscc\" }; $$proc = Start-Process -FilePath $$iscc -ArgumentList 'scripts/package/activitywatch-setup.iss' -NoNewWindow -Wait -PassThru; exit $$proc.ExitCode"

package-watchers-win:
	powershell -NoProfile -Command "if (-not (Test-Path 'dist/activitywatch/aw-qt')) { throw 'dist/activitywatch/aw-qt not found. Run make package-bundle-win once first.' }; $$py = Resolve-Path 'venv/Scripts/python.exe'; Write-Host 'Rebuilding aw-odoo-sync...'; Push-Location 'aw-odoo-sync'; & $$py -m PyInstaller 'aw-odoo-sync.spec' --distpath 'dist' --workpath '../build/pyinstaller-aw-odoo-sync' --clean --noconfirm; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; Pop-Location; $$syncTarget = 'dist/activitywatch/aw-qt/aw-odoo-sync'; if (Test-Path $$syncTarget) { Remove-Item $$syncTarget -Recurse -Force }; Copy-Item 'aw-odoo-sync/dist/aw-odoo-sync' 'dist/activitywatch/aw-qt' -Recurse -Force; if (Test-Path 'aw-odoo-sync/config.toml.example') { Copy-Item 'aw-odoo-sync/config.toml.example' (Join-Path $$syncTarget 'config.toml.example') -Force }; Write-Host 'Rebuilding aw-watcher-screenshot-mini...'; Push-Location 'aw-watcher-screenshot-mini'; & $$py -m PyInstaller 'aw-watcher-screenshot-mini.spec' --clean --noconfirm; if ($$LASTEXITCODE -ne 0) { exit $$LASTEXITCODE }; Pop-Location; $$watcherTarget = 'dist/activitywatch/aw-qt/aw-watcher-screenshot-mini'; if (Test-Path $$watcherTarget) { Remove-Item $$watcherTarget -Recurse -Force }; Copy-Item 'aw-watcher-screenshot-mini/dist/aw-watcher-screenshot-mini' 'dist/activitywatch/aw-qt' -Recurse -Force; if (Test-Path 'aw-watcher-screenshot-mini/config.toml.example') { Copy-Item 'aw-watcher-screenshot-mini/config.toml.example' (Join-Path $$watcherTarget 'config.toml.example') -Force }; $$visSrc = 'aw-watcher-screenshot-mini/visualization'; $$visDst = Join-Path $$watcherTarget 'visualization'; if (Test-Path $$visSrc) { New-Item -ItemType Directory -Force $$visDst | Out-Null; Copy-Item (Join-Path $$visSrc '*') $$visDst -Recurse -Force }"

package-installer-win-quick:
	powershell -NoProfile -Command "if (-not (Test-Path 'dist/activitywatch')) { throw 'dist/activitywatch not found. Run make package-bundle-win once first.' }; $$line = Get-Content 'aw-server/aw_server/__about__.py' | Where-Object { $$_ -match '__version__\s*=' } | Select-Object -First 1; if (-not $$line) { throw 'Could not determine version' }; $$version = ($$line.Split('=')[1]).Trim().Trim('\"'); if ($$version.StartsWith('v')) { $$version = $$version.Substring(1) }; $$env:AW_VERSION = $$version; $$iscc = '$(ISCC)'; if ($$iscc -eq 'iscc' -and (Test-Path '$(ISCC_FALLBACK)')) { $$iscc = '$(ISCC_FALLBACK)' }; if (-not (Test-Path $$iscc)) { throw \"ISCC not found at $$iscc\" }; $$proc = Start-Process -FilePath $$iscc -ArgumentList 'scripts/package/activitywatch-setup.iss' -NoNewWindow -Wait -PassThru; exit $$proc.ExitCode"

package-win-no-rust:
	$(MAKE) package-bundle-win SKIP_SERVER_RUST=true CUSTOM_RUST_WATCHERS=
	$(MAKE) package-installer-win-quick
else
package:
	rm -rf dist
	mkdir -p dist/activitywatch
ifeq ($(TAURI_BUILD),true)
	$(MAKE) install-tauri-python-modules PYTHON=$(PYTHON)
endif
	for dir in $(PACKAGEABLES); do \
		$(MAKE) --directory=$$dir package PYTHON=$(PYTHON) POETRY=$(POETRY); \
		cp -r $$dir/dist/$$dir dist/activitywatch; \
	done
ifeq ($(TAURI_BUILD),true)
# Package Tauri-managed watchers into dist/activitywatch for macOS app bundling.
	for dir in $(TAURI_WATCHERS); do \
		$(MAKE) install-tauri-python-modules PYTHON=$(PYTHON) || { echo "Error refreshing local Python modules before packaging $$dir"; exit 2; }; \
		$(MAKE) --directory=$$dir package PYTHON=$(PYTHON) POETRY=$(POETRY); \
		cp -r $$dir/dist/$$dir dist/activitywatch; \
	done
# Copy aw-sync binary for Tauri builds
	mkdir -p dist/activitywatch/aw-server-rust
	cp aw-server-rust/target/$(targetdir)/aw-sync dist/activitywatch/aw-server-rust/aw-sync
# Copy aw-tauri binary for macOS app bundling (build_app_tauri.sh expects a file, not a dir).
# Some Tauri bundle modes leave the executable only inside the generated .app bundle.
	if [ -f aw-tauri/src-tauri/target/$(targetdir)/aw-tauri ]; then \
		cp aw-tauri/src-tauri/target/$(targetdir)/aw-tauri dist/activitywatch/aw-tauri; \
	elif [ -f aw-tauri/src-tauri/target/$(targetdir)/bundle/macos/ActivityWatch.app/Contents/MacOS/aw-tauri ]; then \
		cp aw-tauri/src-tauri/target/$(targetdir)/bundle/macos/ActivityWatch.app/Contents/MacOS/aw-tauri dist/activitywatch/aw-tauri; \
	else \
		echo "Error: aw-tauri binary not found in target/$(targetdir) or bundle/macos/ActivityWatch.app"; \
		find aw-tauri/src-tauri/target/$(targetdir) -maxdepth 5 -type f -perm -111 -print 2>/dev/null || true; \
		exit 2; \
	fi
else
# Move aw-qt to the root of the dist folder
	mv dist/activitywatch/aw-qt aw-qt-tmp
	mv aw-qt-tmp/* dist/activitywatch
	rmdir aw-qt-tmp
endif
# Remove problem-causing binaries
	rm -f dist/activitywatch/libdrm.so.2       # see: https://github.com/ActivityWatch/activitywatch/issues/161
	rm -f dist/activitywatch/libharfbuzz.so.0  # see: https://github.com/ActivityWatch/activitywatch/issues/660#issuecomment-959889230
# These should be provided by the distro itself
# Had to be removed due to otherwise causing the error:
#   aw-qt: symbol lookup error: /opt/activitywatch/libQt5XcbQpa.so.5: undefined symbol: FT_Get_Font_Format
	rm -f dist/activitywatch/libfontconfig.so.1
	rm -f dist/activitywatch/libfreetype.so.6
# Remove unnecessary files
	rm -rf dist/activitywatch/pytz
# Builds zips and setups
	bash scripts/package/package-all.sh
endif

clean:
	rm -rf build dist

# Clean all subprojects
clean_all: clean
	for dir in $(SUBMODULES); do \
		make --directory=$$dir clean; \
	done

clean-auto:
	rm -rIv **/aw-server-rust/target
	rm -rIv **/aw-android/mobile/build
	rm -rIfv **/node_modules
