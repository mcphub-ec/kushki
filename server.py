"""
Kushki MCP Server v2.0.0
──────────────────────────
Model Context Protocol (MCP) server bridging the Kushki Payments API.

Transport: Streamable HTTP  →  POST/GET/DELETE  http://<host>:8006/mcp

MULTI-ACCOUNT SUPPORT (v2.0):
  Every tool accepts `public_key` and `private_key` as explicit parameters.
  The server internally decides which key to use based on the operation type.
  The agent should ALWAYS pass both keys per call.

Authentication modes:
  · Public key:  Used ONLY for token creation (create_card_token, create_cash_token,
                 create_transfer_token).
  · Private key: Used for all charge/mutation operations.
"""

import os
import json
import logging
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Optional

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()


# ─────────────────────────────────────────────────────────────────────
# Motor fiscal determinista — IVA Ecuador (Kushki)
# ─────────────────────────────────────────────────────────────────────
# El LLM NUNCA calcula impuestos ni construye el dict `amount`.
# Solo pasa `monto` + `tipo_monto`. Este módulo produce el objeto amount
# exacto que espera la API de Kushki: {subtotalIva, subtotalIva0, iva, ice, currency}.
# ─────────────────────────────────────────────────────────────────────

class TipoMonto(str, Enum):
    """Indica si el monto dado por el usuario incluye IVA o es la base imponible."""
    SUBTOTAL      = "subtotal"       # el usuario dio la base SIN IVA  (default)
    TOTAL_CON_IVA = "total_con_iva"  # el usuario dio el total CON IVA incluido


_TWO = Decimal("0.01")


def _iva_rate() -> Decimal:
    """Lee IVA_EC_PERCENTAGE del entorno. Fallback: 0.15 (15%)."""
    raw = os.environ.get("IVA_EC_PERCENTAGE", "0.15")
    try:
        rate = Decimal(raw)
        if not (Decimal(0) < rate <= Decimal(1)):
            raise ValueError()
        return rate
    except Exception:
        raise ValueError(
            f"IVA_EC_PERCENTAGE inválido: {raw!r}. "
            "Debe ser un decimal entre 0 y 1, ej. '0.15' para 15%."
        )


def _r2(v: Decimal) -> Decimal:
    """Redondeo estricto a 2 decimales (ROUND_HALF_UP)."""
    return v.quantize(_TWO, rounding=ROUND_HALF_UP)


def _calcular_monto_kushki(
    monto: float, tipo: TipoMonto, currency: str = "USD"
) -> dict:
    """Construye el objeto `amount` que exige la API de Kushki.

    Kushki espera un dict con floats:
        {subtotalIva, subtotalIva0, iva, ice, currency}
    donde subtotalIva = base gravada (sin IVA), subtotalIva0 = base cero.
    En el flujo estándar gravado, subtotalIva0 e ice son siempre 0.

    Args:
        monto:    El valor exacto dado por el usuario (en USD).
        tipo:     TipoMonto.SUBTOTAL      → monto es la base sin IVA.
                  TipoMonto.TOTAL_CON_IVA → monto es el total ya con IVA.
        currency: Código de moneda (default "USD").

    Returns:
        dict listo para usar como `amount` en create_card_charge / create_cash_charge.

    Ejemplos:
        _calcular_monto_kushki(30.0, SUBTOTAL)
            → {subtotalIva: 30.0, subtotalIva0: 0.0, iva: 4.5, ice: 0.0, currency: 'USD'}
        _calcular_monto_kushki(30.0, TOTAL_CON_IVA)
            → {subtotalIva: 26.09, subtotalIva0: 0.0, iva: 3.91, ice: 0.0, currency: 'USD'}
    """
    if monto <= 0:
        raise ValueError(f"monto debe ser > 0. Recibido: {monto}")
    rate = _iva_rate()
    d = Decimal(str(monto))

    if tipo == TipoMonto.TOTAL_CON_IVA:
        total    = _r2(d)
        subtotal = _r2(d / (1 + rate))
        iva      = _r2(total - subtotal)
    else:  # SUBTOTAL
        subtotal = _r2(d)
        iva      = _r2(d * rate)

    return {
        "subtotalIva":  float(subtotal),
        "subtotalIva0": 0.0,
        "iva":          float(iva),
        "ice":          0.0,
        "currency":     currency,
    }


# ─────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s", "level":"%(levelname)s", "name":"%(name)s", "message":"%(message)s"}',
)
logger = logging.getLogger("kushki-mcp")

# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────
KUSHKI_ENVIRONMENT: str = os.getenv("KUSHKI_ENVIRONMENT", "sandbox").lower()

