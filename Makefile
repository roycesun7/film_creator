.PHONY: test test-fast test-integration lint typecheck dev api frontend

test:
	python -m pytest tests/ -v

test-fast:
	python -m pytest tests/ -v -m "not slow"

test-integration:
	python -m pytest tests/test_integration.py -v

lint:
	python -m py_compile config.py
	python -m py_compile main.py
	python -m py_compile index/store.py
	python -m py_compile index/clip_embeddings.py
	python -m py_compile index/vision_describe.py
	python -m py_compile index/apple_photos.py
	python -m py_compile curate/search.py
	python -m py_compile curate/director.py
	python -m py_compile assemble/builder.py
	python -m py_compile assemble/themes.py
	python -m py_compile api.py
	@echo "All files compile successfully"

api:
	uvicorn api:app --reload --port 8000

frontend:
	cd frontend && npm run dev

dev:
	@echo "Run these in two terminals:"
	@echo "  make api       # starts FastAPI on :8000"
	@echo "  make frontend  # starts Vite on :5173"
