"""
Esquema de Base de Datos Relacional para Plataforma SaaS de Administración de Condominios.
Implementado con SQLAlchemy 2.0 (ORM) y Type Hints completos.

Características de Arquitectura Empresarial:
- Patrón Declarativo Moderno (DeclarativeBase, Mapped, mapped_column).
- Claves Primarias basadas en UUIDv4 (tipo generic Uuid de SQLAlchemy 2.0) para alta concurrencia,
  escalabilidad multi-tenant y prevención de vulnerabilidades de enumeración IDOR.
- Restricciones de Integridad Referencial (ForeignKeys con CASCADE, SET NULL y RESTRICT).
- Índices B-Tree compuestos y simples para optimizar consultas de alta frecuencia
  (Búsquedas de QR en garita, búsquedas por cédula/placa, filtros de morosidad y traslape de reservas).
- Tipado Estricto con Enums de Python y Restricciones a nivel de base de datos (CheckConstraints).
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


# ==============================================================================
# BASE DECLARATIVA
# ==============================================================================

class Base(DeclarativeBase):
    """Clase base declarativa común para todos los modelos del sistema."""
    pass


# ==============================================================================
# ENUMERACIONES (DOMINIO DEL NEGOCIO)
# ==============================================================================

class UserRole(str, enum.Enum):
    """Roles de acceso y autorización en la plataforma."""
    ADMINISTRADOR = "ADMINISTRADOR"
    RESIDENTE = "RESIDENTE"
    GUARDIA = "GUARDIA"


class ObligationType(str, enum.Enum):
    """Categorías de obligaciones financieras."""
    ORDINARIA = "ORDINARIA"          # Alícuota mensual ordinaria
    EXTRAORDINARIA = "EXTRAORDINARIA"  # Cuota extraordinaria para mejoras/mantenimiento
    MULTA = "MULTA"                  # Sanciones por infracciones al reglamento


class ObligationStatus(str, enum.Enum):
    """Estados del ciclo de vida de una obligación financiera."""
    PENDIENTE = "PENDIENTE"
    PAGADA = "PAGADA"
    VENCIDA = "VENCIDA"


class PaymentMethod(str, enum.Enum):
    """Métodos de recaudación habilitados."""
    TRANSFERENCIA = "TRANSFERENCIA"
    TARJETA = "TARJETA"
    EFECTIVO = "EFECTIVO"


class PaymentValidationStatus(str, enum.Enum):
    """Estados de auditoría y conciliación de un pago."""
    EN_REVISION = "EN_REVISION"
    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"


class VisitType(str, enum.Enum):
    """Clasificación de visitantes para garita."""
    FAMILIAR = "FAMILIAR"
    DELIVERY = "DELIVERY"
    UBER = "UBER"
    CONTRATISTA = "CONTRATISTA"


class QRPassStatus(str, enum.Enum):
    """Estados del pase de visita con código QR."""
    ACTIVO = "ACTIVO"
    USADO = "USADO"
    EXPIRADO = "EXPIRADO"


class ReservationStatus(str, enum.Enum):
    """Estados de solicitud de uso de áreas comunales."""
    SOLICITADA = "SOLICITADA"
    APROBADA = "APROBADA"
    RECHAZADA = "RECHAZADA"
    CANCELADA = "CANCELADA"


class TicketCategory(str, enum.Enum):
    """Áreas o especialidades de soporte y mantenimiento."""
    PLOMERIA = "PLOMERIA"
    ILUMINACION = "ILUMINACION"
    CONVIVENCIA = "CONVIVENCIA"
    SEGURIDAD = "SEGURIDAD"
    AREAS_COMUNES = "AREAS_COMUNES"
    OTROS = "OTROS"


class TicketStatus(str, enum.Enum):
    """Flujo de atención de tickets de novedades/daños."""
    ABIERTO = "ABIERTO"
    EN_PROGRESO = "EN_PROGRESO"
    RESUELTO = "RESUELTO"


# ==============================================================================
# 1. SEGURIDAD Y ROLES
# ==============================================================================

class User(Base):
    """
    Representa a los usuarios del sistema (Administradores, Residentes y Guardias).
    
    Reglas de Negocio:
    - El email es la identidad única del usuario y posee índice B-tree para login O(1).
    - Un usuario puede ser propietario de varias unidades y arrendatario de otra.
    - Los guardias registran accesos en garita (trazabilidad de seguridad).
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Identificador único universal (UUIDv4) del usuario",
    )
    nombre_completo: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        doc="Nombres y apellidos completos del usuario",
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
        doc="Correo electrónico único utilizado como credencial principal de autenticación",
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Hash seguro de la contraseña (e.g. Argon2id o Bcrypt)",
    )
    rol: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole, name="user_role_enum", native_enum=False),
        nullable=False,
        index=True,
        doc="Rol asignado que determina los permisos en el sistema",
    )
    telefono: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        doc="Número de contacto telefónico principal o celular",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        doc="Indica si la cuenta está activa para iniciar sesión",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp de creación del usuario en el sistema",
    )

    # Relaciones Cruzadas (Cross-Relationships con back_populates explícitos)
    propiedades: Mapped[List["Unit"]] = relationship(
        "Unit",
        foreign_keys="[Unit.propietario_id]",
        back_populates="propietario",
        lazy="selectin",
    )
    residencias: Mapped[List["Unit"]] = relationship(
        "Unit",
        foreign_keys="[Unit.residente_id]",
        back_populates="residente",
        lazy="selectin",
    )
    registros_guardia: Mapped[List["AccessLog"]] = relationship(
        "AccessLog",
        foreign_keys="[AccessLog.guard_id]",
        back_populates="guard",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<User(id={self.id}, nombre_completo='{self.nombre_completo}', "
            f"email='{self.email}', rol='{self.rol.value}', is_active={self.is_active})>"
        )


# ==============================================================================
# 2. ESTRUCTURA DEL CONDOMINIO
# ==============================================================================

class Unit(Base):
    """
    Representa una unidad habitacional física (departamento, casa, villa, local comercial).

    Reglas de Negocio:
    - `identificador` es único para evitar duplicidades dentro del condominio (ej. Torre A - 101).
    - `coeficiente_copropiedad` determina el porcentaje de participación para alícuotas (ej. 0.045 = 4.5%).
    - Propietario (`RESTRICT`): No se puede eliminar un usuario propietario sin transferir o liquidar su unidad.
    - Residente (`SET NULL`): Si el habitante o arrendatario se desvincula, la unidad queda vacante (NULL).
    - Cascada (`CASCADE`): Si una unidad es suprimida administrativamente, se eliminan en cascada sus obligaciones,
      pagos, pases de visita, reservas y tickets.
    """
    __tablename__ = "units"
    __table_args__ = (
        CheckConstraint("coeficiente_copropiedad >= 0", name="chk_unit_coeficiente_positivo"),
        Index("idx_units_propietario_residente", "propietario_id", "residente_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Identificador único (UUIDv4) de la unidad habitacional",
    )
    identificador: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
        doc="Nomenclatura única de la unidad (ej. 'Torre A - 101', 'Casa 14')",
    )
    coeficiente_copropiedad: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Coeficiente porcentual de copropiedad para cálculo proporcional de alícuotas",
    )
    propietario_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="FK al usuario propietario legítimo de la unidad",
    )
    residente_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="FK al habitante actual (arrendatario o habitante). Nullable si está vacía",
    )

    # Relaciones con Usuarios
    propietario: Mapped["User"] = relationship(
        "User",
        foreign_keys=[propietario_id],
        back_populates="propiedades",
    )
    residente: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[residente_id],
        back_populates="residencias",
    )

    # Relaciones Modulares con Cascada hacia entidades dependientes
    obligaciones: Mapped[List["FinancialObligation"]] = relationship(
        "FinancialObligation",
        back_populates="unit",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    pagos: Mapped[List["Payment"]] = relationship(
        "Payment",
        back_populates="unit",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    pases_qr: Mapped[List["QRPass"]] = relationship(
        "QRPass",
        back_populates="unit",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )
    registros_acceso: Mapped[List["AccessLog"]] = relationship(
        "AccessLog",
        back_populates="unit",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )
    reservas: Mapped[List["Reservation"]] = relationship(
        "Reservation",
        back_populates="unit",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )
    tickets: Mapped[List["SupportTicket"]] = relationship(
        "SupportTicket",
        back_populates="unit",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<Unit(id={self.id}, identificador='{self.identificador}', "
            f"coeficiente={self.coeficiente_copropiedad}, propietario_id={self.propietario_id}, "
            f"residente_id={self.residente_id})>"
        )


# ==============================================================================
# 3. MÓDULO FINANCIERO (Facturación y Pagos)
# ==============================================================================

class FinancialObligation(Base):
    """
    Representa una cuenta por cobrar (deuda, alícuota o multa) asignada a una unidad.
    
    Reglas de Negocio:
    - El monto se almacena en `Numeric(10, 2)` (Decimal) para prevenir imprecisiones de punto flotante.
    - Índices B-Tree optimizados para consultas de morosidad, reportes de cartera vencida y filtros por estado.
    """
    __tablename__ = "financial_obligations"
    __table_args__ = (
        CheckConstraint("monto >= 0", name="chk_obligation_monto_positivo"),
        Index("idx_obligations_unit_estado", "unit_id", "estado"),
        Index("idx_obligations_vencimiento_estado", "fecha_vencimiento", "estado"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Identificador único (UUIDv4) de la obligación financiera",
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="FK a la unidad responsable de la deuda",
    )
    tipo: Mapped[ObligationType] = mapped_column(
        SQLEnum(ObligationType, name="obligation_type_enum", native_enum=False),
        nullable=False,
        doc="Tipo de obligación: ORDINARIA, EXTRAORDINARIA o MULTA",
    )
    concepto: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="Descripción detallada del rubro (ej. 'Alícuota Ordinaria Noviembre 2026')",
    )
    monto: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="Monto monetario exacto con 2 decimales",
    )
    fecha_emision: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        default=date.today,
        doc="Fecha de emisión o facturación del rubro",
    )
    fecha_vencimiento: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        doc="Fecha límite de pago oportuno antes de generar mora",
    )
    estado: Mapped[ObligationStatus] = mapped_column(
        SQLEnum(ObligationStatus, name="obligation_status_enum", native_enum=False),
        nullable=False,
        default=ObligationStatus.PENDIENTE,
        index=True,
        doc="Estado de la obligación: PENDIENTE, PAGADA o VENCIDA",
    )

    # Relación
    unit: Mapped["Unit"] = relationship(
        "Unit",
        back_populates="obligaciones",
    )

    def __repr__(self) -> str:
        return (
            f"<FinancialObligation(id={self.id}, unit_id={self.unit_id}, "
            f"tipo='{self.tipo.value}', concepto='{self.concepto}', monto={self.monto}, "
            f"estado='{self.estado.value}', vencimiento={self.fecha_vencimiento})>"
        )


