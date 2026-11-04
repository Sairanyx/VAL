.PHONY: setup gpu train tb fmt up

setup:   ## install everything
	uv sync
gpu:     ## check the GPU works
	uv run python -m app.gpu_check
train:   ## train a model
	uv run python -m app.train
tb:      ## training graphs at http://localhost:6006
	uv run tensorboard --logdir runs
fmt:     ## tidy code style
	uv run ruff format .
up:      ## train inside Docker
	docker compose up --build
