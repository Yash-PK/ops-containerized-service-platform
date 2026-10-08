FROM python:3.14.7-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS dependencies
WORKDIR /build
COPY requirements.lock .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes --only-binary=:all: -r requirements.lock

FROM python:3.14.7-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY opsjobs ./opsjobs
COPY migrations ./migrations
USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM
CMD ["python", "-m", "opsjobs.api"]