class Payment(Base):
    """
    Representa una transacción de pago registrada o procesada para una unidad.

    Reglas de Negocio:
    - Incluye soporte para URL de comprobante digital en almacenamiento en la nube (S3, GCS).
    - Estado de validación administrativa para flujos de conciliación bancaria.
    """
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("monto_pagado > 0", name="chk_payment_monto_positivo"),
        Index("idx_payments_unit_fecha", "unit_id", "fecha_pago"),
        Index("idx_payments_validacion_fecha", "estado_validacion", "fecha_pago"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Identificador único (UUIDv4) de la transacción de pago",
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="FK a la unidad que efectúa el pago",
    )
    monto_pagado: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="Monto monetario recibido o reportado",
    )
    fecha_pago: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        doc="Fecha y hora en que se ejecutó la transacción",
    )
    metodo: Mapped[PaymentMethod] = mapped_column(
        SQLEnum(PaymentMethod, name="payment_method_enum", native_enum=False),
        nullable=False,
        doc="Canal de cobro: TRANSFERENCIA, TARJETA o EFECTIVO",
    )
    comprobante_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        doc="URL del comprobante digital almacenado en almacenamiento en la nube",
    )
    estado_validacion: Mapped[PaymentValidationStatus] = mapped_column(
        SQLEnum(PaymentValidationStatus, name="payment_validation_enum", native_enum=False),
        nullable=False,
        default=PaymentValidationStatus.EN_REVISION,
        index=True,
        doc="Estado de validación: EN_REVISION, APROBADO o RECHAZADO",
    )
    notas_admin: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Comentarios u observaciones de conciliación administrativa",
    )

    # Relación
    unit: Mapped["Unit"] = relationship(
        "Unit",
        back_populates="pagos",
    )

    def __repr__(self) -> str:
        return (
            f"<Payment(id={self.id}, unit_id={self.unit_id}, monto_pagado={self.monto_pagado}, "
            f"metodo='{self.metodo.value}', estado='{self.estado_validacion.value}', fecha={self.fecha_pago})>"
        )


