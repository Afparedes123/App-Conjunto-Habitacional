"""
Servicio Financiero y Motor de Facturación para Condominios.
Contiene la lógica de negocio para:
1. Generación masiva mensual de alícuotas (Día 1 de cada mes).
2. Cálculo de morosidad y aplicación de multas por recargo (Día 11 de cada mes).
Incluye soporte para transacciones ACID seguras y ejecución vía CLI/CRON.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional

# Garantizar que el directorio raíz del proyecto esté en sys.path al ejecutarse directamente
ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import FinancialObligation, ObligationStatus, ObligationType, Unit

NOMBRES_MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]


# ==============================================================================
# 1. TAREA AUTOMÁTICA: GENERACIÓN MASIVA DE ALÍCUOTAS (DÍA 1)
# ==============================================================================

def generar_alicuotas_mensuales(
    db: Session,
    monto_base: Decimal,
    anio: Optional[int] = None,
    mes: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Genera masivamente las obligaciones de alícuota ordinaria para todas las unidades activas.
    Pensada para ejecutarse automáticamente el día 1 de cada mes.

    Reglas de Negocio:
    - Valor a pagar = monto_base * coeficiente_copropiedad (redondeado a 2 decimales bancarios).
    - Fecha de emisión: Día 1 del mes indicado.
    - Fecha de vencimiento: Día 10 del mes en curso.
    - Tipo: 'ORDINARIA', Estado inicial: 'PENDIENTE'.
    - Idempotencia: Si una unidad ya tiene emitida su alícuota ordinaria para el periodo,
      se omite para evitar cobros dobles en reintentos.
    - Seguridad Transaccional: db.commit() atómico al final con db.rollback() ante cualquier excepción.
    """
    hoy = date.today()
    target_year = anio if anio is not None else hoy.year
    target_month = mes if mes is not None else hoy.month

    if not (1 <= target_month <= 12):
        raise ValueError(f"Mes inválido: {target_month}. Debe estar comprendido entre 1 y 12.")

    fecha_emision = date(target_year, target_month, 1)
    fecha_vencimiento = date(target_year, target_month, 10)
    nombre_mes = NOMBRES_MESES[target_month - 1]
    concepto_periodo = f"Alícuota Ordinaria - {nombre_mes} {target_year}"

    try:
        # 1. Consultar todas las unidades habitacionales
        stmt_units = select(Unit).order_by(Unit.identificador)
        units = db.scalars(stmt_units).all()

        if not units:
            return {
                "periodo": f"{target_year}-{target_month:02d}",
                "monto_base": monto_base,
                "unidades_procesadas": 0,
                "total_generadas": 0,
                "obligaciones_generadas": [],
                "total_omitidas": 0,
                "unidades_omitidas": [],
                "total_facturado": Decimal("0.00"),
            }

        # 2. Consultar alícuotas ordinarias ya existentes en este periodo para garantizar IDEMPOTENCIA
        stmt_existentes = select(FinancialObligation.unit_id).where(
            FinancialObligation.tipo == ObligationType.ORDINARIA,
            FinancialObligation.fecha_emision == fecha_emision,
        )
        unidades_con_alicuota = set(db.scalars(stmt_existentes).all())

        nuevas_obligaciones: List[FinancialObligation] = []
        unidades_omitidas: List[str] = []
        total_facturado = Decimal("0.00")

        # 3. Calcular e instanciar cada alícuota
        for unit in units:
            if unit.id in unidades_con_alicuota:
                unidades_omitidas.append(unit.identificador)
                continue

            # Conversión segura a Decimal para cálculo financiero de alta precisión
            coeficiente_dec = Decimal(str(unit.coeficiente_copropiedad))
            monto_calculado = (monto_base * coeficiente_dec).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Si el monto calculado es 0 o negativo, fijar mínimo configurable o preservar valor
            if monto_calculado < Decimal("0.00"):
                monto_calculado = Decimal("0.00")

            obligacion = FinancialObligation(
                unit_id=unit.id,
                tipo=ObligationType.ORDINARIA,
                concepto=concepto_periodo,
                monto=monto_calculado,
                fecha_emision=fecha_emision,
                fecha_vencimiento=fecha_vencimiento,
                estado=ObligationStatus.PENDIENTE,
            )
            nuevas_obligaciones.append(obligacion)
            total_facturado += monto_calculado

        if nuevas_obligaciones:
            db.add_all(nuevas_obligaciones)

        # 4. Transacción atómica
        db.commit()

        # Refrescar IDs para uso posterior
        for obligacion in nuevas_obligaciones:
            db.refresh(obligacion)

        return {
            "periodo": f"{target_year}-{target_month:02d}",
            "monto_base": monto_base,
            "unidades_procesadas": len(units),
            "total_generadas": len(nuevas_obligaciones),
            "obligaciones_generadas": nuevas_obligaciones,
            "total_omitidas": len(unidades_omitidas),
            "unidades_omitidas": unidades_omitidas,
            "total_facturado": total_facturado,
        }

    except Exception as exc:
        db.rollback()
        raise RuntimeError(f"Error durante la facturación masiva de alícuotas: {exc}") from exc