BASE_URL = (
    "https://api.kushkipagos.com"
    if KUSHKI_ENVIRONMENT == "production"
    else "https://api-uat.kushkipagos.com"
)
HTTP_TIMEOUT = 30.0

# ─────────────────────────────────────────────────────────────────────
# MCP Server
# ─────────────────────────────────────────────────────────────────────
mcp = FastMCP(
    "Kushki",
    host="0.0.0.0",
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
    ))


# ─────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────

def _build_headers(auth_type: str = "private") -> dict[str, str]:
    """Build auth headers using the appropriate Merchant-Id key."""
    resolved_public = os.getenv("KUSHKI_PUBLIC_KEY", "")
    resolved_private = os.getenv("KUSHKI_PRIVATE_KEY", "")

    if not resolved_public or not resolved_private:
        raise RuntimeError(
            "Both KUSHKI_PUBLIC_KEY and KUSHKI_PRIVATE_KEY environment variables are required."
        )
    headers = {"Content-Type": "application/json"}
    if auth_type == "public":
        headers["Public-Merchant-Id"] = resolved_public
    else:
        headers["Private-Merchant-Id"] = resolved_private
    return headers


async def _kushki_request(
    method: str,
    path: str,
    *,    auth_type: str = "private",
    json_body: dict | None = None) -> dict:
    """Execute an HTTP request against the Kushki API with centralized error handling."""
    url = f"{BASE_URL}{path}"
    logger.info("→ %s %s [%s key]", method.upper(), url, auth_type)

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            headers = _build_headers(auth_type)
            if method.upper() in ["GET", "DELETE"] and not json_body:
                response = await client.request(method, url, headers=headers)
            else:
                response = await client.request(
                    method, url, headers=headers, json=json_body
                )
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Cannot connect to Kushki API ({url}). "
            f"Check network connectivity. Detail: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"Timeout connecting to Kushki API ({url}). "
            f"Request exceeded {HTTP_TIMEOUT}s. Detail: {exc}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Unexpected HTTP error contacting Kushki API: {exc}"
        ) from exc

    if response.status_code >= 400:
        try:
            error_body = response.json()
        except Exception:
            error_body = response.text

        status = response.status_code
        detail = (
            f"Error in Kushki ({status}) calling {path}. "
            f"Response: {json.dumps(error_body, ensure_ascii=False) if isinstance(error_body, dict) else error_body}"
        )
        logger.error("← %s %s → %d: %s", method.upper(), url, status, detail)
        raise RuntimeError(detail)

    try:
        data = response.json()
    except Exception:
        data = {"status_code": response.status_code, "text": response.text}

    logger.info("← %s %s → %d OK", method.upper(), url, response.status_code)
    return data


# ─────────────────────────────────────────────────────────────────────
# MCP Tools
# ─────────────────────────────────────────────────────────────────────


@mcp.tool()
async def create_card_token(    card: dict,
    totalAmount: float,
    currency: str = "USD") -> dict:
    """Tokenize a credit or debit card to prepare for a charge — POST /card/v1/tokens.

    Use this tool as the FIRST step in the card payment flow.
    It uses the PUBLIC key. The returned token is single-use and must be
    consumed immediately with create_card_charge.

    REQUIRED PARAMETERS:
      card (dict): Card data object with these exact fields:
                   {
                     "name": "JOHN DOE",          # Cardholder name as printed on card
                     "number": "4111111111111111", # Card number, no spaces
                     "expiryMonth": "12",          # Expiry month, 2 digits
                     "expiryYear": "28",           # Expiry year, 2 digits
                     "cvv": "123"                  # Card security code
                   }
      totalAmount (float): Total amount to charge. Example: 11.50

    OPTIONAL PARAMETERS:
      currency (str, default="USD"): Currency code.

    RETURNS:
      {"token": str, ...}  — single-use token to pass to create_card_charge.

    EXAMPLE CALL:
      create_card_token(
          card={"name": "JOHN DOE", "number": "4111111111111111",
                "expiryMonth": "12", "expiryYear": "28", "cvv": "123"},
          totalAmount=11.50
      )
    """
    payload = {
        "card": card,
        "totalAmount": totalAmount,
        "currency": currency,
    }
    return await _kushki_request(
        "POST", "/card/v1/tokens",
        auth_type="public", json_body=payload
    )


