"""Kushki FastMCP application instance."""

import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "Kushki",
    host=os.getenv("MCP_HOST", "0.0.0.0"),  # nosec B104
    instructions=(
        "MCP server for Kushki payment gateway. Supports card payments, "
        "cash payments (efectivo), bank transfers, and subscriptions. "
        "Credentials are loaded from KUSHKI_PUBLIC_KEY / KUSHKI_PRIVATE_KEY env vars. "
        "TYPICAL CARD FLOW: create_card_token → create_card_charge. "
        "TYPICAL CASH FLOW: create_cash_token → create_cash_charge. "
        "MONETARY INPUT RULES (agent must follow strictly): "
        "  · Pass `monto` (float) with the EXACT number the user stated. "
        "  · Pass `tipo_monto`='subtotal' if the amount is WITHOUT IVA (default). "
        "  · Pass `tipo_monto`='total_con_iva' if the amount ALREADY INCLUDES IVA. "
        "  · NEVER build the amount dict or calculate IVA yourself. "
        "  · The server builds {subtotalIva, subtotalIva0, iva, ice, currency} internally. "
        "ENVIRONMENT: set KUSHKI_ENVIRONMENT=production for live payments "
        "(default is sandbox at api-uat.kushkipagos.com). "
        "The IVA rate is read from IVA_EC_PERCENTAGE env var (default 15%)."
    ),
)
