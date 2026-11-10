"""
Módulo de Programación de Tareas Recurrentes (Schedulers / CRON).
Explica y demuestra cómo orquestar las tareas financieras:
- Tarea 1: Generación masiva de alícuotas el día 1 de cada mes a las 00:05.
- Tarea 2: Aplicación de multas por morosidad el día 11 de cada mes a las 00:05.

Estrategias disponibles:
1. APScheduler (In-Process dentro de FastAPI).
2. Celery + Celery Beat (Distribuido para producción SaaS).
3. Linux CRON nativo (CLI Runner).
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import SessionLocal
from services.financial_service import aplicar_multas_por_mora, generar_alicuotas_mensuales

logger = logging.getLogger("condo.scheduler")
logging.basicConfig(level=logging.INFO)

# Instancia global de APScheduler
scheduler = BackgroundScheduler(timezone="UTC")


# ==============================================================================
# ENVOLTORIOS DE TAREAS PARA EL PLANIFICADOR (JOBS)
# ==============================================================================

def job_generar_alicuotas_mensuales() -> None:
    """
    Job programado para el día 1 de cada mes a las 00:05 UTC.
    Gatilla la facturación proporcional para todas las unidades activas.
    """
    logger.info(">> [CRON JOB] Iniciando tarea programada: Generación masiva de alícuotas...")
    presupuesto_base = Decimal(os.getenv("PRESUPUESTO_MENSUAL_BASE", "2500.00"))

    with SessionLocal() as db:
        try:
            resultado = generar_alicuotas_mensuales(db, monto_base=presupuesto_base)
            logger.info(
                ">> [CRON JOB] Alícuotas generadas con éxito para periodo %s. Total: %d, Monto: $%s",
                resultado["periodo"],
                resultado["total_generadas"],
                resultado["total_facturado"],
            )
        except Exception as exc:
            logger.error(">> [CRON JOB ERROR] Fallo al generar alícuotas: %s", exc, exc_info=True)


def job_aplicar_multas_mora() -> None:
    """
    Job programado para el día 11 de cada mes a las 00:05 UTC.
    Aplica el recargo por mora a las cuotas ordinarias no pagadas al vencimiento (día 10).
    """
    logger.info(">> [CRON JOB] Iniciando tarea programada: Aplicación de multas por mora...")
    porcentaje = Decimal(os.getenv("PORCENTAJE_MULTA_MORA", "10.00"))  # 10% de recargo estándar

    with SessionLocal() as db:
        try:
            resultado = aplicar_multas_por_mora(db, porcentaje_multa=porcentaje)
            logger.info(
                ">> [CRON JOB] Multas aplicadas con éxito. Vencidas: %d, Multas creadas: %d, Total: $%s",
                resultado["deudas_vencidas_procesadas"],
                resultado["total_multas_generadas"],
                resultado["total_multas_monto"],
            )
        except Exception as exc:
            logger.error(">> [CRON JOB ERROR] Fallo al aplicar multas: %s", exc, exc_info=True)


# ==============================================================================
# CONFIGURACIÓN Y ARRANQUE DE APSCHEDULER
# ==============================================================================

def start_scheduler() -> BackgroundScheduler:
    """
    Registra los triggers CRON y arranca el scheduler en segundo plano.
    
    Reglas de temporización:
    - Alícuotas: Día 1 de cada mes a las 00:05 UTC (cron: minute=5, hour=0, day=1)
    - Multas:    Día 11 de cada mes a las 00:05 UTC (cron: minute=5, hour=0, day=11)
    """
    if scheduler.running:
        return scheduler

    # 1. Alícuotas: Día 1 de cada mes a las 00:05
    scheduler.add_job(
        job_generar_alicuotas_mensuales,
        trigger=CronTrigger(day=1, hour=0, minute=5),
        id="generar_alicuotas_mensuales_job",
        name="Generación Mensual de Alícuotas",
        replace_existing=True,
    )

    # 2. Multas: Día 11 de cada mes a las 00:05 (post-vencimiento del día 10)
    scheduler.add_job(
        job_aplicar_multas_mora,
        trigger=CronTrigger(day=11, hour=0, minute=5),
        id="aplicar_multas_mora_job",
        name="Aplicación de Multas por Mora",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(">> [SCHEDULER] APScheduler iniciado correctamente con 2 jobs registrados.")
    return scheduler


def shutdown_scheduler() -> None:
    """Detiene limpiamente el scheduler al apagar el servidor."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info(">> [SCHEDULER] APScheduler detenido.")
