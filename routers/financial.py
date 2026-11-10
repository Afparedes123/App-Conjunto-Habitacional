"""
Controlador Administrativo para Operaciones Financieras y Facturación.
Rutas:
- POST /api/finanzas/generar-alicuotas (Exclusivo Administrador)
- POST /api/finanzas/aplicar-multas (Exclusivo Administrador)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_admin
from models import User
from schemas import (
    AlicuotasGenerationRequest,
    AlicuotasGenerationResponse,
    MultasApplicationRequest,
    MultasApplicationResponse,
)
from services.financial_service import aplicar_multas_por_mora, generar_alicuotas_mensuales

router = APIRouter(prefix="/api/finanzas", tags=["Operaciones Financieras"])


@router.post(
    "/generar-alicuotas",
    response_model=AlicuotasGenerationResponse,
    status_code=status.HTTP_200_OK,
    summary="Gatillar emisión masiva de alícuotas (Exclusivo Administrador)",
)
def trigger_generar_alicuotas(
    payload: AlicuotasGenerationRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AlicuotasGenerationResponse:
    """
    Permite al administrador ejecutar o programar la emisión masiva de alícuotas.
    Calcula el valor en base a monto_base * coeficiente_copropiedad para cada unidad.
    """
    res = generar_alicuotas_mensuales(
        db=db,
        monto_base=payload.monto_base,
        anio=payload.anio,
        mes=payload.mes,
    )

    return AlicuotasGenerationResponse(
        periodo=res["periodo"],
        monto_base=res["monto_base"],
        unidades_procesadas=res["unidades_procesadas"],
        total_generadas=res["total_generadas"],
        total_omitidas=res["total_omitidas"],
        total_facturado=res["total_facturado"],
    )


@router.post(
    "/aplicar-multas",
    response_model=MultasApplicationResponse,
    status_code=status.HTTP_200_OK,
    summary="Gatillar corte y aplicación de multas por mora (Exclusivo Administrador)",
)
def trigger_aplicar_multas(
    payload: MultasApplicationRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MultasApplicationResponse:
    """
    Permite al administrador ejecutar el corte de mora:
    Busca alícuotas ordinarias vencidas, las marca como 'VENCIDA' y genera las obligaciones de MULTA.
    """
    res = aplicar_multas_por_mora(
        db=db,
        porcentaje_multa=payload.porcentaje_multa,
    )

    return MultasApplicationResponse(
        fecha_corte=res["fecha_corte"],
        porcentaje_multa=res["porcentaje_multa"],
        deudas_vencidas_procesadas=res["deudas_vencidas_procesadas"],
        total_multas_generadas=res["total_multas_generadas"],
        total_multas_monto=res["total_multas_monto"],
    )
