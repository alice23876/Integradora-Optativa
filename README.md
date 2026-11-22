# Marketplace — interfaz gráfica en Python

Aplicación de escritorio (**PySide6 / Qt 6**) para un marketplace con **17,000+ productos**, pensada para ser
cómoda y didáctica: se entiende sola, explica los errores en español y nunca se queda «congelada».

Se conecta a tus **4 tablas de DynamoDB** (`productos`, `categorias`, `resenas`, `variantes_producto`) y a tus
**2 bases MySQL** (`usuarios` + `pagos` · `carritos` + `detalle_carrito` + `pedidos` + `detalle_pedido`), o bien —
cuando lo tengamos— **a tu backend Python por HTTP**. Los 3 modos se cambian desde la propia pantalla de inicio.

| Modo | Para qué sirve | Qué necesita |
|---|---|---|
| **Demostración** (por defecto) | Conocer la aplicación ya: 17,000 productos de ejemplo en tu computadora | Nada (ni AWS ni MySQL) |
| **Directo** | Desarrollo: la app habla con DynamoDB y los 2 MySQL | Credenciales en `.env` |
| **API** | Producción: la app habla con *tu backend* | Backend que cumpla [`docs/contrato_api.md`](docs/contrato_api.md) |

![Inicio de sesión](docs/capturas/01_login.png)
![Catálogo](docs/capturas/02_tienda.png)

---
## 2. Qué puede hacer cada rol

| Rol | Pantallas |
|---|---|
| **Comprador** | **Tienda** (cuadrícula con desplazamiento infinito, búsqueda, árbol de categorías) · detalle de producto con variantes (talla/color…) y reseñas · **Carrito** · **Compra** (dirección + método de pago) · **Mis pedidos** (seguimiento, cancelar, «Marcar como entregado», reseñar) |
| **Vendedor** | Todo lo del comprador + **Mis productos** (publicar/editar con variantes, SKU, precio, existencias, activar/pausar) + **Mis ventas** (marcar como enviado) |
| **Administrador** | **Panel** con indicadores · **Usuarios** (cambiar rol, suspender/reactivar) · **Categorías** (árbol, crear/editar/mover) · **Pedidos** (todos, cambiar estatus) · **Pagos** · **Conexiones** (estado de cada base de datos) 
