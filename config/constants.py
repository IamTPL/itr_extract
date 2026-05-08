"""Centralized constants. NEVER inline literals for these values elsewhere."""
from pathlib import Path

# ── Session & retention ──
MAX_SESSIONS_PER_USER       = 10
MAX_ACTIVE_JOBS_PER_USER    = 5
MAX_INPUT_FILE_SIZE_BYTES   = 50 * 1024 * 1024

# ── Worker / retry ──
JOB_TIMEOUT_SECONDS         = 300
WORKER_MAX_CONCURRENT_JOBS  = 4
MAX_RETRY_ATTEMPTS          = 3
RETRY_BACKOFF_SECONDS       = (5, 15)
STUCK_JOB_THRESHOLD_SECONDS = 360

# ── Filesystem ──
FILES_ROOT_DEFAULT          = Path("/var/lib/itr_extract/files")
INPUT_FILENAME              = "input.pdf"
ECONSENT_FILENAME           = "econsent.pdf"

# ── Auth / JWT ──
JWKS_CACHE_TTL_SECONDS      = 3600
JWT_LEEWAY_SECONDS          = 60
JWT_ALGORITHM               = "RS256"
BEARER_PREFIX               = "Bearer "
AZURE_AUTHORITY_BASE        = "https://login.microsoftonline.com"

# ── Cron ──
CLEANUP_ORPHAN_FILES_HOUR     = 3
STUCK_JOB_SWEEP_INTERVAL_MIN  = 1

# ── Rate limit ──
USER_RATE_LIMIT             = "30/minute"

# ── HTTP ──
HEALTH_CHECK_TIMEOUT_SECONDS = 5