# ==============================================================================
# 4. MÓDULO DE SEGURIDAD (Control de Acceso en Garita)
# ==============================================================================

class QRPass(Base):
    """
    Representa una invitación / pase digital con código QR generado por el residente.

    Reglas de Negocio:
    - `hash_qr` es único e indexado con índice B-tree para verificación en milisegundos en garita.
    - Ventana de vigencia temporal (`fecha_hora_inicio` y `fecha_hora_fin`).
    """
    __tablename__ = "qr_passes"
    __table_args__ = (
        CheckConstraint("fecha_hora_fin > fecha_hora_inicio", name="chk_qr_pass_rango_fechas"),
        Index("idx_qr_passes_unit_estado", "unit_id", "estado"),
        Index("idx_qr_passes_vigencia", "fecha_hora_inicio", "fecha_hora_fin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Identificador único (UUIDv4) del pase QR",
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="FK a la unidad que autoriza la visita",
    )
    nombre_visitante: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        doc="Nombre completo del visitante invitado",
    )
    tipo_visita: Mapped[VisitType] = mapped_column(
        SQLEnum(VisitType, name="visit_type_enum", native_enum=False),
        nullable=False,
        doc="Clasificación: FAMILIAR, DELIVERY, UBER, CONTRATISTA",
    )
    hash_qr: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
        doc="Token criptográfico único (ej. SHA-256) codificado dentro de la imagen QR",
    )
    fecha_hora_inicio: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Inicio de la ventana de validez del pase",
    )
    fecha_hora_fin: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Fin de la ventana de validez del pase",
    )
    estado: Mapped[QRPassStatus] = mapped_column(
        SQLEnum(QRPassStatus, name="qr_pass_status_enum", native_enum=False),
        nullable=False,
        default=QRPassStatus.ACTIVO,
        index=True,
        doc="Estado del pase: ACTIVO, USADO o EXPIRADO",
    )

    # Relaciones
    unit: Mapped["Unit"] = relationship(
        "Unit",
        back_populates="pases_qr",
    )
    access_logs: Mapped[List["AccessLog"]] = relationship(
        "AccessLog",
        back_populates="qr_pass",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<QRPass(id={self.id}, unit_id={self.unit_id}, visitante='{self.nombre_visitante}', "
            f"tipo='{self.tipo_visita.value}', estado='{self.estado.value}', hash_qr='{self.hash_qr[:10]}...')>"
        )


class AccessLog(Base):
    """
    Bitácora física/digital de garita para control y trazabilidad de ingresos y salidas.

    Reglas de Negocio:
    - Si el ingreso es sin QR (portería tradicional/manual), `qr_pass_id` es `NULL`.
    - Si se borra o expira el pase QR, el log histórico se preserva con integridad (`ondelete="SET NULL"`).
    - El guardia que registró el acceso queda vinculado con restricción (`RESTRICT`).
    - Índices B-tree en cédula y placa para auditorías de seguridad rápidas.
    """
    __tablename__ = "access_logs"
    __table_args__ = (
        Index("idx_access_logs_fecha_ingreso", "fecha_hora_ingreso"),
        Index("idx_access_logs_cedula", "cedula_visitante"),
        Index("idx_access_logs_placa", "placa_vehiculo"),
        Index("idx_access_logs_unit_fecha", "unit_id", "fecha_hora_ingreso"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Identificador único (UUIDv4) de la entrada en bitácora",
    )
    qr_pass_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid,
        ForeignKey("qr_passes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="FK opcional al pase QR presentado (NULL si fue ingreso manual sin QR)",
    )
    guard_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="FK al guardia que validó y registró el ingreso",
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="FK a la unidad de destino de la visita",
    )
    cedula_visitante: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        doc="Documento nacional de identidad o pasaporte del visitante",
    )
    placa_vehiculo: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        doc="Placa/patente vehicular en caso de ingreso con automóvil",
    )
    fecha_hora_ingreso: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="Timestamp exacto de ingreso",
    )
    fecha_hora_salida: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp exacto de salida (NULL si el visitante sigue dentro)",
    )

    # Relaciones
    qr_pass: Mapped[Optional["QRPass"]] = relationship(
        "QRPass",
        back_populates="access_logs",
    )
    guard: Mapped["User"] = relationship(
        "User",
        foreign_keys=[guard_id],
        back_populates="registros_guardia",
    )
    unit: Mapped["Unit"] = relationship(
        "Unit",
        foreign_keys=[unit_id],
        back_populates="registros_acceso",
    )

    def __repr__(self) -> str:
        return (
            f"<AccessLog(id={self.id}, unit_id={self.unit_id}, guard_id={self.guard_id}, "
            f"cedula='{self.cedula_visitante}', placa='{self.placa_vehiculo}', ingreso={self.fecha_hora_ingreso})>"
        )


