"""
Controlador del Módulo Financiero (Pagos).
Rutas:
- POST /api/pagos (Solo Residentes)
"""

from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_residente
from models import Payment, PaymentValidationStatus, Unit, User
from schemas import PaymentCreateRequest, PaymentResponse

router = APIRouter(tags=["Módulo Financiero"])


@router.post(
    "/api/pagos",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un pago de alícuota o cuota (Exclusivo Residente)",
)
def create_payment(
    payment_in: PaymentCreateRequest,
    current_residente: User = Depends(require_residente),
    db: Session = Depends(get_db),
) -> PaymentResponse:
    """
    Ruta protegida exclusivamente para usuarios con rol 'RESIDENTE'.
    Registra una nueva transacción de pago asociada a la unidad habitacional del residente solicitante.
    El estado inicial del pago se fija en 'EN_REVISION' para auditoría administrativa.
    """
    # 1. Determinar y validar la unidad correspondiente al residente
    if payment_in.unit_id:
        # Si especifica una unidad, validamos que pertenezca al usuario (como residente o propietario)
        unit = db.scalar(
            select(Unit).where(
                Unit.id == payment_in.unit_id,
                or_(
                    Unit.residente_id == current_residente.id,
                    Unit.propietario_id == current_residente.id,
                ),
            )
        )
        if not unit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La unidad habitacional indicada no existe o no está vinculada a su cuenta",
            )
    else:
        # Búsqueda automática de la unidad donde reside habitualmente
        unit = db.scalar(
            select(Unit).where(
                or_(
                    Unit.residente_id == current_residente.id,
                    Unit.propietario_id == current_residente.id,
                )
            )
        )
        if not unit:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El residente no tiene ninguna unidad habitacional asignada actualmente",
            )

    # 2. Instanciar y persistir el nuevo pago
    new_payment = Payment(
        unit_id=unit.id,
        monto_pagado=payment_in.monto,
        fecha_pago=datetime.now(timezone.utc),
        metodo=payment_in.metodo,
        comprobante_url=payment_in.comprobante_url,
        estado_validacion=PaymentValidationStatus.EN_REVISION,
        notas_admin=f"Registrado por residente: {current_residente.nombre_completo}",
    )

    db.add(new_payment)
    db.commit()
    db.refresh(new_payment)

    return PaymentResponse.model_validate(new_payment)
