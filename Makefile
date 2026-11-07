VIEWS_TAG ?= views-v1
VIEWS_FILE ?= equipment_room_views_v1.tar
DATABASE_URL ?= postgresql://copilot:copilot@127.0.0.1:5433/copilot
FLOOR_SCENE ?= $(SCENE_DIR)/Equipment Room.ply
SCENE_TAG ?= objects-v2
SCENE_FILE ?= objects_v2.tar
SCENE_DIR ?= data/scene/equipment_room
SCENE_FULL ?= clean.ply
PIECES_OBJECTS ?= obj-0067 obj-0021 obj-0112
PIECES_BOX ?= obj-0067
PIECES_FROM ?= $(SCENE_DIR)/Equipment Room.ply
PIECES_DIR ?= $(SCENE_DIR)/cut
HIGHLIGHTS_DIR ?= $(SCENE_DIR)/highlights
HIGHLIGHTS ?= $(if $(filter $(SCENE_DIR)/%,$(SCENE)),$(if $(wildcard $(HIGHLIGHTS_DIR)/highlights.json),$(HIGHLIGHTS_DIR)))
# Phones and tablets load this lighter scene. Not with PIECES: it still has the cut-out objects.
LIGHT ?= $(if $(PIECES),,$(if $(filter $(SCENE_DIR)/%,$(SCENE)),$(wildcard $(SCENE_DIR)/light_full.ply)))
BIM_DIR ?= $(SCENE_DIR)/bim
BIM ?= $(if $(filter $(SCENE_DIR)/%,$(SCENE)),$(if $(wildcard $(BIM_DIR)/bim.json),$(BIM_DIR)))
MODEL ?= Qwen3.5-9B
MODEL_DIR ?= data/models/$(MODEL)
LAPTOP_MODEL ?= gemma4:e2b
VOICE_MODEL ?= small.en

.PHONY: setup entire views scene scene-full model laptop-model voice-model pieces highlights shapes bim pipeline gpu train tb web fmt lint test check up api floor mapping db nav-check start-browser start-laptop start-tablet

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
scene:   ## get the original scene's objects and light splats from the GitHub Release, or use ARCHIVE=path
ifndef ARCHIVE
	mkdir -p data/scene
	gh release download $(SCENE_TAG) --pattern $(SCENE_FILE) --dir data/scene --clobber
endif
	mkdir -p $(SCENE_DIR)
	tar -xf $(or $(ARCHIVE),data/scene/$(SCENE_FILE)) -C $(SCENE_DIR)
	@echo "Next: put 'Equipment Room.ply' in $(SCENE_DIR) and the Excel pack in data/, then: make mapping db api"
	@echo "Viewer on a PC: make web SCENE=\"$(SCENE_DIR)/Equipment Room.ply\" ASSETS=$(SCENE_DIR)/assets_mapped.json SHAPES=$(SCENE_DIR)/shapes.json"
	@echo "Viewer on a tablet: use SCENE=$(SCENE_DIR)/light_full.ply, or light_400k.ply if it's slow"
scene-full: ## get our own full-quality splat (513 MB). The demo uses the original scene instead
	mkdir -p $(SCENE_DIR)
	gh release download scene-v2 --pattern $(SCENE_FULL) --dir data/scene/splat_v2 --clobber
	@echo "Viewer: make web SCENE=data/scene/splat_v2/$(SCENE_FULL) ASSETS=$(SCENE_DIR)/assets_viewer.json SHAPES=$(SCENE_DIR)/shapes.json"
laptop-model: ## get Val's small model for a laptop with no GPU, before going offline. Needs Ollama
	ollama pull $(LAPTOP_MODEL)
voice-model: ## get the speech-to-text model for talking to Val, before going offline (about 460 MB)
	uv run python -c "from huggingface_hub import snapshot_download as s; s('Systran/faster-whisper-$(VOICE_MODEL)', local_dir='data/models/whisper-$(VOICE_MODEL)')"
model:   ## download the copilot's language model once, before going offline (about 20 GB)
	uv run python -c "from huggingface_hub import snapshot_download as s; s('Qwen/$(MODEL)', local_dir='$(MODEL_DIR)', allow_patterns=['*.safetensors', '*.json', '*.txt', '*.jinja', 'merges*', 'vocab*'])"
pieces:  ## cut movable objects out of a scene, so dragging moves the real thing. Then: make web SCENE=$(PIECES_DIR)/base.ply PIECES=$(PIECES_DIR)
	uv run python -m app.scene.split_movable "$(PIECES_FROM)" $(SCENE_DIR)/assets_viewer.json $(PIECES_DIR) --objects $(PIECES_OBJECTS) --members $(SCENE_DIR)/members.npz --box $(PIECES_BOX)
