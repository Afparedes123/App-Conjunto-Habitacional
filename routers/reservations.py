"""
Controlador de Convivencia y Motor de Reservas de Áreas Comunales.
Rutas:
- POST /api/reservas (Creación con validación cruzada financiera y de solapamiento)
- GET  /api/reservas/areas (Catálogo de áreas comunales disponibles)
- GET  /api/reservas/calendario (Franjas ocupadas para visualización en calendario)
- GET  /api/reservas (Historial de reservas de la unidad del residente)
- GET  /api/reservas/interfaz (Interfaz web de reservas para el residente)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from database import get_db
from dependencies import get_current_user, require_residente
from models import (
    CommonArea,
    FinancialObligation,
    ObligationStatus,
    Reservation,
    ReservationStatus,
    Unit,
    User,
)
from schemas import (
    CommonAreaResponse,
    ReservationCalendarSlot,
    ReservationCreateRequest,
    ReservationResponse,
)

router = APIRouter(prefix="/api/reservas", tags=["Módulo de Convivencia y Reservas"])


# ==============================================================================
# 1. CATÁLOGO DE ÁREAS COMUNALES Y DISPONIBILIDAD
# ==============================================================================

@router.get(
    "/areas",
    response_model=List[CommonAreaResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar áreas comunales disponibles para reserva",
)
def list_common_areas(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[CommonAreaResponse]:
    """
    Retorna el catálogo completo de áreas comunes (Piscina, BBQ, Salón Comunal, Cancha)
    con su aforo máximo y costo de alquiler.
    """
    areas = db.scalars(select(CommonArea).order_by(CommonArea.nombre)).all()
    return [CommonAreaResponse.model_validate(area) for area in areas]


@router.get(
    "/calendario",
    response_model=List[ReservationCalendarSlot],
    status_code=status.HTTP_200_OK,
    summary="Consultar franjas horarias ocupadas de un área comunal",
)
def get_area_calendar_slots(
    area_id: uuid.UUID = Query(..., description="ID del área comunal"),
    fecha_desde: Optional[datetime] = Query(None, description="Fecha de inicio de rango"),
    fecha_hasta: Optional[datetime] = Query(None, description="Fecha de fin de rango"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[ReservationCalendarSlot]:
    """
    Devuelve las reservas activas (SOLICITADA o APROBADA) para pintar franjas ocupadas en el calendario.
    """
    now = datetime.now(timezone.utc)
    desde = fecha_desde or now

    conditions = [
        Reservation.area_id == area_id,
        Reservation.estado.in_([ReservationStatus.SOLICITADA, ReservationStatus.APROBADA]),
        Reservation.fecha_hora_fin >= desde,
    ]
    if fecha_hasta:
        conditions.append(Reservation.fecha_hora_inicio <= fecha_hasta)

    stmt = select(Reservation).where(*conditions).order_by(Reservation.fecha_hora_inicio.asc())
    reservas = db.scalars(stmt).all()

    return [
        ReservationCalendarSlot(
            id=r.id,
            area_id=r.area_id,
            fecha_hora_inicio=r.fecha_hora_inicio,
            fecha_hora_fin=r.fecha_hora_fin,
            estado=r.estado,
        )
        for r in reservas
    ]


@router.get(
    "",
    response_model=List[ReservationResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar reservas de la unidad del residente autenticado",
)
def list_my_reservations(
    current_residente: User = Depends(require_residente),
    db: Session = Depends(get_db),
) -> List[ReservationResponse]:
    """
    Retorna el historial y estado de solicitudes de reserva pertenecientes a la unidad del residente.
    """
    # Buscar unidades asociadas al residente
    stmt_units = select(Unit.id).where(
        or_(
            Unit.residente_id == current_residente.id,
            Unit.propietario_id == current_residente.id,
        )
    )
    unit_ids = db.scalars(stmt_units).all()
    if not unit_ids:
        return []

    stmt_res = (
        select(Reservation)
        .options(joinedload(Reservation.unit), joinedload(Reservation.area))
        .where(Reservation.unit_id.in_(unit_ids))
        .order_by(Reservation.fecha_hora_inicio.desc())
    )
    reservas = db.scalars(stmt_res).unique().all()

    return [
        ReservationResponse(
            id=r.id,
            unit_id=r.unit_id,
            unit_identificador=r.unit.identificador,
            area_id=r.area_id,
            area_nombre=r.area.nombre,
            fecha_hora_inicio=r.fecha_hora_inicio,
            fecha_hora_fin=r.fecha_hora_fin,
            estado=r.estado,
            costo_reserva=r.area.costo_reserva,
            requiere_aprobacion=r.area.requiere_aprobacion,
        )
        for r in reservas
    ]


# ==============================================================================
# 2. VALIDACIÓN CRUZADA Y CREACIÓN DE RESERVA (MOTOR PRINCIPAL)
# ==============================================================================

@router.post(
    "",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Solicitar reserva de área comunal con validación cruzada financiera y de horarios",
)
def create_reservation(
    payload: ReservationCreateRequest,
    current_residente: User = Depends(require_residente),
    db: Session = Depends(get_db),
):
    """
    Motor de Reservas con validación cruzada:
    1. Localiza la unidad habitacional del residente.
    2. Validación Financiera (Bloqueo a Morosos):
       - Consulta deudas en estado 'VENCIDA' u obligaciones 'PENDIENTE' con fecha vencida expirada.
       - Si la sumatoria es > $0, aborta y retorna HTTP 403 con mensaje de morosidad.
    3. Validación de Disponibilidad (Overlapping):
       - Consulta si existe colisión de horario en el área solicitada.
       - Si hay traslape, aborta y retorna HTTP 409 (Conflict).
    4. Creación Exitosa:
       - Fija estado en 'SOLICITADA' (o 'APROBADA' si el área no requiere visto bueno manual).
       - Retorna HTTP 201 Created.
    """
    now = datetime.now(timezone.utc)
    today = now.date()

    # 1. Determinar y validar la unidad del residente
    if payload.unit_id:
        unit = db.scalar(
            select(Unit).where(
                Unit.id == payload.unit_id,
                or_(
                    Unit.residente_id == current_residente.id,
                    Unit.propietario_id == current_residente.id,
                ),
            )
        )
        if not unit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La unidad indicada no existe o no está vinculada a su cuenta",
            )
    else:
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

    # 2. VALIDACIÓN FINANCIERA (BLOQUEO A MOROSOS)
    # Busca obligaciones VENCIDAS o PENDIENTES cuya fecha límite ya haya expirado
    stmt_deudas = select(FinancialObligation).where(
        FinancialObligation.unit_id == unit.id,
        or_(
            FinancialObligation.estado == ObligationStatus.VENCIDA,
            and_(
                FinancialObligation.estado == ObligationStatus.PENDIENTE,
                FinancialObligation.fecha_vencimiento < today,
            ),
        ),
    )
    deudas_morosas = db.scalars(stmt_deudas).all()
    total_deuda_morosa = sum((d.monto for d in deudas_morosas), Decimal("0.00"))

    if total_deuda_morosa > Decimal("0.00"):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": "Acceso restringido por morosidad. Por favor, ponga al día sus obligaciones para reservar áreas comunes.",
                "detail": "Acceso restringido por morosidad. Por favor, ponga al día sus obligaciones para reservar áreas comunes.",
                "deuda_total": float(total_deuda_morosa),
                "obligaciones_en_mora": len(deudas_morosas),
            },
        )

    # 3. Validar existencia del Área Comunal
    area = db.scalar(select(CommonArea).where(CommonArea.id == payload.area_id))
    if not area:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Área comunal no encontrada",
        )

    # 4. Validar coherencia temporal del rango solicitado
    inicio = payload.fecha_hora_inicio
    fin = payload.fecha_hora_fin

    # Normalizar zonas horarias si vienen sin tz
    if inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=timezone.utc)
    if fin.tzinfo is None:
        fin = fin.replace(tzinfo=timezone.utc)

    if fin <= inicio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha y hora de finalización debe ser posterior a la de inicio",
        )

    # 5. VALIDACIÓN DE DISPONIBILIDAD (OVERLAPPING / COLISIÓN DE HORARIOS)
    # Condición matemática de solapamiento de intervalos [A, B] y [C, D]:
    # A < D AND B > C
    stmt_overlap = select(Reservation).where(
        Reservation.area_id == area.id,
        Reservation.estado.in_([ReservationStatus.SOLICITADA, ReservationStatus.APROBADA]),
        Reservation.fecha_hora_inicio < fin,
        Reservation.fecha_hora_fin > inicio,
    )
    conflicto = db.scalar(stmt_overlap)

    if conflicto:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "El área comunal ya se encuentra reservada en el horario seleccionado. Por favor, elija otro horario.",
                "detail": "El área comunal ya se encuentra reservada en el horario seleccionado. Por favor, elija otro horario.",
                "conflicto_inicio": conflicto.fecha_hora_inicio.isoformat(),
                "conflicto_fin": conflicto.fecha_hora_fin.isoformat(),
            },
        )

    # 6. ÉXITO: Determinar estado inicial según política del área
    estado_inicial = (
        ReservationStatus.SOLICITADA if area.requiere_aprobacion else ReservationStatus.APROBADA
    )

    nueva_reserva = Reservation(
        unit_id=unit.id,
        area_id=area.id,
        fecha_hora_inicio=inicio,
        fecha_hora_fin=fin,
        estado=estado_inicial,
    )

    db.add(nueva_reserva)
    db.commit()
    db.refresh(nueva_reserva)

    return ReservationResponse(
        id=nueva_reserva.id,
        unit_id=unit.id,
        unit_identificador=unit.identificador,
        area_id=area.id,
        area_nombre=area.nombre,
        fecha_hora_inicio=nueva_reserva.fecha_hora_inicio,
        fecha_hora_fin=nueva_reserva.fecha_hora_fin,
        estado=nueva_reserva.estado,
        costo_reserva=area.costo_reserva,
        requiere_aprobacion=area.requiere_aprobacion,
    )


# ==============================================================================
# 3. INTERFAZ WEB DEL RESIDENTE
# ==============================================================================

@router.get(
    "/interfaz",
    response_class=HTMLResponse,
    include_in_schema=False,
    summary="Interfaz web para reservas de residentes",
)
def get_reservations_view() -> HTMLResponse:
    """Sirve la interfaz web SPA para que el residente reserve áreas comunales."""
    html_file = Path(__file__).resolve().parent.parent / "static" / "reservas.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Módulo de reservas no disponible</h1>", status_code=404)
