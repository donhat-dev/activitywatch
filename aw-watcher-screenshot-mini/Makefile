.PHONY: build test package clean

build:
	poetry install

test:
	poetry run aw-watcher-screenshot-mini --help  # Ensures that it at least starts

package:
	pyinstaller aw-watcher-screenshot-mini.spec --clean --noconfirm

clean:
	rm -rf build dist
	rm -rf aw_watcher_screenshot_mini/__pycache__
