# Contrato de la API (para el backend que construiremos)

La interfaz ya sabe hablar con tu backend: elige **Conexión → Mi backend (API)** (o `python main.py --modo api`) y
escribe su dirección (`MKT_API_URL`, por defecto `http://localhost:8000`). Todo lo que sigue es lo que
`app/gateways/api.py` envía y espera. Si tu backend cumple este contrato, **no hay que tocar la interfaz**.

> **Especificación ejecutable.** `tests/fake_api.py` es un servidor HTTP *falso* que cumple este contrato
> (rutas, códigos de estado y formas JSON). `tests/test_contrato.py` ejecuta **las mismas pruebas** contra el modo
> directo y contra ese servidor falso. Cuando tengas el backend real, el camino más rápido es convertir esa
> misma suite en pruebas de tu API: si pasan, la interfaz funcionará.
>
> **Referencia de la lógica de negocio.** `app/gateways/directo.py` (`GatewayDirecto`) contiene todas las reglas
> (validaciones, permisos, checkout, estados del pedido). Tu backend puede **reutilizar** `app/catalogo/`,
> `app/relacional/` y `GatewayDirecto` casi tal cual y envolverlos con rutas HTTP — es justo lo que hace
> `fake_api.py` en ~100 líneas.

## 1. Convenciones

| Tema | Regla |
|---|---|
| Formato | JSON (`Content-Type: application/json`), UTF-8. Los nombres de campos van en español y son **exactamente** los de las 10 tablas. |
| Dinero | **Texto decimal**: `"1234.50"`. Nunca `float`. |
| Fechas | ISO-8601 en UTC: `"2026-03-14T18:30:00+00:00"` (también se acepta `Z`). |
| Ids | `id_producto`, `id_variante`, `id_categoria`, `id_resena`: **texto**. `id_usuario`, `id_pedido`, `id_pago`, `id_carrito`, `id_detalle_*`: **entero**. |
| Autenticación | `POST /auth/login` devuelve un `token`; todas las demás rutas (salvo las públicas) lo reciben en `Authorization: Bearer <token>`. Rutas públicas: `/auth/login`, `/auth/registro`, `/salud`. Un token ausente, inválido o vencido → **401**. |
| Paginación | Listas largas: `GET …?limite=N&cursor=C` → `{"items": [...], "siguiente": "<cursor opaco>" \| null}`. El cliente nunca interpreta el cursor; solo lo devuelve tal cual. `siguiente = null` significa «no hay más». Nunca devuelvas «total de páginas» ni uses `OFFSET` (con 17,000+ productos es lento y poco fiable). |
| Campos extra | Se ignoran. Campos ausentes toman el valor por defecto del modelo (`app/models.py`). Puedes ir añadiendo cosas sin romper la interfaz. |
| `204 No Content` | Permitido para `POST /auth/logout`. |
| CORS / TLS | La interfaz de escritorio no necesita CORS. En producción usa **HTTPS** siempre. |

## 2. Errores

Cualquier respuesta con estado ≥ 400 debe llevar este cuerpo:

```json
{ "codigo": "stock_insuficiente",
  "mensaje": "Revisa tu carrito antes de pagar.",
  "detalles": ["«Playera» (SKU-12): solo quedan 1, pediste 3."],
  "ids_afectados": ["a1b2c3…"] }
```

* `mensaje` se muestra **tal cual** al usuario → en español y comprensible (no trazas de Python).
* `detalles` (lista de textos) es opcional; la interfaz los muestra como viñetas.
* `ids_afectados` solo para `stock_insuficiente` (ids de variante).

| `codigo` | HTTP sugerido | Cuándo |
|---|---|---|
| `autenticacion` | 401 | Credenciales malas, cuenta suspendida, token vencido. **La interfaz cierra la sesión y vuelve al login.** |
| `permiso` | 403 | El rol no puede hacer esto (p. ej. un comprador llama a `/admin/…`). |
| `no_encontrado` | 404 | El producto/pedido/usuario no existe (o no es visible para ese usuario). |
| `validacion` | 422 (o 400) | Datos incorrectos: correo mal escrito, calificación fuera de 1–5, SKU repetido en el mismo producto… |
| `conflicto` | 409 | Correo ya registrado, SKU ya usado por otro producto, ya reseñaste este producto, transición de estatus no permitida, el pedido cambió mientras lo editabas. |
| `stock_insuficiente` | 409 | Checkout con productos sin existencias / no disponibles. |
| `pago` | 402 | El cobro fue rechazado. |
| `conexion` | 503 | Una base de datos o un servicio externo no responde. |