@mcp.tool()
async def create_card_charge(
    token: str,
    monto: float,
    tipo_monto: TipoMonto = TipoMonto.SUBTOTAL,
    currency: str = "USD",
    fullResponse: bool = True) -> dict:
    """⚠️ MUTATION — Process a card charge using a token — POST /card/v1/charges.

    Use this tool as the SECOND step in the card payment flow, after
    create_card_token. Uses the PRIVATE key.

    MONETARY INPUT (agent MUST follow this contract):
      monto (float): The EXACT amount the user stated — pass it verbatim, no rounding.
      tipo_monto (enum):
        · "subtotal"      → monto is the taxable base WITHOUT IVA (default).
        · "total_con_iva" → monto is the final price ALREADY INCLUDING IVA.

    ⚠️ DO NOT build the amount dict or calculate subtotalIva/iva yourself.
       The server builds {subtotalIva, subtotalIva0, iva, ice, currency} internally.

    REQUIRED PARAMETERS:
      token (str): Single-use token returned by create_card_token.
      monto (float): Amount exactly as stated by the user. Example: 30.0

    OPTIONAL PARAMETERS:
      tipo_monto (str, default="subtotal"): "subtotal" | "total_con_iva".
      currency (str, default="USD"): Currency code.
      fullResponse (bool, default=True): If True, returns complete transaction details.

    RETURNS:
      {"ticketNumber": str, "status": str, "authorizationCode": str,
       "cardType": str, "cardBrand": str, "cardMasked": str}

    EXAMPLE CALLS:
      create_card_charge(token="kjsdfh87324...", monto=30.0, tipo_monto="subtotal")
      create_card_charge(token="kjsdfh87324...", monto=34.50, tipo_monto="total_con_iva")
    """
    amount_dict = _calcular_monto_kushki(monto, tipo_monto, currency)
    logger.info(
        "[create_card_charge] monto=%.2f tipo=%s → subtotalIva=%.2f iva=%.2f",
        monto, tipo_monto.value, amount_dict["subtotalIva"], amount_dict["iva"],
    )
    payload = {
        "token": token,
        "amount": amount_dict,
        "fullResponse": fullResponse,
    }
    return await _kushki_request(
        "POST", "/card/v1/charges",
        auth_type="private", json_body=payload
    )


@mcp.tool()
async def void_or_refund_charge(    ticketNumber: str,
    amount: Optional[dict] = None) -> dict:
    """⚠️ MUTATION — Void or refund a card charge — DELETE /card/v1/charges/{ticketNumber}.

    Use this tool to cancel (void) a charge or issue a refund to a customer.
    Uses the PRIVATE key.

    REQUIRED PARAMETERS:
      ticketNumber (str): The ticket number returned by create_card_charge.
                          Example: "200000000351"

    OPTIONAL PARAMETERS:
      amount (dict): Amount object for a PARTIAL refund. If omitted, the FULL
                     amount is voided/refunded.
                     Schema: {subtotalIva, subtotalIva0, iva, ice, currency}

    RETURNS:
      {"status": str, "message": str}  — confirmation of the void/refund.

    EXAMPLE CALLS:
      void_or_refund_charge(ticketNumber="200000000351")  # Full void
      void_or_refund_charge(ticketNumber="200000000351",
                            amount={"subtotalIva": 5.00, ...})  # Partial refund
    """
    payload = {"amount": amount} if amount else None
    return await _kushki_request(
        "DELETE",
        f"/card/v1/charges/{ticketNumber}",
        auth_type="private", json_body=payload)


@mcp.tool()
async def create_cash_token(    name: str,
    lastName: str,
    identification: str,
    email: str,
    totalAmount: float,
    currency: str = "USD") -> dict:
    """Tokenize a cash payment to prepare it for collection — POST /cash/v1/tokens.

    Use this tool as the FIRST step for cash payments (efectivo).
    Uses the PUBLIC key. The token is then used with create_cash_charge
    to generate a reference code the customer pays at a physical agent.

    REQUIRED PARAMETERS:
      name (str): Customer first name. Example: "Juan"
      lastName (str): Customer last name. Example: "Pérez"
      identification (str): Customer cedula or RUC. Example: "0912345678"
      email (str): Customer email for confirmation. Example: "juan@example.com"
      totalAmount (float): Total amount to collect. Example: 25.00

    OPTIONAL PARAMETERS:
      currency (str, default="USD"): Currency code.

    RETURNS:
      {"token": str, ...}  — cash token to use in create_cash_charge.

    EXAMPLE CALL:
      create_cash_token(
          name="Juan", lastName="Pérez", identification="0912345678",
          email="juan@example.com", totalAmount=25.00
      )
    """
    payload = {
        "name": name,
        "lastName": lastName,
        "identification": identification,
        "email": email,
        "totalAmount": totalAmount,
        "currency": currency,
    }
    return await _kushki_request(
        "POST", "/cash/v1/tokens",
        auth_type="public", json_body=payload
    )


