.PHONY: setup entire gpu train tb fmt lint test check up

setup:   ## install everything
	uv sync
entire:  ## install and enable Entire, set AGENT= for other agents
	bash scripts/setup_entire.sh
gpu:     ## check the GPU works
	uv run python -m app.gpu_check
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
