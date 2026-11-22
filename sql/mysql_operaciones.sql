-- Base B: carritos, detalle_carrito, pedidos y detalle_pedido
-- Generado por scripts/exportar_ddl.py a partir de app/relacional/esquema.py. No lo edites a mano.
-- Requiere MySQL 8.0.16+ (las restricciones CHECK se aplican desde esa versión).

CREATE DATABASE IF NOT EXISTS `mkt_operaciones` CHARACTER SET utf8mb4;
USE `mkt_operaciones`;

CREATE TABLE carritos (
	id_carrito BIGINT NOT NULL AUTO_INCREMENT, 
	id_usuario BIGINT NOT NULL, 
	estatus VARCHAR(20) NOT NULL DEFAULT 'ACTIVO', 
	fecha_creacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, 
	fecha_actualizacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, 
	CONSTRAINT pk_carritos PRIMARY KEY (id_carrito), 
	CONSTRAINT ck_carritos_estatus CHECK (estatus IN ('ACTIVO','CONVERTIDO','ABANDONADO'))
)ENGINE=InnoDB CHARSET=utf8mb4;

CREATE INDEX ix_carritos_usuario_estatus ON carritos (id_usuario, estatus);

CREATE TABLE pedidos (
	id_pedido BIGINT NOT NULL AUTO_INCREMENT, 
	id_comprador BIGINT NOT NULL, 
	estatus VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE', 
	monto_total NUMERIC(12, 2) NOT NULL, 
	direccion_envio VARCHAR(500) NOT NULL, 
	fecha_pedido DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, 
	CONSTRAINT pk_pedidos PRIMARY KEY (id_pedido), 
	CONSTRAINT ck_pedidos_estatus CHECK (estatus IN ('PENDIENTE','PAGADO','ENVIADO','ENTREGADO','CANCELADO')), 
	CONSTRAINT ck_pedidos_monto_total CHECK (monto_total >= 0)
)ENGINE=InnoDB CHARSET=utf8mb4;

CREATE INDEX ix_pedidos_comprador_id ON pedidos (id_comprador, id_pedido);

CREATE INDEX ix_pedidos_estatus_id ON pedidos (estatus, id_pedido);

CREATE TABLE detalle_carrito (
	id_detalle_carrito BIGINT NOT NULL AUTO_INCREMENT, 
	id_carrito BIGINT NOT NULL, 
	id_variante VARCHAR(36) NOT NULL, 
	cantidad INTEGER NOT NULL, 
	CONSTRAINT pk_detalle_carrito PRIMARY KEY (id_detalle_carrito), 
	CONSTRAINT uq_detalle_carrito_variante UNIQUE (id_carrito, id_variante), 
	CONSTRAINT ck_detalle_carrito_cantidad CHECK (cantidad > 0), 
	CONSTRAINT fk_detalle_carrito_id_carrito_carritos FOREIGN KEY(id_carrito) REFERENCES carritos (id_carrito) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4;

CREATE TABLE detalle_pedido (
	id_detalle_pedido BIGINT NOT NULL AUTO_INCREMENT, 
	id_pedido BIGINT NOT NULL, 
	id_variante VARCHAR(36) NOT NULL, 
	id_vendedor BIGINT NOT NULL, 
	precio_unitario NUMERIC(12, 2) NOT NULL, 
	cantidad INTEGER NOT NULL, 
	subtotal NUMERIC(12, 2) NOT NULL, 
	CONSTRAINT pk_detalle_pedido PRIMARY KEY (id_detalle_pedido), 
	CONSTRAINT ck_detalle_pedido_cantidad CHECK (cantidad > 0), 
	CONSTRAINT fk_detalle_pedido_id_pedido_pedidos FOREIGN KEY(id_pedido) REFERENCES pedidos (id_pedido) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4;

CREATE INDEX ix_detalle_pedido_pedido ON detalle_pedido (id_pedido);

CREATE INDEX ix_detalle_pedido_variante ON detalle_pedido (id_variante);

CREATE INDEX ix_detalle_pedido_vendedor_id ON detalle_pedido (id_vendedor, id_detalle_pedido);
