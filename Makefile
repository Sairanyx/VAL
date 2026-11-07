VIEWS_TAG ?= views-v1
VIEWS_FILE ?= equipment_room_views_v1.tar

.PHONY: setup entire views gpu train tb fmt lint test check up api floor

setup:   ## install everything
	uv sync
entire:  ## install and enable Entire, set AGENT= for other agents
	bash scripts/setup_entire.sh
views:   ## get rendered views from the GitHub Release, or use ARCHIVE=path for a local copy
ifndef ARCHIVE
	mkdir -p data/scene
	gh release download $(VIEWS_TAG) --pattern $(VIEWS_FILE) --dir data/scene --clobber
endif
	uv run scripts/views_archive.py unpack $(or $(ARCHIVE),data/scene/$(VIEWS_FILE)) data/scene/equipment_room
gpu:     ## check the GPU works
	uv run python -m app.gpu_check
api:     ## backend API at http://localhost:8001/docs
	uv run uvicorn app.api.main:app --host 0.0.0.0 --port 8001 --reload
floor:   ## floor map: make floor SCENE="path/to/Equipment Room.ply"
	uv run python -m app.nav.grid "$(SCENE)" --out data/scene/equipment_room/nav_grid.npz --preview runs/floor.png
train:   ## train a model
	uv run python -m app.train
tb:      ## training graphs at http://localhost:6006
	uv run tensorboard --logdir runs
fmt:     ## tidy code style and auto-fix lint
	uv run --only-group dev ruff format .
	uv run --only-group dev ruff check --fix .
lint:    ## check style without changing anything
	uv run --only-group dev ruff format --check .
	uv run --only-group dev ruff check .
test:    ## run the tests
	uv run pytest
check: lint test  ## run before finishing work
up:      ## train inside Docker
	docker compose up --build