Si no llega `codigo`, la interfaz deduce el tipo por el estado HTTP (401/403/404/409/400/422); cualquier otro
(500, 502…) se muestra como «problema del servidor».

## 3. Rutas

`R` = rol requerido. «cualquiera» = cualquier usuario con sesión.

### Autenticación

| Método y ruta | R | Cuerpo → Respuesta |
|---|---|---|
| `POST /auth/login` | pública | `{"correo","password"}` → `{"token":"…","usuario":Usuario}` |
| `POST /auth/registro` | pública | `{"correo","password","nombre","apellido","telefono"?,"rol"?}` → igual que login. `rol` solo `COMPRADOR` (por defecto) o `VENDEDOR`. |
| `POST /auth/logout` | cualquiera | — → `204` (el backend invalida el token) |

Reglas: correo en minúsculas y único; contraseña ≥ 8 caracteres con letras y números y ≤ 72 bytes (límite de
bcrypt); guardar **solo el hash** (bcrypt/argon2); el mensaje de login fallido es el mismo exista o no el correo
(«Correo o contraseña incorrectos.») para no revelar qué correos están registrados; cuentas `SUSPENDIDO` no entran.

### Catálogo (cualquiera)

| Método y ruta | Parámetros / cuerpo | Respuesta |
|---|---|---|
| `GET /categorias` | — | `{"items":[Categoria,…]}` (lista plana; la interfaz arma el árbol con `id_categoria_padre`) |
| `GET /productos` | `q`, `id_categoria`, `en_cualquier_parte` (`"true"`), `limite` (1–100, def. 24), `cursor` | `Pagina<ProductoResumen>`. Solo productos `ACTIVO`. |
| `GET /productos/{id}` | — | `Producto` (con `variantes`, `ruta_categoria`, `nombre_vendedor`). Un producto `INACTIVO` solo lo ve su dueño o un administrador (404 para los demás); a los demás solo se les devuelven variantes `ACTIVO`. |
| `GET /productos/{id}/resenas` | `limite` (def. 10), `cursor` | `Pagina<Resena>`, más recientes primero |
| `GET /productos/{id}/elegibilidad-resena` | — | `{"puede": bool, "motivo": "…"}` |
| `POST /productos/{id}/resenas` | `{"calificacion":1-5,"comentario":"≤1000"}` | `Resena` (403 si no es elegible) |

Semántica de búsqueda: `q` sin `en_cualquier_parte` es **por prefijo del título** (rápida, usa índice);
con `en_cualquier_parte=true` es «contiene» (más lenta; en DynamoDB es un Scan acotado). `id_categoria` incluye
todas las subcategorías. Si llevas la búsqueda a OpenSearch/Elasticsearch/MySQL FULLTEXT, respeta los mismos parámetros.

Elegibilidad para reseñar: no administradores; no el dueño del producto; una sola reseña por usuario y producto;
y solo quien tiene un pedido `ENTREGADO` que incluya una variante de ese producto.

### Carrito (COMPRADOR o VENDEDOR)

Todas devuelven el `Carrito` completo y actualizado.

| Método y ruta | Cuerpo |
|---|---|
| `GET /carrito` | — |
| `POST /carrito/lineas` | `{"id_variante","cantidad":1-99}` — si la variante ya está, suma cantidades. No se puede comprar un producto propio. |
| `PATCH /carrito/lineas/{id_detalle_carrito}` | `{"cantidad":1-99}` |
| `DELETE /carrito/lineas/{id_detalle_carrito}` | — |

Cada `LineaCarrito` trae los datos del catálogo ya mezclados (`titulo`, `sku`, `atributos`, `precio_unitario`,
`stock_disponible`, `disponible`) porque `detalle_carrito` vive en MySQL y el producto en DynamoDB: **no hay JOIN
entre bases**, el backend los une. Siempre se muestra el precio **actual** del catálogo.