@mcp.tool()
async def create_cash_charge(
    token: str,
    monto: float,
    tipo_monto: TipoMonto = TipoMonto.SUBTOTAL,
    currency: str = "USD",
    fullResponse: bool = True) -> dict:
    """⚠️ MUTATION — Generate a cash payment reference code — POST /cash/v1/charges.

    Use this tool as the SECOND step for cash payments, after create_cash_token.
    Creates a PIN or barcode the customer uses to pay at a physical agent (e.g. bank).
    Uses the PRIVATE key.

    MONETARY INPUT (agent MUST follow this contract):
      monto (float): The EXACT amount the user stated — pass it verbatim, no rounding.
      tipo_monto (enum):
        · "subtotal"      → monto is the taxable base WITHOUT IVA (default).
        · "total_con_iva" → monto is the final price ALREADY INCLUDING IVA.

    ⚠️ DO NOT build the amount dict or calculate subtotalIva/iva yourself.
       The server builds {subtotalIva, subtotalIva0, iva, ice, currency} internally.

    REQUIRED PARAMETERS:
      token (str): Cash token returned by create_cash_token.
      monto (float): Amount exactly as stated by the user. Example: 25.0

    OPTIONAL PARAMETERS:
      tipo_monto (str, default="subtotal"): "subtotal" | "total_con_iva".
      currency (str, default="USD"): Currency code.
      fullResponse (bool, default=True): If True, returns complete charge details.

    RETURNS:
      {"pincashCode": str, "expirationDate": str, "ticketNumber": str}

    EXAMPLE CALLS:
      create_cash_charge(token="abc123token", monto=25.0, tipo_monto="subtotal")
      create_cash_charge(token="abc123token", monto=28.75, tipo_monto="total_con_iva")
    """
    amount_dict = _calcular_monto_kushki(monto, tipo_monto, currency)
    logger.info(
        "[create_cash_charge] monto=%.2f tipo=%s → subtotalIva=%.2f iva=%.2f",
        monto, tipo_monto.value, amount_dict["subtotalIva"], amount_dict["iva"],
    )
    payload = {
        "token": token,
        "amount": amount_dict,
        "fullResponse": fullResponse,
    }
    return await _kushki_request(
        "POST", "/cash/v1/charges",
        auth_type="private", json_body=payload
    )


@mcp.tool()
async def create_transfer_token(    bankId: str,
    userType: str,
    documentType: str,
    documentNumber: str,
    paymentDescription: str,
    amount: dict,
    currency: str = "USD") -> dict:
    """Tokenize a bank transfer payment — POST /transfer/v1/tokens.

    Use this tool as the FIRST step for bank transfer payments (PSE-style).
    Uses the PUBLIC key. The resulting token is used with init_transfer.

    REQUIRED PARAMETERS:
      bankId (str): Bank code for the transfer destination. Example: "1022"
      userType (str): Customer type. "0"=Natural person, "1"=Legal entity.
      documentType (str): ID document type. Example: "CC", "NIT", "CE"
      documentNumber (str): Customer ID number. Example: "0912345678"
      paymentDescription (str): Payment description shown to the customer.
      amount (dict): Amount details with amountDetails sub-object:
                     {"amountDetails": {
                       "subtotalIva": 0,      # ⚠️ TAXABLE BASE. NOT Total.
                       "subtotalIva0": 100,   # ⚠️ ZERO-RATE BASE.
                       "iva": 0, "ice": 0, "currency": "USD"
                     }}

    OPTIONAL PARAMETERS:
      currency (str, default="USD"): Currency code.

    RETURNS:
      {"token": str, ...}  — transfer token to use in init_transfer.

    EXAMPLE CALL:
      create_transfer_token(
          bankId="1022", userType="0", documentType="CC",
          documentNumber="0912345678", paymentDescription="Invoice payment",
          amount={"amountDetails": {"subtotalIva": 0, "subtotalIva0": 100, "iva": 0, "ice": 0}}
      )
    """
    payload = {
        "bankId": bankId,
        "userType": userType,
        "documentType": documentType,
        "documentNumber": documentNumber,
        "paymentDescription": paymentDescription,
        "amount": amount,
        "currency": currency,
    }
    return await _kushki_request(
        "POST", "/transfer/v1/tokens",
        auth_type="public", json_body=payload
    )


