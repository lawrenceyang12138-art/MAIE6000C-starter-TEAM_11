FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md /app/
# Dependency installation belongs to the image build, not a request handler.
# Install from metadata before copying application code, so ordinary source
# changes cannot invalidate the heavy dependency layer. The real package map is
# registered separately after its source tree exists.
RUN pip install --upgrade pip "setuptools>=80.0.0" wheel && pip install ".[dev,embeddings]" --extra-index-url https://download.pytorch.org/whl/cpu
COPY services /app/services
COPY scripts /app/scripts
COPY fixtures /app/fixtures
# Frozen evaluation inputs are part of the operator CLI runtime. Keep their
# original bytes and include only the three small JSON files the tools use.
COPY submissions/week07/gold-queries.json submissions/week07/gold-queries.freeze.json /app/submissions/week07/
COPY submissions/week07/evidence/C/model-manifest.json /app/submissions/week07/evidence/C/model-manifest.json
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini
COPY tests /app/tests
RUN pip install -e . --no-deps --no-build-isolation
CMD ["uvicorn", "services.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
