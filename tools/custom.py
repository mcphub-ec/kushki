"""
Kushki — all 9 tools as explicit @mcp.tool() functions.

Kushki uses dual-key auth (public/private), raises RuntimeError on errors,
and requires fiscal pre-processing for charge tools. All tools live here.
"""

from __future__ import annotations

from typing import Any, Optional

from mcp_common.security import validate_amount

import server
from _fiscal import TipoMonto, calcular_monto_kushki
from app import mcp


@mcp.tool()
async def create_card_token(card: dict, totalAmount: float, currency: str = "USD") -> dict:
    """Tokenize a credit or debit card to prepare for a charge — POST /card/v1/tokens.

    REQUIRED PARAMETERS:
      card (dict): {"name": "JOHN DOE", "number": "4111111111111111",
                    "expiryMonth": "12", "expiryYear": "28", "cvv": "123"}
      totalAmount (float): Total amount to charge.

    RETURNS:
      {"token": str, ...}  — single-use token to pass to create_card_charge.
    """
    return await server._kushki_request(
        "POST", "/card/v1/tokens", auth_type="public",
        json_body={"card": card, "totalAmount": totalAmount, "currency": currency},
    )


@mcp.tool()
async def create_card_charge(
    token: str,
    monto: float,
    tipo_monto: TipoMonto = TipoMonto.SUBTOTAL,
    currency: str = "USD",
    fullResponse: bool = True,
) -> dict:
    """⚠️ MUTATION — Process a card charge using a token — POST /card/v1/charges.

    REQUIRED PARAMETERS:
      token (str): Single-use token returned by create_card_token.
      monto (float): Amount exactly as stated by the user.

    RETURNS:
      {"ticketNumber": str, "status": str, "authorizationCode": str, ...}
    """
    amount_dict = calcular_monto_kushki(monto, tipo_monto, currency)
    validate_amount(monto, "monto")
    server.logger.info("[create_card_charge] monto=%.2f tipo=%s → subtotalIva=%.2f iva=%.2f",
        monto, tipo_monto.value, amount_dict["subtotalIva"], amount_dict["iva"])
    return await server._kushki_request(
        "POST", "/card/v1/charges", auth_type="private",
        json_body={"token": token, "amount": amount_dict, "fullResponse": fullResponse},
    )


@mcp.tool()
async def void_or_refund_charge(
    ticketNumber: str,
    amount: Optional[dict] = None,
    verify_status: bool = True,
) -> dict:
    """⚠️ MUTATION — Void or refund a card charge — DELETE /card/v1/charges/{ticketNumber}.

    REQUIRED PARAMETERS:
      ticketNumber (str): Ticket number from create_card_charge.

    OPTIONAL PARAMETERS:
      amount (dict): Partial refund amount object. Omit for full void.
      verify_status (bool, default=True): Pre-check charge is approved.

    RETURNS:
      {"status": str, "message": str, "pre_check": dict | None}
    """
    pre_check: dict | None = None
    if verify_status:
        try:
            status_resp = await server._kushki_request("GET", f"/v1/charges/{ticketNumber}", auth_type="private")
            pre_check = {
                "ticketNumber": ticketNumber,
                "approved": status_resp.get("approved"),
                "responseText": status_resp.get("responseText"),
            }
            if not status_resp.get("approved"):
                raise ValueError(
                    f"No se puede anular/reembolsar el cargo {ticketNumber}: "
                    f"estado actual no es aprobado. Pasa verify_status=False para omitir la verificación."
                )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(
                f"No se pudo verificar el estado del cargo {ticketNumber}: {exc}. "
                "Pasa verify_status=False para omitir la verificación."
            ) from exc

    payload = {"amount": amount} if amount else None
    result = await server._kushki_request(
        "DELETE", f"/card/v1/charges/{ticketNumber}", auth_type="private", json_body=payload
    )
    if pre_check is not None:
        result["pre_check"] = pre_check
    return result


@mcp.tool()
async def create_cash_token(
    name: str, lastName: str, identification: str,
    email: str, totalAmount: float, currency: str = "USD",
) -> dict:
    """Tokenize a cash payment to prepare it for collection — POST /cash/v1/tokens.

    REQUIRED PARAMETERS:
      name, lastName, identification, email, totalAmount.

    RETURNS:
      {"token": str, ...}  — cash token to use in create_cash_charge.
    """
    return await server._kushki_request(
        "POST", "/cash/v1/tokens", auth_type="public",
        json_body={"name": name, "lastName": lastName, "identification": identification,
                   "email": email, "totalAmount": totalAmount, "currency": currency},
    )


