"""
Controlador de Unidades Habitacionales.
Rutas:
- GET /api/unidades (Solo Administradores)
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from database import get_db
from dependencies import require_admin
from models import Unit, User
from schemas import UnitSummaryResponse

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