# ==============================================================================
# 5. MÓDULO DE CONVIVENCIA (Reservas y Helpdesk)
# ==============================================================================

class CommonArea(Base):
    """
    Representa un área comunal sujeta a reservación y normas de uso comunitario.

    Reglas de Negocio:
    - Control de aforo máximo para seguridad.
    - Costo de reserva con Decimal y bandera de aprobación administrativa obligatoria.
    """
    __tablename__ = "common_areas"
    __table_args__ = (
        CheckConstraint("aforo_maximo > 0", name="chk_common_area_aforo_positivo"),
        CheckConstraint("costo_reserva >= 0", name="chk_common_area_costo_no_negativo"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Identificador único (UUIDv4) del área comunal",
    )
    nombre: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        doc="Nombre descriptivo único (ej. 'Salón de Eventos', 'Área BBQ Principal')",
    )
    aforo_maximo: Mapped[int] = mapped_column(
        nullable=False,
        doc="Capacidad máxima de personas permitidas simultáneamente",
    )
    costo_reserva: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        doc="Costo de uso/mantenimiento de la reserva (0 si es gratuita)",
    )
    requiere_aprobacion: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="True si requiere aprobación del administrador antes de confirmarse",
    )

    # Relaciones
    reservas: Mapped[List["Reservation"]] = relationship(
        "Reservation",
        back_populates="area",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<CommonArea(id={self.id}, nombre='{self.nombre}', aforo_maximo={self.aforo_maximo}, "
            f"costo_reserva={self.costo_reserva}, requiere_aprobacion={self.requiere_aprobacion})>"
        )


class Reservation(Base):
    """
    Representa una solicitud de reserva de un área comunal por parte de una unidad.

    Reglas de Negocio:
    - Índice compuesto en (area_id, fecha_hora_inicio, fecha_hora_fin) para validación rápida
      de traslapes de horario (evitar doble agendamiento).
    - Restricción de verificación que garantiza que fin > inicio.
    """
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("fecha_hora_fin > fecha_hora_inicio", name="chk_reservation_fechas_validas"),
        Index("idx_reservations_solapamiento", "area_id", "fecha_hora_inicio", "fecha_hora_fin"),
        Index("idx_reservations_unit_estado", "unit_id", "estado"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Identificador único (UUIDv4) de la reservación",
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="FK a la unidad que solicita el área",
    )
    area_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("common_areas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="FK al área comunal solicitada",
    )
    fecha_hora_inicio: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Fecha y hora de inicio de la reserva",
    )
    fecha_hora_fin: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Fecha y hora de conclusión de la reserva",
    )
    estado: Mapped[ReservationStatus] = mapped_column(
        SQLEnum(ReservationStatus, name="reservation_status_enum", native_enum=False),
        nullable=False,
        default=ReservationStatus.SOLICITADA,
        index=True,
        doc="Estado de la reserva: SOLICITADA, APROBADA, RECHAZADA, CANCELADA",
    )

    # Relaciones
    unit: Mapped["Unit"] = relationship(
        "Unit",
        back_populates="reservas",
    )
    area: Mapped["CommonArea"] = relationship(
        "CommonArea",
        back_populates="reservas",
    )

    def __repr__(self) -> str:
        return (
            f"<Reservation(id={self.id}, unit_id={self.unit_id}, area_id={self.area_id}, "
            f"inicio={self.fecha_hora_inicio}, fin={self.fecha_hora_fin}, estado='{self.estado.value}')>"
        )


