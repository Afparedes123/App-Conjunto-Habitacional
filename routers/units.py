"""
Controlador de Unidades Habitacionales y Estado de Cuenta.
Rutas:
- GET /api/unidades (Solo Administradores)
- GET /api/unidades/{unit_id}/estado-cuenta (Administradores o Residente titular)
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from database import get_db
from dependencies import get_current_user, require_admin
from models import FinancialObligation, ObligationStatus, Payment, Unit, User, UserRole
from schemas import (
    AccountStatementResponse,
    PendingObligationItem,
    RecentPaymentItem,
    UnitSummaryResponse,
)

router = APIRouter(tags=["Estructura del Condominio"])


@router.get(
    "/api/unidades",
    response_model=List[UnitSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar todas las unidades habitacionales (Exclusivo Administrador)",
)
def list_units(
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> List[UnitSummaryResponse]:
    """
    Ruta protegida exclusivamente para usuarios con rol 'ADMINISTRADOR'.
    Consulta la base de datos y devuelve todas las unidades habitacionales con su coeficiente
    y los datos descriptivos de sus respectivos propietarios y residentes.
    """
    stmt = (
        select(Unit)
        .options(
            joinedload(Unit.propietario),
            joinedload(Unit.residente),
        )
        .order_by(Unit.identificador)
    )
    units = db.scalars(stmt).unique().all()

    response: List[UnitSummaryResponse] = []
    for unit in units:
        response.append(
            UnitSummaryResponse(
                id=unit.id,
                identificador=unit.identificador,
                coeficiente_copropiedad=unit.coeficiente_copropiedad,
                propietario_id=unit.propietario_id,
                propietario_nombre=unit.propietario.nombre_completo,
                propietario_email=unit.propietario.email,
                residente_id=unit.residente_id,
                residente_nombre=unit.residente.nombre_completo if unit.residente else None,
                residente_email=unit.residente.email if unit.residente else None,
            )
        )

    return response


@router.get(
    "/api/unidades/{unit_id}/estado-cuenta",
    response_model=AccountStatementResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar estado de cuenta consolidado de una unidad habitacional",
)
def get_unit_account_statement(
    unit_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccountStatementResponse:
    """
    Obtiene el estado de cuenta financiero consolidado de una unidad habitacional.

    Políticas de Acceso (RBAC):
    - Administrador: Puede consultar el estado de cuenta de CUALQUIER unidad.
    - Residente: Solo puede consultar el estado de cuenta si es PROPIETARIO o RESIDENTE de esa unidad.
    - Otros roles (ej. Guardia): Acceso denegado (HTTP 403 Forbidden).

    Datos Devueltos:
    - Saldo total pendiente (deudas PENDIENTES y VENCIDAS).
    - Lista detallada de obligaciones pendientes/vencidas ordenadas por vencimiento.
    - Lista de los últimos 5 pagos realizados con su estado de validación.
    """
    # 1. Consultar la unidad habitacional con propietario y residente precargados (evita N+1)
    stmt_unit = (
        select(Unit)
        .options(
            joinedload(Unit.propietario),
            joinedload(Unit.residente),
        )
        .where(Unit.id == unit_id)
    )
    unit = db.scalar(stmt_unit)

    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unidad habitacional no encontrada",
        )

    # 2. Control granular de autorización
    if current_user.rol == UserRole.ADMINISTRADOR:
        # Administrador tiene acceso irrestricto
        pass
    elif current_user.rol == UserRole.RESIDENTE:
        # Residente solo si está vinculado como propietario o habitante
        is_owner = unit.propietario_id == current_user.id
        is_resident = unit.residente_id == current_user.id
        if not (is_owner or is_resident):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Privilegios insuficientes para consultar el estado de cuenta de esta unidad",
            )
    else:
        # Guardias u otros roles no tienen acceso a información financiera privada
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Privilegios insuficientes para consultar estados de cuenta",
        )

    # 3. Consultar obligaciones PENDIENTES o VENCIDAS (aprovecha índice idx_obligations_unit_estado)
    stmt_obligations = (
        select(FinancialObligation)
        .where(
            FinancialObligation.unit_id == unit.id,
            FinancialObligation.estado.in_([ObligationStatus.PENDIENTE, ObligationStatus.VENCIDA]),
        )
        .order_by(FinancialObligation.fecha_vencimiento.asc())
    )
    obligaciones_pendientes = db.scalars(stmt_obligations).all()

    # Cálculo seguro del saldo total acumulado
    saldo_total_pendiente = sum(
        (ob.monto for ob in obligaciones_pendientes), Decimal("0.00")
    )

    # 4. Consultar los últimos 5 pagos (aprovecha índice idx_payments_unit_fecha)
    stmt_payments = (
        select(Payment)
        .where(Payment.unit_id == unit.id)
        .order_by(Payment.fecha_pago.desc())
        .limit(5)
    )
    ultimos_pagos = db.scalars(stmt_payments).all()

    return AccountStatementResponse(
        unit_id=unit.id,
        identificador=unit.identificador,
        coeficiente_copropiedad=unit.coeficiente_copropiedad,
        propietario_nombre=unit.propietario.nombre_completo,
        residente_nombre=unit.residente.nombre_completo if unit.residente else None,
        saldo_total_pendiente=saldo_total_pendiente,
        total_obligaciones_pendientes=len(obligaciones_pendientes),
        obligaciones_pendientes=[
            PendingObligationItem.model_validate(ob) for ob in obligaciones_pendientes
        ],
        ultimos_pagos=[
            RecentPaymentItem.model_validate(p) for p in ultimos_pagos
        ],
    )
