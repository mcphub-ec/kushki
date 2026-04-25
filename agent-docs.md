# Integración Kushki MCP - Guía para el Agente

Este servidor MCP proporciona acceso a la API de Kushki Pagos. Permite realizar tokens de tarjetas, cargos directos (débitos), anulaciones, reembolsos, y manejo de pagos con efectivo o transferencias bancarias.

**Transporte:** Streamable HTTP en `http://localhost:8006/mcp`
**Autenticación API:** Oculta en el servidor (Usa _Public-Merchant-Id_ y _Private-Merchant-Id_ automáticamente dependiendo de la operación).

## Flujo de Pagos (Dos Pasos)

Kushki exige un proceso estricto de **dos pasos** para pagos con tarjeta, efectivo o transferencia:
1. **Tokenización (Llave Pública):** Genera un token temporal con los datos sensibles.
2. **Cargo / Init (Llave Privada):** Ejecuta la transacción usando el token.

*Nota:* No intentes enviar datos de tarjeta o efectivo directamente al endpoint de cargo. Siempre debes obtener el token primero.

## Objeto `amount` (Requerido para la mayoría de los endpoints)

Kushki exige un objeto detallado para el desglose de los montos sumados, no un valor único. **Asegúrate de que la suma matemática sea exacta**. Para Ecuador (USD), se usa el siguiente formato:

```json
{
  "subtotalIva": 0.0,
  "subtotalIva0": 10.00,
  "iva": 0.0,
  "ice": 0.0,
  "currency": "USD"
}
```

## Herramientas Disponibles

### 1. Pagos con Tarjeta (Crédito/Débito)
- **`create_card_token(card: dict, totalAmount: float, currency: str)`**:
  - Parámetro `card` requiere: `{ "name": "...", "number": "16_digitos", "expiryMonth": "MM", "expiryYear": "YY", "cvv": "123" }`.
  - Retorna un `token` (String) válido por 15 min.
- **`create_card_charge(token: str, amount: dict, fullResponse: bool)`**:
  - Utiliza el token creado anteriormente y el objeto `amount` para realizar el cobro.
  - Retorna el `ticketNumber` (recibo) tras un cargo exitoso.

### 2. Anulaciones y Reembolsos
- **`void_or_refund_charge(ticketNumber: str, amount: dict | null)`**:
  - Permite anular o reembolsar un cargo exitoso usando su `ticketNumber`.
  - Omitir `amount` para anular/reembolsar el total, o pasar `amount` para un reembolso parcial.

### 3. Pagos en Efectivo
- **`create_cash_token(name: str, lastName: str, identification: str, email: str, totalAmount: float)`**:
  - Retorna un `token`. `identification` suele ser Cédula o RUC.
- **`create_cash_charge(token: str, amount: dict)`**:
  - Genera un código PIN de pago. Retorna un `ticketNumber`, `pin` y `pdfUrl`.

### 4. Pagos por Transferencia (PSE)
- **`create_transfer_token(bankId: str, userType: str, documentType: str, documentNumber: str, paymentDescription: str, amount: dict)`**:
  - `userType`: "0" (Persona) o "1" (Empresa).
  - Retorna el `token`.
- **`init_transfer(token: str, amount: dict)`**:
  - Retorna la URL de redirección en `redirectUrl` para que el cliente la visite.

### 5. Suscripciones
- **`create_subscription(token: str, planName: str, periodicity: str, amount: dict, startDate: str, contactDetails: dict)`**:
  - `periodicity`: "monthly", "yearly", o "weekly".
  - Retorna el `subscriptionId`.

### 6. Consultas de Estado
- **`get_charge_status(ticketNumber: str)`**:
  - Retorna el detalle de una transacción (estado, etc).

## Manejo de Errores

Si la API rechaza el pago (ej. 402 Fondos insuficientes, 401 Problema de autenticación), el servidor MCP lanzará un error detallando el cuerpo de la respuesta en JSON. Debes informar al usuario de forma clara cuando una transacción sea declinada por la integradora u originador.
