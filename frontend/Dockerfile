FROM node:22-slim

WORKDIR /app

# Optional extra CA certs (e.g. a corporate TLS-inspecting proxy) for networks
# that intercept HTTPS. certs/ is normally empty — harmless no-op then.
# Node ignores the OS trust store by default, so this also bundles any certs
# into a PEM file and points NODE_EXTRA_CA_CERTS at it (empty file = no-op).
COPY certs/ /usr/local/share/ca-certificates/local/
RUN cat /usr/local/share/ca-certificates/local/*.crt > /usr/local/share/ca-certificates/local-bundle.pem 2>/dev/null; \
    touch /usr/local/share/ca-certificates/local-bundle.pem
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/local-bundle.pem

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