# ==============================================================================
# 2. TAREA AUTOMÁTICA: CÁLCULO DE MOROSIDAD Y MULTAS (DÍA 11)
# ==============================================================================

def aplicar_multas_por_mora(
    db: Session,
    porcentaje_multa: Decimal,
    fecha_corte: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Identifica deudas ordinarias pendientes vencidas, las marca como 'VENCIDA'
    y genera automáticamente una nueva obligación de tipo 'MULTA'.
    Pensada para ejecutarse automáticamente el día 11 de cada mes.

    Reglas de Negocio:
    - Busca obligaciones tipo 'ORDINARIA' en estado 'PENDIENTE' con fecha_vencimiento < fecha_corte.
    - Por cada deuda vencida:
      * Cambia su estado a 'VENCIDA' para reflejar el corte contable.
      * Crea una obligación tipo 'MULTA' = deuda.monto * (porcentaje_multa / 100).
    - Idempotencia: Verifica que no se aplique más de una multa por mora sobre la misma obligación.
    - Seguridad Transaccional: db.commit() atómico y db.rollback() en fallos.
    """
    corte = fecha_corte if fecha_corte is not None else date.today()

    if porcentaje_multa <= Decimal("0.00"):
        raise ValueError(f"El porcentaje de multa debe ser positivo: {porcentaje_multa}")

    try:
        # 1. Buscar todas las obligaciones ORDINARIAS pendientes cuya fecha de vencimiento ya expiró
        stmt_mora = (
            select(FinancialObligation)
            .where(
                FinancialObligation.tipo == ObligationType.ORDINARIA,
                FinancialObligation.estado == ObligationStatus.PENDIENTE,
                FinancialObligation.fecha_vencimiento < corte,
            )
            .order_by(FinancialObligation.fecha_vencimiento.asc())
        )
        deudas_vencidas = db.scalars(stmt_mora).all()

        if not deudas_vencidas:
            return {
                "fecha_corte": corte.isoformat(),
                "porcentaje_multa": porcentaje_multa,
                "deudas_vencidas_procesadas": 0,
                "total_multas_generadas": 0,
                "multas_generadas": [],
                "total_multas_monto": Decimal("0.00"),
            }

        multas_creadas: List[FinancialObligation] = []
        total_multas = Decimal("0.00")

        # 2. Procesar cada deuda vencida
        for deuda in deudas_vencidas:
            concepto_multa = f"Multa por mora ({porcentaje_multa}%) - {deuda.concepto}"

            # Control de idempotencia: Verificar si ya existe una multa previa asociada a este concepto y unidad
            stmt_existe_multa = select(FinancialObligation).where(
                FinancialObligation.unit_id == deuda.unit_id,
                FinancialObligation.tipo == ObligationType.MULTA,
                FinancialObligation.concepto == concepto_multa,
            )
            multa_previa = db.scalar(stmt_existe_multa)
            if multa_previa:
                # Ya fue multada previamente, solo aseguramos que el estado esté VENCIDA
                deuda.estado = ObligationStatus.VENCIDA
                continue

            # Calcular monto de la multa
            monto_multa = (deuda.monto * (porcentaje_multa / Decimal("100"))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Fecha de vencimiento para la multa (por defecto 10 días tras su emisión)
            vencimiento_multa = corte + timedelta(days=10)

            nueva_multa = FinancialObligation(
                unit_id=deuda.unit_id,
                tipo=ObligationType.MULTA,
                concepto=concepto_multa,
                monto=monto_multa,
                fecha_emision=corte,
                fecha_vencimiento=vencimiento_multa,
                estado=ObligationStatus.PENDIENTE,
            )

            # Actualizar estado de la deuda original a VENCIDA
            deuda.estado = ObligationStatus.VENCIDA

            multas_creadas.append(nueva_multa)
            total_multas += monto_multa

        if multas_creadas:
            db.add_all(multas_creadas)

        # 3. Transacción atómica
        db.commit()

        for multa in multas_creadas:
            db.refresh(multa)

        return {
            "fecha_corte": corte.isoformat(),
            "porcentaje_multa": porcentaje_multa,
            "deudas_vencidas_procesadas": len(deudas_vencidas),
            "total_multas_generadas": len(multas_creadas),
            "multas_generadas": multas_creadas,
            "total_multas_monto": total_multas,
        }

    except Exception as exc:
        db.rollback()
        raise RuntimeError(f"Error durante el cálculo y aplicación de multas: {exc}") from exc


# ==============================================================================
# EJECUCIÓN COMO COMANDO CLI / CRON JOB NATIVO
# ==============================================================================

if __name__ == "__main__":
    from database import SessionLocal, engine
    from models import Base

    Base.metadata.create_all(bind=engine)

    parser = argparse.ArgumentParser(description="Motor de Facturación y Cobranza de Condominios")
    parser.add_argument("--tarea", choices=["alicuotas", "multas"], required=True, help="Tarea a ejecutar")
    parser.add_argument("--monto-base", type=float, default=1000.0, help="Monto base total de presupuesto para alícuotas")
    parser.add_argument("--porcentaje-multa", type=float, default=10.0, help="Porcentaje de recargo por mora")
    parser.add_argument("--anio", type=int, default=None, help="Año de facturación")
    parser.add_argument("--mes", type=int, default=None, help="Mes de facturación (1-12)")

    args = parser.parse_args()

    with SessionLocal() as session:
        if args.tarea == "alicuotas":
            print(f">> Iniciando generación masiva de alícuotas (Monto base: ${args.monto_base:.2f})...")
            res = generar_alicuotas_mensuales(
                session,
                monto_base=Decimal(str(args.monto_base)),
                anio=args.anio,
                mes=args.mes,
            )
            print(f"   ✓ Periodo: {res['periodo']}")
            print(f"   ✓ Alícuotas generadas: {res['total_generadas']}")
            print(f"   ✓ Omitidas (ya facturadas): {res['total_omitidas']}")
            print(f"   ✓ Total facturado: ${res['total_facturado']:.2f}")

        elif args.tarea == "multas":
            print(f">> Iniciando aplicación de multas por mora ({args.porcentaje_multa}%)...")
            res = generar_multas = aplicar_multas_por_mora(
                session,
                porcentaje_multa=Decimal(str(args.porcentaje_multa)),
            )
            print(f"   ✓ Deudas vencidas procesadas: {res['deudas_vencidas_procesadas']}")
            print(f"   ✓ Multas generadas: {res['total_multas_generadas']}")
            print(f"   ✓ Total multas aplicadas: ${res['total_multas_monto']:.2f}")
