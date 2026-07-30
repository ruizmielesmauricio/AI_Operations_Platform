FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg (binary wheel avoids needing libpq-dev, but keep this
# minimal set in case a future dependency needs a build step).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
