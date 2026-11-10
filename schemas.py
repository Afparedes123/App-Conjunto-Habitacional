"""
Esquemas de Validación y Serialización (Pydantic v2).
Garantizan tipado estricto en la entrada y salida de los endpoints de la API REST.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from models import (
    ObligationStatus,
    ObligationType,
    PaymentMethod,
    PaymentValidationStatus,
    UserRole,
)


# ==============================================================================
# ESQUEMAS DE AUTENTICACIÓN Y SESIÓN
# ==============================================================================

class LoginRequest(BaseModel):
    """Payload para autenticación de usuarios."""
    email: EmailStr = Field(..., description="Correo electrónico registrado del usuario")
    password: str = Field(..., min_length=1, description="Contraseña en texto plano")


class TokenResponse(BaseModel):
    """Respuesta con token de acceso JWT e información del usuario autenticado."""
    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID
    nombre_completo: str
    email: str
    rol: UserRole


class UserProfileResponse(BaseModel):
    """Perfil detallado del usuario autenticado."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre_completo: str
    email: str
    rol: UserRole
    telefono: Optional[str] = None
    is_active: bool
    created_at: datetime


# ==============================================================================
# ESQUEMAS DEL MÓDULO DE UNIDADES
# ==============================================================================

class UnitSummaryResponse(BaseModel):
    """Detalle resumido de una unidad habitacional para vistas administrativas."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    identificador: str
    coeficiente_copropiedad: float
    propietario_id: uuid.UUID
    propietario_nombre: str
    propietario_email: str
    residente_id: Optional[uuid.UUID] = None
    residente_nombre: Optional[str] = None
    residente_email: Optional[str] = None


# ==============================================================================
# ESQUEMAS DEL MÓDULO DE PAGOS
# ==============================================================================

class PaymentCreateRequest(BaseModel):
    """Datos para registrar un nuevo pago de cuota o alícuota."""
    monto: Decimal = Field(..., gt=0, decimal_places=2, description="Monto monetario a registrar")
    metodo: PaymentMethod = Field(..., description="Método de pago (TRANSFERENCIA, TARJETA, EFECTIVO)")
    comprobante_url: Optional[str] = Field(None, max_length=500, description="URL del comprobante adjunto")
    unit_id: Optional[uuid.UUID] = Field(None, description="UUID de la unidad (opcional si el residente tiene una asignada)")


class PaymentResponse(BaseModel):
    """Detalle del pago registrado en el sistema."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    unit_id: uuid.UUID
    monto_pagado: Decimal
    fecha_pago: datetime
    metodo: PaymentMethod
    comprobante_url: Optional[str] = None
    estado_validacion: PaymentValidationStatus
    notas_admin: Optional[str] = None


# ==============================================================================
# ESQUEMAS DE ESTADO DE CUENTA Y TAREAS FINANCIERAS
# ==============================================================================

class PendingObligationItem(BaseModel):
    """Detalle de una deuda u obligación pendiente o vencida."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    concepto: str
    tipo: ObligationType
    monto: Decimal
    fecha_emision: date
    fecha_vencimiento: date
    estado: ObligationStatus


class RecentPaymentItem(BaseModel):
    """Detalle resumido de un pago reciente."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    monto_pagado: Decimal
    fecha_pago: datetime
    metodo: PaymentMethod
    comprobante_url: Optional[str] = None
    estado_validacion: PaymentValidationStatus


class AccountStatementResponse(BaseModel):
    """Estado de cuenta consolidado para una unidad habitacional."""
    unit_id: uuid.UUID
    identificador: str
    coeficiente_copropiedad: float
    propietario_nombre: str
    residente_nombre: Optional[str] = None
    saldo_total_pendiente: Decimal
    total_obligaciones_pendientes: int
    obligaciones_pendientes: List[PendingObligationItem]
    ultimos_pagos: List[RecentPaymentItem]


class AlicuotasGenerationRequest(BaseModel):
    """Parámetros para gatillar la emisión masiva de alícuotas."""
    monto_base: Decimal = Field(..., gt=0, decimal_places=2, description="Presupuesto base mensual a distribuir")
    anio: Optional[int] = Field(None, ge=2020, le=2100, description="Año de facturación (opcional)")
    mes: Optional[int] = Field(None, ge=1, le=12, description="Mes de facturación (1-12, opcional)")


class AlicuotasGenerationResponse(BaseModel):
    """Resultado del proceso de emisión masiva de alícuotas."""
    periodo: str
    monto_base: Decimal
    unidades_procesadas: int
    total_generadas: int
    total_omitidas: int
    total_facturado: Decimal


class MultasApplicationRequest(BaseModel):
    """Parámetros para aplicar multas por mora."""
    porcentaje_multa: Decimal = Field(Decimal("10.00"), gt=0, le=100, description="Porcentaje de recargo")


class MultasApplicationResponse(BaseModel):
    """Resultado de la aplicación de multas."""
    fecha_corte: str
    porcentaje_multa: Decimal
    deudas_vencidas_procesadas: int
    total_multas_generadas: int
    total_multas_monto: Decimal
