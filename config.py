"""Kushki MCP Server — configuration module."""

import logging
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s", "level":"%(levelname)s", "name":"%(name)s", "message":"%(message)s"}',
)
logger = logging.getLogger("kushki-mcp")

KUSHKI_ENVIRONMENT: str = os.getenv("KUSHKI_ENVIRONMENT", "production").lower()
if KUSHKI_ENVIRONMENT not in ("sandbox", "production"):
    raise ValueError(
        f"KUSHKI_ENVIRONMENT inválido: {KUSHKI_ENVIRONMENT!r}. "
        "Valores permitidos: 'sandbox' | 'production'."
    )

BASE_URL: str = (
    "https://api.kushkipagos.com"
    if KUSHKI_ENVIRONMENT == "production"
    else "https://api-uat.kushkipagos.com"
)
HTTP_TIMEOUT: float = 30.0
