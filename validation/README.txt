Portal / AI gateway validation

Run portal_gateway.py using a Python environment with the backend requirements.
Install the existing frontend and AI service package-lock.json dependencies with npm ci.
Run npx prisma generate in services/ai-tutor. Chrome must be installed.

python validation/portal_gateway.py --output C:/path/to/NEW-results

The output directory must not exist. The runner creates temporary domain and AI
SQLite databases and starts loopback-only Django, Next.js, Vite and a deterministic
OpenAI-compatible HTTP fixture. No production environment file is loaded. No real
provider credentials, operational database, or operational Redis is used.
The browser uses the real login page and real HTTP interfaces. Only the external
provider is simulated; its embeddings and generated text are not quality evidence.

Optional retention verification uses a NEW PostgreSQL cluster and a NEW Redis
process. Set AIEDU_PG_BIN to the installed PostgreSQL bin directory and
AIEDU_REDIS_SERVER to a local redis-server executable. The runner never connects
to an existing PostgreSQL database or Redis process.

python validation/retention_runner.py --output C:/path/to/NEW-retention-results

Retention tests verify controlled local instances, not the deployed service or
the provider account. Production account retention settings, backup retention,
and deployed Redis TTLs require separate operator evidence.
