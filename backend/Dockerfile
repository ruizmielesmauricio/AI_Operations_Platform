FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg (binary wheel avoids needing libpq-dev, but keep this
# minimal set in case a future dependency needs a build step).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Optional extra CA certs (e.g. a corporate TLS-inspecting proxy) for networks
# that intercept HTTPS. certs/ is normally empty — harmless no-op then.
# pip bundles its own CA list (via certifi) rather than using the OS trust
# store, so PIP_CERT is needed to point it at the updated system bundle too.
COPY certs/ /usr/local/share/ca-certificates/local/
RUN update-ca-certificates
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt

COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
