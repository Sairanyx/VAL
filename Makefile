VIEWS_TAG ?= views-v1
VIEWS_FILE ?= equipment_room_views_v1.tar
DATABASE_URL ?= postgresql://copilot:copilot@127.0.0.1:5433/copilot
SCENE_TAG ?= scene-v2
SCENE_FILE ?= scene_v2.tar
SCENE_DIR ?= data/scene/splat_v2
SCENE_FULL ?= clean.ply

.PHONY: setup entire views scene scene-full gpu train tb web fmt lint test check up api floor mapping db

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
scene:   ## get the demo scene, floor map and objects from the GitHub Release, or use ARCHIVE=path
ifndef ARCHIVE
	mkdir -p data/scene
	gh release download $(SCENE_TAG) --pattern $(SCENE_FILE) --dir data/scene --clobber
endif
	mkdir -p $(SCENE_DIR)
	tar -xf $(or $(ARCHIVE),data/scene/$(SCENE_FILE)) -C $(SCENE_DIR)
	@echo "Viewer: make web SCENE=$(SCENE_DIR)/light_full.ply ASSETS=$(SCENE_DIR)/assets_viewer.json SHAPES=$(SCENE_DIR)/shapes.json"
	@echo "API:    SCENE_ASSETS=$(SCENE_DIR)/assets_viewer.json SCENE_GRID=$(SCENE_DIR)/nav_grid.npz make api"
scene-full: ## get the full-quality scene (513 MB), for the viewer on a PC and rebuilding the floor map
	mkdir -p $(SCENE_DIR)
	gh release download $(SCENE_TAG) --pattern $(SCENE_FULL) --dir $(SCENE_DIR) --clobber
	@echo "Viewer: make web SCENE=$(SCENE_DIR)/$(SCENE_FULL) ASSETS=$(SCENE_DIR)/assets_viewer.json SHAPES=$(SCENE_DIR)/shapes.json"
gpu:     ## check the GPU works
	uv run python -m app.gpu_check
db:      ## start local TimescaleDB and load the Excel telemetry
	docker compose up -d --wait db
	DATABASE_URL=$(DATABASE_URL) uv run python -m app.api.db
api:     ## backend API at http://localhost:8001/docs
	DATABASE_URL=$(DATABASE_URL) \
	uv run uvicorn app.api.main:app --host 0.0.0.0 --port 8001 --reload
floor:   ## floor map: make floor SCENE="path/to/Equipment Room.ply"
	uv run python -m app.nav.grid "$(SCENE)" --out data/scene/equipment_room/nav_grid.npz --preview runs/floor.png
mapping: ## link Excel records to objects, marking them procedural
	uv run python -m app.copilot.mapping $(SCENE_DIR)
train:   ## train a model
	uv run python -m app.train
tb:      ## training graphs at http://localhost:6006
	uv run tensorboard --logdir runs
SCENE ?= data/scene/sample/scene.ply
web:     ## web viewer on port 8000, SCENE= picks the splat, HTTPS=1 for phone sensors
	uv run python web/serve.py --scene "$(SCENE)" $(if $(HTTPS),--https) $(if $(ASSETS),--assets "$(ASSETS)") $(if $(SHAPES),--shapes "$(SHAPES)")
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