highlights: ## export segmented object surfaces for cyan selection highlighting
	uv run python -m app.scene.highlights "$(SCENE_DIR)/Equipment Room.ply" $(SCENE_DIR)/assets_final.json $(SCENE_DIR)/splat_labels.npy $(HIGHLIGHTS_DIR) $(if $(wildcard $(PIECES_DIR)/pieces.json),--pieces $(PIECES_DIR))
shapes:  ## fit object shapes again, which applies newer fit rules to the Release's copy
	uv run python -m app.extract.primitives $(SCENE_DIR)/assets_final.json "$(SCENE_DIR)/Equipment Room.ply" $(SCENE_DIR)/splat_labels.npy $(SCENE_DIR)/shapes.json
bim: shapes ## simulated BIM model of the room for the viewer's BIM mode, plus model.ifc (IFC4)
	uv run python -m app.bim "$(SCENE_DIR)/Equipment Room.ply" $(SCENE_DIR)/assets_mapped.json $(SCENE_DIR)/shapes.json $(BIM_DIR) --labels $(SCENE_DIR)/splat_labels.npy --label-assets $(SCENE_DIR)/assets_final.json $(if $(wildcard $(PIECES_DIR)/pieces.json),--pieces $(PIECES_DIR))
pipeline: ## run a scene through everything: make pipeline CONFIG=scenes/equipment_room.toml, DRY=1 to preview
	uv run python scripts/pipeline.py $(or $(CONFIG),scenes/equipment_room.toml) $(if $(DRY),--dry-run)
start-browser: ## start everything for a laptop or PC. Same as ./start browser
	./start browser
start-laptop: ## start everything for a laptop with no graphics card, using the light scene. Same as ./start laptop
	./start laptop
start-tablet: ## start everything for the Lenovo tablet. Same as ./start tablet
	./start tablet
gpu:     ## check the GPU works
	uv run python -m app.gpu_check
db:      ## start local TimescaleDB and load the Excel telemetry
	docker compose up -d --wait db
	DATABASE_URL=$(DATABASE_URL) uv run python -m app.api.db
api:     ## backend API at http://localhost:8001/docs. Uses the language model if make model has run
	$(if $(wildcard $(MODEL_DIR)/config.json),COPILOT_MODEL=$(MODEL_DIR),$(if $(shell ollama list 2>/dev/null | grep -F '$(LAPTOP_MODEL)'),COPILOT_OLLAMA=$(LAPTOP_MODEL))) SCENE_PLY="$(FLOOR_SCENE)" DATABASE_URL=$(DATABASE_URL) SCENE_ASSETS=$(SCENE_DIR)/assets_mapped.json SCENE_GRID=$(SCENE_DIR)/nav_grid.npz \
	uv run uvicorn app.api.main:app --host 0.0.0.0 --port 8001 --reload --reload-dir app
floor:   ## rebuild the floor map (make scene includes one), needs "Equipment Room.ply" in SCENE_DIR. Pass VIEWS=, or floaters block aisles
	uv run python -m app.nav.grid "$(FLOOR_SCENE)" $(if $(VIEWS),--views $(VIEWS)) $(if $(wildcard $(SCENE_DIR)/walked.npy),--walked $(SCENE_DIR)/walked.npy) --labels $(SCENE_DIR)/splat_labels.npy --assets $(SCENE_DIR)/assets_final.json --out $(SCENE_DIR)/nav_grid.npz --preview runs/floor.png
nav-check: ## test floor map, routes, mapping and API together, and draw runs/nav_check.png
	uv run python -m app.nav.check $(SCENE_DIR)
mapping: ## link Excel records to objects, marking them procedural
	uv run python -m app.copilot.mapping $(SCENE_DIR)
train:   ## train a model
	uv run python -m app.train
tb:      ## training graphs at http://localhost:6006
	uv run tensorboard --logdir runs
SCENE ?= data/scene/sample/scene.ply
web:     ## web viewer on port 8000, SCENE= picks the splat, HTTPS=1 for phone sensors, LIGHT= for phones
	uv run python web/serve.py --scene "$(SCENE)" $(if $(HTTPS),--https) $(if $(ASSETS),--assets "$(ASSETS)") $(if $(SHAPES),--shapes "$(SHAPES)") $(if $(PIECES),--pieces "$(PIECES)") $(if $(HIGHLIGHTS),--highlights "$(HIGHLIGHTS)") $(if $(LIGHT),--light "$(LIGHT)") $(if $(BIM),--bim "$(BIM)")
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
