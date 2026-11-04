.PHONY: setup gpu dev ui test lint fmt up down deploy keys models models-list cloudrun zip train tb

setup:   ## install everything (GPU PyTorch) + .env + git hooks
	cp -n .env.example .env || true
	uv sync
	uv run pre-commit install
gpu:     ## check PyTorch sees the GPU
	uv run python -m app.gpu_check
dev:     ## run API locally with reload
	uv run uvicorn app.main:app --reload
ui:      ## Streamlit demo page
	uv run streamlit run app/ui.py
train:   ## run the training template
	uv run python -m app.train
tb:      ## TensorBoard for training curves
	uv run tensorboard --logdir runs
test:
	uv run pytest -q
lint:
	uv run ruff check . && uv run ruff format --check .
fmt:
	uv run ruff check --fix . && uv run ruff format .
up:
	docker compose up --build
down:
	docker compose down
deploy:  ## push main first, then redeploy on the VPS
	./deploy/deploy.sh
keys:    ## test API keys in .env
	uv run python -m scripts.check_keys
models:  ## pre-download the lightweight HF models
	uv run python -m scripts.predownload_models
models-list:  ## list API model ids: make models-list P=gemini
	uv run python -m scripts.check_keys $(P)
cloudrun:  ## fallback deploy of the API to Google Cloud Run
	./deploy/cloudrun.sh
zip:     ## submission source zip from last commit
	./scripts/make_zip.sh
