CREATE TABLE jobs (
    id uuid PRIMARY KEY,
    idempotency_key varchar(80) NOT NULL UNIQUE,
    text_content text NOT NULL CHECK (octet_length(text_content) BETWEEN 1 AND 4096),
    content_sha256 char(64) NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
    lease_token uuid,
    lease_until timestamptz,
    result jsonb,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((status = 'running') = (lease_token IS NOT NULL AND lease_until IS NOT NULL)),
    CHECK ((status = 'succeeded') = (result IS NOT NULL))
);
CREATE INDEX jobs_claim ON jobs (created_at) WHERE status IN ('queued', 'running');
GRANT SELECT, INSERT, UPDATE ON jobs TO ops_app;
