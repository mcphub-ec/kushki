# **Documentación API Kushki para Servidor MCP**

Esta documentación técnica detalla el funcionamiento de la API REST de Kushki Pagos, optimizada para la creación de un servidor Model Context Protocol (MCP).

## **1\. Entornos y URLs Base**

* **Producción:** https://api.kushkipagos.com  
* **Sandbox (Pruebas / UAT):** https://api-uat.kushkipagos.com

## **2\. Autenticación (¡Muy Importante\!)**

Kushki utiliza un sistema de **doble llave** mediante Headers. El agente MCP debe entender qué llave usar dependiendo del endpoint:

1. **Public Key (Public-Merchant-Id):** Se usa EXCLUSIVAMENTE para tokenizar tarjetas (convertir el número de tarjeta en un token seguro). Nunca debe usarse para procesar dinero.  
2. **Private Key (Private-Merchant-Id):** Se usa para realizar cargos, consultar transacciones, emitir reembolsos o anulaciones. Nunca debe exponerse en el frontend.

**Headers Obligatorios:**

Content-Type: application/json  
Public-Merchant-Id: \<TU\_LLAVE\_PUBLICA\>   \# (Solo para /card/v1/tokens)  
Private-Merchant-Id: \<TU\_LLAVE\_PRIVADA\>  \# (Para /card/v1/charges y reversos)

## **3\. Flujo Principal de Pagos (Tarjeta de Crédito/Débito)**

El pago con Kushki es un proceso estricto de dos pasos:

### **Paso 1: Tokenizar la Tarjeta (POST /card/v1/tokens)**

* **Propósito:** Envía los datos sensibles de la tarjeta (PAN, CVV, Expiración) para obtener un token alfanumérico temporal.  
* **Autenticación:** Public-Merchant-Id  
* **Respuesta Exitosa:** Devuelve un token válido por 15 minutos.

### **Paso 2: Procesar el Cargo (POST /card/v1/charges)**

* **Propósito:** Usa el token obtenido en el paso 1 junto con el detalle del monto para debitar los fondos de la cuenta del cliente.  
* **Autenticación:** Private-Merchant-Id  
* **Estructura de Montos:** Kushki NO usa un solo número entero. Exige un objeto amount que desglosa la compra. Para Ecuador, la suma matemática debe cuadrar exactamente:  
  * subtotalIva: Monto que SÍ grava IVA.  
  * subtotalIva0: Monto que NO grava IVA.  
  * iva: El valor calculado del impuesto.  
  * ice: Impuesto a Consumos Especiales (si aplica, usualmente 0).  
* **Respuesta Exitosa:** Devuelve un ticketNumber (Recibo) y el detalle de la aprobación.

## **4\. Anulaciones y Reembolsos (DELETE /card/v1/charges/{ticketNumber})**

* **Propósito:** Permite anular (void) o reembolsar (refund) una transacción aprobada previamente.  
* **Autenticación:** Private-Merchant-Id  
* **Parámetro en Ruta:** El ticketNumber devuelto cuando se hizo el cargo.  
* **Body (Opcional):** Si se envía un objeto amount, se realizará un reembolso parcial. Si se envía vacío, se intentará anular/reembolsar el 100% de la transacción.

## **5\. Códigos de Respuesta**

* **201 Created:** Transacción/Token creado y aprobado exitosamente.  
* **400 Bad Request:** Error de validación (ej. tarjeta expirada, datos mal formateados).  
* **401 Unauthorized:** Faltan llaves de acceso o son incorrectas.  
* **402 Payment Required:** Fondos insuficientes o transacción rechazada por el banco emisor.