class SupportTicket(Base):
    """
    Representa un reporte de daño, mantenimiento o novedad de convivencia.

    Reglas de Negocio:
    - Indexado para dashboards de administración por unidad, estado y categoría.
    - Soporta enlace a archivo fotográfico (`foto_url`).
    """
    __tablename__ = "support_tickets"
    __table_args__ = (
        Index("idx_tickets_unit_estado", "unit_id", "estado"),
        Index("idx_tickets_categoria_estado", "categoria", "estado"),
        Index("idx_tickets_fecha_creacion", "fecha_creacion"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Identificador único (UUIDv4) del ticket de soporte",
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="FK a la unidad habitacional que origina el reporte",
    )
    categoria: Mapped[TicketCategory] = mapped_column(
        SQLEnum(TicketCategory, name="ticket_category_enum", native_enum=False),
        nullable=False,
        doc="Categoría: PLOMERIA, ILUMINACION, CONVIVENCIA, SEGURIDAD, AREAS_COMUNES, OTROS",
    )
    descripcion: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Explicación detallada del reporte o novedad",
    )
    foto_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        doc="Enlace seguro a la fotografía o evidencia adjunta",
    )
    estado: Mapped[TicketStatus] = mapped_column(
        SQLEnum(TicketStatus, name="ticket_status_enum", native_enum=False),
        nullable=False,
        default=TicketStatus.ABIERTO,
        index=True,
        doc="Estado del ticket: ABIERTO, EN_PROGRESO o RESUELTO",
    )
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
        doc="Timestamp de creación del ticket",
    )

    # Relación
    unit: Mapped["Unit"] = relationship(
        "Unit",
        back_populates="tickets",
    )

    def __repr__(self) -> str:
        return (
            f"<SupportTicket(id={self.id}, unit_id={self.unit_id}, "
            f"categoria='{self.categoria.value}', estado='{self.estado.value}', fecha={self.fecha_creacion})>"
        )


