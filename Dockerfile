FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
ARG INSTALL_EMBEDDINGS=0
COPY pyproject.toml README.md /app/
COPY services /app/services
COPY scripts /app/scripts
COPY fixtures /app/fixtures
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini
RUN pip install --upgrade pip && \
    if [ "$INSTALL_EMBEDDINGS" = "1" ]; then \
      pip install -e ".[dev,embeddings]" --extra-index-url https://download.pytorch.org/whl/cpu; \
    else \
      pip install -e ".[dev]"; \
    fi
COPY tests /app/tests
CMD ["uvicorn", "services.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