@mcp.tool()
async def init_transfer(    token: str,
    amount: dict,
    fullResponse: bool = True) -> dict:
    """⚠️ MUTATION — Initiate a bank transfer and get the redirect URL — POST /transfer/v1/init.

    Use this tool after create_transfer_token to start the actual bank transfer.
    Returns a URL to redirect the customer to their bank's authentication page.
    Uses the PRIVATE key.

    REQUIRED PARAMETERS:
      token (str): Transfer token returned by create_transfer_token.
      amount (dict): Amount breakdown:
                     {
                       "subtotalIva": 0.00,   # ⚠️ TAXABLE BASE. NOT Total.
                       "subtotalIva0": 100.0, # ⚠️ ZERO-RATE BASE.
                       "iva": 0, "ice": 0, "currency": "USD"
                     }

    OPTIONAL PARAMETERS:
      fullResponse (bool, default=True): If True, returns full transaction details.

    RETURNS:
      {"redirectUrl": str, "ticketNumber": str}
      Send the customer to redirectUrl to authenticate with their bank.

    EXAMPLE CALL:
      init_transfer(
          token="transferToken123",
          amount={"subtotalIva": 0, "subtotalIva0": 100.00, "iva": 0, "ice": 0, "currency": "USD"}
      )
    """
    payload = {
        "token": token,
        "amount": amount,
        "fullResponse": fullResponse,
    }
    return await _kushki_request(
        "POST", "/transfer/v1/init",
        auth_type="private", json_body=payload
    )


@mcp.tool()
async def create_subscription(    token: str,
    planName: str,
    periodicity: str,
    amount: dict,
    startDate: str,
    contactDetails: Optional[dict] = None) -> dict:
    """⚠️ MUTATION — Create a recurring card subscription — POST /subscriptions/v1/card.

    Use this tool to enroll a card token into a recurring billing plan.
    The card will be automatically charged based on the periodicity.
    Uses the PRIVATE key.

    REQUIRED PARAMETERS:
      token (str): Card token from create_card_token.
      planName (str): Name of the subscription plan. Example: "Monthly Premium"
      periodicity (str): Billing frequency. "monthly" | "yearly" | "weekly"
      amount (dict): Amount breakdown:
                     {
                       "subtotalIva": 10,     # ⚠️ TAXABLE BASE. NOT Total.
                       "subtotalIva0": 0,     # ⚠️ ZERO-RATE BASE.
                       "iva": 1.50, "ice": 0, "currency": "USD"
                     }
      startDate (str): First billing date in YYYY-MM-DD format. Example: "2025-02-01"

    OPTIONAL PARAMETERS:
      contactDetails (dict): Customer contact info: {email, firstName, lastName}

    RETURNS:
      {"subscriptionId": str, "nextBillingDate": str}

    EXAMPLE CALL:
      create_subscription(
          token="cardToken123", planName="Monthly Premium", periodicity="monthly",
          amount={"subtotalIva": 10, "subtotalIva0": 0, "iva": 1.50, "ice": 0, "currency": "USD"},
          startDate="2025-02-01"
      )
    """
    payload = {
        "token": token,
        "planName": planName,
        "periodicity": periodicity,
        "amount": amount,
        "startDate": startDate,
    }
    if contactDetails:
        payload["contactDetails"] = contactDetails
    return await _kushki_request(
        "POST", "/subscriptions/v1/card",
        auth_type="private", json_body=payload
    )


@mcp.tool()
async def get_charge_status(    ticketNumber: str) -> dict:
    """Check the current status of any Kushki transaction — GET /v1/charges/{ticketNumber}.

    Use this tool to verify whether a charge is approved, declined, or pending.
    Uses the PRIVATE key.

    REQUIRED PARAMETERS:
      ticketNumber (str): Ticket number returned by create_card_charge,
                          create_cash_charge, or init_transfer.
                          Example: "200000000351"

    RETURNS:
      {"approved": bool, "authorizationCode": str, "amount": float,
       "cardBrand": str, "cardMasked": str, "responseText": str}

    EXAMPLE CALL:
      get_charge_status(ticketNumber="200000000351")
    """
    return await _kushki_request(
        "GET", f"/v1/charges/{ticketNumber}",
        auth_type="private"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("MCP_PORT", 8000))
    transport_mode = os.getenv("MCP_TRANSPORT_MODE", "sse").lower()
    print(f"Starting Kushki MCP Server on http://0.0.0.0:{port}/mcp ({transport_mode})")
    if transport_mode == "sse":
        app = mcp.sse_app()
    elif transport_mode == "http_stream":
        app = mcp.streamable_http_app()
    else:
        raise ValueError(f"Unknown transport mode: {transport_mode}")
    uvicorn.run(app, host="0.0.0.0", port=port)