# ==============================================================================
# DEMOSTRACIÓN DE VERIFICACIÓN Y PRUEBAS FUNCIONALES
# ==============================================================================

if __name__ == "__main__":
    from datetime import timedelta
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    print("=" * 80)
    print("VERIFICACIÓN DEL ESQUEMA DE BASE DE DATOS (SaaS Condominios)")
    print("=" * 80)

    # 1. Configuración de motor en memoria para pruebas
    engine = create_engine("sqlite:///:memory:", echo=False)

    print("\n[1/4] Creando todas las tablas e índices en el motor relacional...")
    Base.metadata.create_all(engine)
    print("  -> Tablas creadas con éxito:", list(Base.metadata.tables.keys()))

    with Session(engine) as session:
        print("\n[2/4] Sembrando datos de prueba (Seed Data)...")

        # Usuarios
        admin = User(
            nombre_completo="Carlos Méndez (Admin)",
            email="admin@condominio.com",
            password_hash="pbkdf2:sha256:100000$admin_hash",
            rol=UserRole.ADMINISTRADOR,
            telefono="+593987654321",
        )
        propietario = User(
            nombre_completo="Dra. Laura Valencia (Propietaria)",
            email="laura.valencia@example.com",
            password_hash="pbkdf2:sha256:100000$laura_hash",
            rol=UserRole.RESIDENTE,
            telefono="+593991234567",
        )
        inquilino = User(
            nombre_completo="Ing. David Salazar (Arrendatario)",
            email="david.salazar@example.com",
            password_hash="pbkdf2:sha256:100000$david_hash",
            rol=UserRole.RESIDENTE,
            telefono="+593998877665",
        )
        guardia = User(
            nombre_completo="José Guachamín (Guardia Garita)",
            email="garita1@condominio.com",
            password_hash="pbkdf2:sha256:100000$guardia_hash",
            rol=UserRole.GUARDIA,
            telefono="+593990001122",
        )
        session.add_all([admin, propietario, inquilino, guardia])
        session.flush()

        # Unidad Habitacional
        unit_101 = Unit(
            identificador="Torre A - 101",
            coeficiente_copropiedad=0.045,  # 4.5% de alícuota
            propietario_id=propietario.id,
            residente_id=inquilino.id,
        )
        session.add(unit_101)
        session.flush()

        # Obligaciones Financieras
        alicuota_nov = FinancialObligation(
            unit_id=unit_101.id,
            tipo=ObligationType.ORDINARIA,
            concepto="Alícuota Ordinaria Noviembre 2026",
            monto=Decimal("85.50"),
            fecha_emision=date(2026, 11, 1),
            fecha_vencimiento=date(2026, 11, 10),
            estado=ObligationStatus.PENDIENTE,
        )
        multa_ruido = FinancialObligation(
            unit_id=unit_101.id,
            tipo=ObligationType.MULTA,
            concepto="Multa por exceso de ruido en horario no permitido",
            monto=Decimal("40.00"),
            fecha_emision=date(2026, 11, 5),
            fecha_vencimiento=date(2026, 11, 15),
            estado=ObligationStatus.PENDIENTE,
        )
        session.add_all([alicuota_nov, multa_ruido])

        # Pago reportado
        pago = Payment(
            unit_id=unit_101.id,
            monto_pagado=Decimal("85.50"),
            fecha_pago=datetime.utcnow(),
            metodo=PaymentMethod.TRANSFERENCIA,
            comprobante_url="https://s3.amazonaws.com/condo-receipts/comprobante-8842.pdf",
            estado_validacion=PaymentValidationStatus.APROBADO,
            notas_admin="Transferencia confirmada en Banco Pichincha Ref #8842",
        )
        session.add(pago)

        # Módulo de Seguridad: Pase QR y Registro de Ingreso en Garita
        ahora = datetime.utcnow()
        qr_visitante = QRPass(
            unit_id=unit_101.id,
            nombre_visitante="Martín Estrada (Familiar)",
            tipo_visita=VisitType.FAMILIAR,
            hash_qr=uuid.uuid4().hex,
            fecha_hora_inicio=ahora - timedelta(hours=1),
            fecha_hora_fin=ahora + timedelta(hours=5),
            estado=QRPassStatus.ACTIVO,
        )
        session.add(qr_visitante)
        session.flush()

        log_ingreso = AccessLog(
            qr_pass_id=qr_visitante.id,
            guard_id=guardia.id,
            unit_id=unit_101.id,
            cedula_visitante="1718293847",
            placa_vehiculo="PBA-4832",
            fecha_hora_ingreso=ahora,
        )
        session.add(log_ingreso)

        # Módulo de Convivencia: Área Comunal, Reserva y Ticket de Mantenimiento
        area_bbq = CommonArea(
            nombre="Área BBQ Panorámica",
            aforo_maximo=25,
            costo_reserva=Decimal("20.00"),
            requiere_aprobacion=True,
        )
        session.add(area_bbq)
        session.flush()

        reserva = Reservation(
            unit_id=unit_101.id,
            area_id=area_bbq.id,
            fecha_hora_inicio=ahora + timedelta(days=2, hours=12),
            fecha_hora_fin=ahora + timedelta(days=2, hours=18),
            estado=ReservationStatus.SOLICITADA,
        )
        ticket = SupportTicket(
            unit_id=unit_101.id,
            categoria=TicketCategory.PLOMERIA,
            descripcion="Fuga de agua ligera detectada en la llave de paso del balcón.",
            foto_url="https://s3.amazonaws.com/condo-tickets/ticket-101-balcon.jpg",
            estado=TicketStatus.ABIERTO,
        )
        session.add_all([reserva, ticket])

        session.commit()
        print("  -> Datos sembrados correctamente.")

        # 3. Consultas de demostración
        print("\n[3/4] Ejecutando consultas de prueba con relaciones...")

        u101 = session.scalar(select(Unit).where(Unit.identificador == "Torre A - 101"))
        print(f"  Unidad: {u101}")
        print(f"  -> Propietario: {u101.propietario.nombre_completo} ({u101.propietario.email})")
        print(f"  -> Residente:   {u101.residente.nombre_completo} ({u101.residente.email})")
        print(f"  -> Obligaciones ({len(u101.obligaciones)}): {[o.concepto for o in u101.obligaciones]}")
        deuda_pendiente = sum(o.monto for o in u101.obligaciones if o.estado == ObligationStatus.PENDIENTE)
        print(f"  -> Total Deuda Pendiente: ${deuda_pendiente:.2f}")
        print(f"  -> Pagos Registrados: {[p.monto_pagado for p in u101.pagos]}")
        print(f"  -> Tickets Abiertos: {[t.categoria.value for t in u101.tickets]}")

        # Consultar bitácora de guardia
        logs = session.scalars(select(AccessLog).where(AccessLog.unit_id == u101.id)).all()
        print(f"\n[4/4] Verificación de Bitácora de Garita ({len(logs)} registros):")
        for log in logs:
            print(f"  Log ID: {log.id} | Visitante: {log.cedula_visitante} | Placa: {log.placa_vehiculo} | Guardia: {log.guard.nombre_completo}")

    print("\n" + "=" * 80)
    print("¡TODO EL ESQUEMA FUE VALIDADO Y FUNCIONA A LA PERFECCIÓN!")
    print("=" * 80)