### Compra y pedidos

| Método y ruta | R | Cuerpo → Respuesta |
|---|---|---|
| `POST /checkout` | COMPRADOR/VENDEDOR | `{"direccion_envio":"≥10 caracteres","metodo_pago":"TARJETA\|TRANSFERENCIA\|PAYPAL\|OXXO"}` → `Pedido` (ya `PAGADO`) |
| `GET /pedidos` | COMPRADOR/VENDEDOR | `limite` (def. 20), `cursor` → `Pagina<Pedido>` (los míos) |
| `GET /pedidos/{id}` | comprador del pedido, vendedor con líneas en él, o ADMIN | `Pedido` con `lineas` y `pagos`. A quien no le corresponde → **404** (no se revela que existe). Un vendedor ve solo *sus* líneas y no ve los pagos. |
| `POST /pedidos/{id}/estatus` | ver abajo | `{"estatus":"…"}` → `Pedido` |

**Checkout — orden recomendado** (implementado en `GatewayDirecto.checkout`):

1. Validar el carrito contra el catálogo (precio y existencias *actuales*). Si algo falla → `stock_insuficiente` con `detalles`.
2. **Reservar existencias de forma atómica** (en DynamoDB: `TransactWriteItems` con condición `cantidad_stock >= n`; todo o nada). Si otro comprador ganó → `stock_insuficiente` («Alguien se llevó las últimas piezas…»).
3. En una transacción de MySQL: crear `pedidos` (`PENDIENTE`) + `detalle_pedido` (congelando `precio_unitario`, `id_vendedor`) y marcar el carrito `CONVERTIDO`. Si falla → **liberar** las existencias.
4. Cobrar con la pasarela (Stripe, Conekta, Mercado Pago…) y registrar `pagos`. Rechazado → pedido `CANCELADO`, existencias liberadas, `pago`. Aprobado → pedido `PAGADO`.

Como no existe una transacción entre DynamoDB y MySQL, es una *saga* con compensaciones: cada paso que falla
deshace los anteriores. **La interfaz nunca recibe ni envía datos de tarjeta** (PCI-DSS): el cobro con tarjeta
real debe hacerse con la pasarela mediante token / página alojada por ella.

**Máquina de estados del pedido** (`POST /pedidos/{id}/estatus`):

```
PENDIENTE → PAGADO | CANCELADO        PAGADO → ENVIADO | CANCELADO
ENVIADO   → ENTREGADO                 ENTREGADO, CANCELADO → (final)
```

Una transición que no esté en el diagrama → `conflicto`. Quién puede hacerla:

| Quién | Puede |
|---|---|
| ADMIN | cualquier transición válida |
| El comprador del pedido | `PENDIENTE→CANCELADO`, `PAGADO→CANCELADO`, `ENVIADO→ENTREGADO` |
| Un VENDEDOR | `PAGADO→ENVIADO` **solo si todas las líneas del pedido son suyas**. Si el pedido mezcla productos de varios vendedores → `permiso` con un mensaje claro (el esquema guarda **un** estatus por pedido, no por línea; lo decide el administrador). |

Cancelar libera las existencias reservadas. Un cambio con condición («solo si sigue en el estado que yo leí»,
`UPDATE … WHERE estatus = ?`) evita que dos personas cambien el mismo pedido a la vez → `conflicto`.

### Vendedor (R = VENDEDOR)

| Método y ruta | Cuerpo → Respuesta |
|---|---|
| `GET /vendedor/productos` | `limite` (def. 30), `cursor` → `Pagina<ProductoResumen>` (incluye `INACTIVO`) |
| `POST /vendedor/productos` | `DatosProducto` → `Producto` (201 ó 200) |
| `PUT /vendedor/productos/{id}` | `DatosProducto` → `Producto`. El vendedor solo edita lo suyo; ADMIN puede editar cualquiera. |
| `GET /vendedor/ventas` | `limite`, `cursor` → `Pagina<LineaVenta>` (líneas de pedidos que contienen sus productos) |

