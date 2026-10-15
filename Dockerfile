# Minimal image for the Singularis MCP client shell (client only; no engine code).
FROM python:3.12-slim

WORKDIR /app

# Install the published client from source in this repo.
COPY . /app
RUN pip install --no-cache-dir .

# No API key is required to start; the server lists its tools (introspection)
# without one. Jobs that need credits call singularis_register_key at runtime.
ENV SINGULARIS_COUNTRY=US

ENTRYPOINT ["singularis-mcp"]
