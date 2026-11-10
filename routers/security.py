"""
Controlador de Seguridad y Control de Acceso en Garita.
Rutas:
- POST /api/seguridad/generar-pase (Exclusivo Residente)
- POST /api/seguridad/validar-pase (Exclusivo Guardia de Seguridad)
"""

from __future__ import annotations

import base64
import io
import uuid
from datetime import datetime, timezone
from pathlib import Path

import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from database import get_db
from dependencies import require_guardia, require_residente
from models import AccessLog, QRPass, QRPassStatus, Unit, User
from schemas import (
    QRPassCreateRequest,
    QRPassResponse,
    QRPassValidateRequest,
    QRPassValidateResponse,
)

router = APIRouter(prefix="/api/seguridad", tags=["Seguridad y Control de Acceso"])


def generate_qr_base64(data: str) -> str:
    """
    Genera un código QR de alta legibilidad y lo codifica en un Data URL Base64 (PNG).
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=3,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    b64_encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64_encoded}"


# ==============================================================================
# 1. GENERACIÓN DEL PASE QR (RESIDENTE)
# ==============================================================================

@router.post(
    "/generar-pase",
    response_model=QRPassResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generar un nuevo pase de visita con código QR (Exclusivo Residente)",
)
def create_qr_pass(
    payload: QRPassCreateRequest,
    current_residente: User = Depends(require_residente),
    db: Session = Depends(get_db),
) -> QRPassResponse:
    """
    Permite al residente emitir un pase digital de acceso para visitas.
    Genera un token criptográfico único, persiste el registro en `QRPass`
    y retorna la imagen del QR codificada en Base64 para compartir por WhatsApp/Email.
    """
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
                detail="La unidad especificada no existe o no está vinculada a su cuenta",
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

    now = datetime.now(timezone.utc)
    inicio = payload.fecha_hora_inicio if payload.fecha_hora_inicio else now

    # Normalizar zonas horarias si vienen naive
    if payload.fecha_hora_fin.tzinfo is None:
        fin = payload.fecha_hora_fin.replace(tzinfo=timezone.utc)
    else:
        fin = payload.fecha_hora_fin

    if fin <= inicio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha y hora de finalización debe ser posterior a la de inicio",
        )

    # 2. Generar identificador único criptográfico para el código QR
    qr_token = uuid.uuid4().hex

    # 3. Crear registro en base de datos
    new_pass = QRPass(
        unit_id=unit.id,
        nombre_visitante=payload.nombre_visitante.strip(),
        tipo_visita=payload.tipo_visita,
        hash_qr=qr_token,
        fecha_hora_inicio=inicio,
        fecha_hora_fin=fin,
        estado=QRPassStatus.ACTIVO,
    )

    db.add(new_pass)
    db.commit()
    db.refresh(new_pass)

    # 4. Generar imagen del QR en base64
    qr_image_data_url = generate_qr_base64(qr_token)

    return QRPassResponse(
        id=new_pass.id,
        unit_id=unit.id,
        unit_identificador=unit.identificador,
        nombre_visitante=new_pass.nombre_visitante,
        tipo_visita=new_pass.tipo_visita,
        hash_qr=new_pass.hash_qr,
        fecha_hora_inicio=new_pass.fecha_hora_inicio,
        fecha_hora_fin=new_pass.fecha_hora_fin,
        estado=new_pass.estado,
        qr_image_base64=qr_image_data_url,
    )


# ==============================================================================
# 2. VALIDACIÓN EN GARITA (GUARDIA)
# ==============================================================================

@router.post(
    "/validar-pase",
    response_model=QRPassValidateResponse,
    status_code=status.HTTP_200_OK,
    summary="Validar código QR en garita y registrar bitácora (Exclusivo Guardia)",
)
def validate_qr_pass(
    payload: QRPassValidateRequest,
    current_guard: User = Depends(require_guardia),
    db: Session = Depends(get_db),
) -> QRPassValidateResponse:
    """
    Ruta consumida por la tablet o lector de garita del guardia de seguridad:
    1. Busca el hash_qr en la tabla QRPass mediante índice B-tree rápido O(1).
    2. Valida vigencia temporal y estado de un solo uso.
    3. Si es válido: Marca como 'USADO', crea un 'AccessLog' de auditoría y concede acceso.
    4. Si es inválido/expirado: Retorna HTTP 403 o HTTP 404 detallado.
    """
    clean_hash = payload.hash_qr.strip()

    # 1. Búsqueda indexada con la unidad precargada para evitar consultas N+1
    stmt = (
        select(QRPass)
        .options(joinedload(QRPass.unit))
        .where(QRPass.hash_qr == clean_hash)
    )
    qr_pass = db.scalar(stmt)

    # 2. Si no existe -> 404 Not Found
    if not qr_pass:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pase no encontrado",
        )

    now = datetime.now(timezone.utc)

    # Asegurar compatibilidad de zonas horarias
    fin_tz = qr_pass.fecha_hora_fin
    if fin_tz.tzinfo is None:
        fin_tz = fin_tz.replace(tzinfo=timezone.utc)

    inicio_tz = qr_pass.fecha_hora_inicio
    if inicio_tz.tzinfo is None:
        inicio_tz = inicio_tz.replace(tzinfo=timezone.utc)

    # 3. Validar estado y expiración temporal
    if qr_pass.estado == QRPassStatus.USADO:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pase expirado o ya utilizado",
        )

    if qr_pass.estado == QRPassStatus.EXPIRADO or now > fin_tz:
        # Transicionar estado a EXPIRADO si aún no lo estaba
        if qr_pass.estado != QRPassStatus.EXPIRADO:
            qr_pass.estado = QRPassStatus.EXPIRADO
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pase expirado o ya utilizado",
        )

    if now < inicio_tz:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El pase aún no está vigente para ingreso",
        )

    # 4. Transicionar estado del pase a USADO
    qr_pass.estado = QRPassStatus.USADO

    # 5. Crear registro histórico de auditoría en la bitácora de garita
    cedula_final = (payload.cedula_visitante.strip() if payload.cedula_visitante else None) or "VALIDADO_QR"

    access_log = AccessLog(
        qr_pass_id=qr_pass.id,
        guard_id=current_guard.id,
        unit_id=qr_pass.unit_id,
        cedula_visitante=cedula_final,
        placa_vehiculo=payload.placa_vehiculo.strip().upper() if payload.placa_vehiculo else None,
        fecha_hora_ingreso=now,
        fecha_hora_salida=None,
    )

    db.add(access_log)
    db.commit()
    db.refresh(access_log)

    return QRPassValidateResponse(
        mensaje="ACCESO PERMITIDO",
        acceso_permitido=True,
        nombre_visitante=qr_pass.nombre_visitante,
        unidad_destino=qr_pass.unit.identificador,
        tipo_visita=qr_pass.tipo_visita,
        fecha_hora_ingreso=access_log.fecha_hora_ingreso,
        guardia_nombre=current_guard.nombre_completo,
        access_log_id=access_log.id,
    )


# ==============================================================================
# 3. INTERFAZ WEB DEL ESCÁNER PARA TABLETS
# ==============================================================================

@router.get(
    "/escaner",
    response_class=HTMLResponse,
    include_in_schema=False,
    summary="Interfaz web de garita para escáner de códigos QR",
)
def get_guard_scanner_view() -> HTMLResponse:
    """
    Sirve la Single Page Application de la tablet de garita con soporte para cámara
    y visualización de estados en pantalla completa.
    """
    html_file = Path(__file__).resolve().parent.parent / "static" / "scanner.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Visor de garita no encontrado</h1>", status_code=404)