`DatosProducto`: `{"titulo":3-150,"id_categoria","descripcion":≤4000,"marca":≤80,"estatus":"ACTIVO|INACTIVO","variantes":[DatosVariante,…≥1]}`.
`DatosVariante`: `{"sku","precio":"0.01–10000000","cantidad_stock":≥0,"atributos":{"Talla":"M"},"estatus","id_variante"?}`.
`id_variante` ausente = variante nueva; presente = edición (el SKU de una variante existente **no cambia**).
**El SKU es único en todo el catálogo** (se guarda en mayúsculas) → `conflicto` si ya existe. En DynamoDB se logra con
un ítem «candado» `SKU#<sku>` escrito con `ConditionExpression: attribute_not_exists`.

### Administración (R = ADMIN)

| Método y ruta | Cuerpo → Respuesta |
|---|---|
| `GET /admin/usuarios` | `rol`, `estatus`, `q` (correo/nombre), `limite`, `cursor` → `Pagina<Usuario>` |
| `PATCH /admin/usuarios/{id}` | `{"rol"?,"estatus"?}` → `Usuario`. Un admin no puede quitarse su propio acceso. |
| `POST /admin/categorias` | `Categoria` → `Categoria` |
| `PUT /admin/categorias/{id}` | `Categoria` → `Categoria`. Una categoría no puede colgar de sí misma ni de sus descendientes. |
| `GET /admin/pedidos` | `estatus`, `limite`, `cursor` → `Pagina<Pedido>` |
| `GET /admin/pagos` | `limite`, `cursor` → `Pagina<Pago>` |
| `GET /admin/estadisticas` | → `Estadisticas` |

### Diagnóstico

`GET /salud` (pública) → `{"items":[EstadoConexion,…]}`. La pantalla «Conexiones» y el botón «Probar conexión» lo usan:
una entrada por base de datos (`nombre`, `tipo`, `ok`, `detalle`, `latencia_ms`, `contiene`). Que el endpoint responda
ya significa «el backend está vivo»; los `ok:false` dicen qué base falló.

## 4. Formas JSON

Los ejemplos omiten campos opcionales. La definición completa y los valores por defecto están en `app/models.py`.

