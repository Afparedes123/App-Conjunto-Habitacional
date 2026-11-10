"""
Esquemas de Validación y Serialización (Pydantic v2).
Garantizan tipado estricto en la entrada y salida de los endpoints de la API REST.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from models import PaymentMethod, PaymentValidationStatus, UserRole


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