@mcp.tool()
async def create_cash_charge(
    token: str,
    monto: float,
    tipo_monto: TipoMonto = TipoMonto.SUBTOTAL,
    currency: str = "USD",
    fullResponse: bool = True,
) -> dict:
    """⚠️ MUTATION — Generate a cash payment reference code — POST /cash/v1/charges.

    REQUIRED PARAMETERS:
      token (str): Cash token from create_cash_token.
      monto (float): Amount exactly as stated by the user.

    RETURNS:
      {"pincashCode": str, "expirationDate": str, "ticketNumber": str}
    """
    amount_dict = calcular_monto_kushki(monto, tipo_monto, currency)
    validate_amount(monto, "monto")
    server.logger.info("[create_cash_charge] monto=%.2f tipo=%s → subtotalIva=%.2f iva=%.2f",
        monto, tipo_monto.value, amount_dict["subtotalIva"], amount_dict["iva"])
    return await server._kushki_request(
        "POST", "/cash/v1/charges", auth_type="private",
        json_body={"token": token, "amount": amount_dict, "fullResponse": fullResponse},
    )


@mcp.tool()
async def create_transfer_token(
    bankId: str, userType: str, documentType: str,
    documentNumber: str, paymentDescription: str,
    amount: dict, currency: str = "USD",
) -> dict:
    """Tokenize a bank transfer payment — POST /transfer/v1/tokens.

    REQUIRED PARAMETERS:
      bankId, userType ("0"=Natural/"1"=Legal), documentType, documentNumber,
      paymentDescription, amount (dict with amountDetails sub-object).

    RETURNS:
      {"token": str, ...}
    """
    return await server._kushki_request(
        "POST", "/transfer/v1/tokens", auth_type="public",
        json_body={"bankId": bankId, "userType": userType, "documentType": documentType,
                   "documentNumber": documentNumber, "paymentDescription": paymentDescription,
                   "amount": amount, "currency": currency},
    )


@mcp.tool()
async def init_transfer(token: str, amount: dict, fullResponse: bool = True) -> dict:
    """⚠️ MUTATION — Initiate a bank transfer and get the redirect URL — POST /transfer/v1/init.

    REQUIRED PARAMETERS:
      token (str): Transfer token from create_transfer_token.
      amount (dict): {subtotalIva, subtotalIva0, iva, ice, currency}

    RETURNS:
      {"redirectUrl": str, "ticketNumber": str}
    """
    return await server._kushki_request(
        "POST", "/transfer/v1/init", auth_type="private",
        json_body={"token": token, "amount": amount, "fullResponse": fullResponse},
    )


@mcp.tool()
async def create_subscription(
    token: str, planName: str, periodicity: str,
    amount: dict, startDate: str,
    contactDetails: Optional[dict] = None,
) -> dict:
    """⚠️ MUTATION — Create a recurring card subscription — POST /subscriptions/v1/card.

    REQUIRED PARAMETERS:
      token (str): Card token from create_card_token.
      planName (str): Subscription plan name.
      periodicity (str): "monthly" | "yearly" | "weekly"
      amount (dict): {subtotalIva, subtotalIva0, iva, ice, currency}
      startDate (str): First billing date YYYY-MM-DD.

    RETURNS:
      {"subscriptionId": str, "nextBillingDate": str}
    """
    _ALLOWED = ("monthly", "yearly", "weekly")
    if periodicity not in _ALLOWED:
        raise ValueError(f"periodicity debe ser uno de {_ALLOWED}. Recibido: {periodicity!r}")
    payload: dict[str, Any] = {
        "token": token, "planName": planName,
        "periodicity": periodicity, "amount": amount, "startDate": startDate,
    }
    if contactDetails:
        payload["contactDetails"] = contactDetails
    return await server._kushki_request("POST", "/subscriptions/v1/card", auth_type="private", json_body=payload)


@mcp.tool()
async def get_charge_status(ticketNumber: str) -> dict:
    """Check the current status of any Kushki transaction — GET /v1/charges/{ticketNumber}.

    REQUIRED PARAMETERS:
      ticketNumber (str): Ticket number from any charge tool.

    RETURNS:
      {"approved": bool, "authorizationCode": str, "responseText": str, ...}
    """
    return await server._kushki_request("GET", f"/v1/charges/{ticketNumber}", auth_type="private")
