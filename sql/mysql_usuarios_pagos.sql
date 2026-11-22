-- Base A: usuarios y pagos
-- Generado por scripts/exportar_ddl.py a partir de app/relacional/esquema.py. No lo edites a mano.
-- Requiere MySQL 8.0.16+ (las restricciones CHECK se aplican desde esa versión).

CREATE DATABASE IF NOT EXISTS `mkt_usuarios` CHARACTER SET utf8mb4;
USE `mkt_usuarios`;

CREATE TABLE pagos (
	id_pago BIGINT NOT NULL AUTO_INCREMENT, 
	id_pedido BIGINT NOT NULL, 
	metodo_pago VARCHAR(30) NOT NULL, 
	estatus VARCHAR(20) NOT NULL, 
	monto NUMERIC(12, 2) NOT NULL, 
	referencia_transaccion VARCHAR(100), 
	fecha_pago DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, 
	CONSTRAINT pk_pagos PRIMARY KEY (id_pago), 
	CONSTRAINT ck_pagos_estatus CHECK (estatus IN ('APROBADO','RECHAZADO','REEMBOLSADO')), 
	CONSTRAINT ck_pagos_monto CHECK (monto >= 0)
)ENGINE=InnoDB CHARSET=utf8mb4;

CREATE INDEX ix_pagos_id_pedido ON pagos (id_pedido);

CREATE TABLE usuarios (
	id_usuario BIGINT NOT NULL AUTO_INCREMENT, 
	correo VARCHAR(255) NOT NULL, 
	contrasena_hash VARCHAR(255) NOT NULL, 
	rol VARCHAR(20) NOT NULL DEFAULT 'COMPRADOR', 
	nombre VARCHAR(100) NOT NULL, 
	apellido VARCHAR(100) NOT NULL, 
	telefono VARCHAR(30), 
	estatus VARCHAR(20) NOT NULL DEFAULT 'ACTIVO', 
	fecha_registro DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, 
	CONSTRAINT pk_usuarios PRIMARY KEY (id_usuario), 
	CONSTRAINT uq_usuarios_correo UNIQUE (correo), 
	CONSTRAINT ck_usuarios_rol CHECK (rol IN ('COMPRADOR','VENDEDOR','ADMIN')), 
	CONSTRAINT ck_usuarios_estatus CHECK (estatus IN ('ACTIVO','SUSPENDIDO'))
)ENGINE=InnoDB CHARSET=utf8mb4;

CREATE INDEX ix_usuarios_rol_id ON usuarios (rol, id_usuario);