```jsonc
// Usuario
{ "id_usuario": 7, "correo": "ana@demo.com", "rol": "COMPRADOR", "nombre": "Ana", "apellido": "Ruiz",
  "telefono": "7771234567", "estatus": "ACTIVO", "fecha_registro": "2026-01-05T16:20:00+00:00" }

// Categoria
{ "id_categoria": "electronica", "nombre": "Electrónica", "slug": "electronica",
  "id_categoria_padre": null, "estatus": "ACTIVO" }

// ProductoResumen  (lo que pinta una tarjeta del catálogo; los campos de precio/calificación van desnormalizados)
{ "id_producto": "f3a9…", "titulo": "Audífonos Bluetooth", "id_categoria": "audio", "id_vendedor": 2,
  "marca": "Sonex", "estatus": "ACTIVO", "fecha_creacion": "2026-02-01T10:00:00+00:00",
  "precio_desde": "499.00", "calificacion_promedio": 4.4, "num_resenas": 31 }

// Producto = ProductoResumen + :
{ "descripcion": "…", "ruta_categoria": ["Electrónica", "Audio"], "nombre_vendedor": "Carlos M.",
  "variantes": [ { "id_variante": "9c1e…", "id_producto": "f3a9…", "sku": "AUD-BT-NEG", "precio": "499.00",
                   "cantidad_stock": 12, "atributos": {"Color": "Negro"}, "estatus": "ACTIVO" } ] }

// Resena
{ "id_resena": "…", "id_producto": "f3a9…", "id_usuario": 7, "calificacion": 5, "comentario": "Excelentes",
  "nombre_usuario": "Ana R.", "fecha_resena": "2026-03-02T12:00:00+00:00" }

// Carrito
{ "id_carrito": 41, "lineas": [ { "id_detalle_carrito": 90, "id_variante": "9c1e…", "cantidad": 2,
    "id_producto": "f3a9…", "titulo": "Audífonos Bluetooth", "sku": "AUD-BT-NEG", "atributos": {"Color":"Negro"},
    "precio_unitario": "499.00", "stock_disponible": 12, "disponible": true } ] }

// Pedido
{ "id_pedido": 1001, "id_comprador": 7, "estatus": "PAGADO", "monto_total": "998.00",
  "direccion_envio": "Calle 5 #12, Col. Centro, Cuernavaca, 62000", "fecha_pedido": "2026-03-10T09:00:00+00:00",
  "nombre_comprador": "Ana Ruiz",
  "lineas": [ { "id_detalle_pedido": 5, "id_pedido": 1001, "id_variante": "9c1e…", "id_vendedor": 2,
                "precio_unitario": "499.00", "cantidad": 2, "subtotal": "998.00",
                "id_producto": "f3a9…", "titulo": "Audífonos Bluetooth", "sku": "AUD-BT-NEG", "atributos": {"Color":"Negro"} } ],
  "pagos":  [ { "id_pago": 33, "id_pedido": 1001, "metodo_pago": "TARJETA", "estatus": "APROBADO",
                "monto": "998.00", "referencia_transaccion": "pi_3Nx…", "fecha_pago": "2026-03-10T09:00:03+00:00" } ] }

// LineaVenta  (fila de «Mis ventas»)
{ "id_detalle_pedido": 5, "id_pedido": 1001, "id_variante": "9c1e…", "precio_unitario": "499.00", "cantidad": 2,
  "subtotal": "998.00", "estatus_pedido": "PAGADO", "fecha_pedido": "2026-03-10T09:00:00+00:00",
  "titulo": "Audífonos Bluetooth", "sku": "AUD-BT-NEG", "atributos": {"Color":"Negro"} }

// Estadisticas
{ "usuarios_por_rol": {"COMPRADOR": 120, "VENDEDOR": 9, "ADMIN": 1},
  "pedidos_por_estatus": {"PAGADO": 40, "ENVIADO": 12, "ENTREGADO": 200, "CANCELADO": 7},
  "ingresos_aprobados": "184500.00", "productos_aprox": 17000 }

// EstadoConexion
{ "nombre": "DynamoDB", "tipo": "NoSQL", "ok": true, "detalle": "us-east-1", "latencia_ms": 21.4,
  "contiene": "productos, categorias, resenas, variantes_producto" }
```

Valores permitidos (constantes en `app/models.py`):
`rol` COMPRADOR · VENDEDOR · ADMIN — `estatus` de usuario ACTIVO · SUSPENDIDO — de producto/variante/categoría ACTIVO · INACTIVO —
de pedido PENDIENTE · PAGADO · ENVIADO · ENTREGADO · CANCELADO — de pago APROBADO · RECHAZADO · REEMBOLSADO —
`metodo_pago` TARJETA · TRANSFERENCIA · PAYPAL · OXXO.

## 5. Comprobación rápida

```bash
# 1) arranca tu backend; luego:
python scripts/probar_conexiones.py --modo api       # GET /salud
python main.py --modo api                            # y entra con una cuenta real
pytest tests/test_contrato.py                        # la especificación ejecutable (corre contra memoria, DynamoDB simulado y la API falsa)
```

## 6. Consejos para el backend (Python)

* **FastAPI + Pydantic** encaja bien: genera `/docs` (OpenAPI) y valida los cuerpos. Mapea las excepciones de
  `app/errors.py` a respuestas con un `exception_handler` (`{"codigo": exc.codigo, "mensaje": exc.mensaje, "detalles": exc.detalles}`).
* **Un `GatewayDirecto` por petición**, no uno global: guarda al usuario de la sesión en su estado interno.
  Crea el contexto con el token → usuario (JWT corto + refresh, o sesiones en Redis/DynamoDB con TTL).
* **No** expongas credenciales de AWS ni de MySQL al cliente: ese es el motivo de existir del backend.
* Pon rate-limit en `/auth/login` y `/auth/registro`, y registra (sin contraseñas) los intentos fallidos.
* Con muchas instancias del backend, el árbol de categorías cacheado en memoria necesita invalidarse (TTL corto o evento).
