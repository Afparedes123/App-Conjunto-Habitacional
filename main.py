"""
Punto de Entrada Principal de la API REST de Administración de Condominios.
Configuración de FastAPI, Middleware CORS, Inicialización de Tablas y Routers.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware

from database import SessionLocal, engine
from models import Base, CommonArea, Unit, User, UserRole
from routers.auth import router as auth_router
from routers.financial import router as financial_router
from routers.payments import router as payments_router
from routers.reservations import router as reservations_router
from routers.security import router as security_router
from routers.units import router as units_router
from scheduler import shutdown_scheduler, start_scheduler
from security import hash_password


def seed_database_if_empty() -> None:
    """
    Crea las tablas en la base de datos si no existen y siembra
    usuarios y unidades básicas para facilitar el desarrollo y pruebas.
    """
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        admin_exists = db.query(User).filter(User.rol == UserRole.ADMINISTRADOR).first()
        if not admin_exists:
            print(">> Base de datos limpia: sembrando usuarios y unidades iniciales...")

            # 1. Administrador del condominio
            admin = User(
                nombre_completo="Carlos Méndez (Admin)",
                email="admin@condominio.com",
                password_hash=hash_password("admin123"),
                rol=UserRole.ADMINISTRADOR,
                telefono="+593987654321",
                is_active=True,
            )

            # 2. Residente / Propietario
            residente = User(
                nombre_completo="Dra. Laura Valencia (Residente)",
                email="laura@condominio.com",
                password_hash=hash_password("residente123"),
                rol=UserRole.RESIDENTE,
                telefono="+593991234567",
                is_active=True,
            )

            # 3. Guardia de seguridad en garita
            guardia = User(
                nombre_completo="José Guachamín (Guardia)",
                email="guardia@condominio.com",
                password_hash=hash_password("guardia123"),
                rol=UserRole.GUARDIA,
                telefono="+593990001122",
                is_active=True,
            )

            db.add_all([admin, residente, guardia])
            db.flush()

            # 4. Unidad Habitacional
            unidad = Unit(
                identificador="Torre A - 101",
                coeficiente_copropiedad=0.045,
                propietario_id=residente.id,
                residente_id=residente.id,
            )
            db.add(unidad)
            db.commit()
            print(">> Usuarios y unidades iniciales sembrados con éxito:")
            print("   - Admin:     admin@condominio.com     / admin123")
            print("   - Residente: laura@condominio.com     / residente123")
            print("   - Guardia:   guardia@condominio.com   / guardia123")

        # 5. Asegurar Áreas Comunales iniciales si no existen
        if db.query(CommonArea).count() == 0:
            bbq = CommonArea(
                nombre="Área BBQ Panorámica",
                aforo_maximo=25,
                costo_reserva=20.00,
                requiere_aprobacion=True,
            )
            piscina = CommonArea(
                nombre="Piscina y Jacuzzi",
                aforo_maximo=30,
                costo_reserva=0.00,
                requiere_aprobacion=False,
            )
            padel = CommonArea(
                nombre="Cancha de Pádel / Tenis",
                aforo_maximo=4,
                costo_reserva=0.00,
                requiere_aprobacion=False,
            )
            salon = CommonArea(
                nombre="Salón Comunal de Eventos",
                aforo_maximo=60,
                costo_reserva=50.00,
                requiere_aprobacion=True,
            )
            db.add_all([bbq, piscina, padel, salon])
            db.commit()
            print(">> Áreas Comunales sembradas: BBQ, Piscina, Pádel y Salón Comunal")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Ciclo de vida de la aplicación: asegura las tablas, inicialización y schedulers."""
    seed_database_if_empty()
    enable_sched = os.getenv("ENABLE_SCHEDULER", "false").lower() == "true"
    if enable_sched:
        start_scheduler()
    yield
    if enable_sched:
        shutdown_scheduler()


# ==============================================================================
# INSTANCIA FASTAPI
# ==============================================================================

app = FastAPI(
    title="SaaS Administración de Condominios API",
    description=(
        "API REST para la gestión de seguridad, finanzas, control de acceso "
        "y convivencia en condominios y conjuntos residenciales. "
        "Incluye autenticación JWT y control de acceso basado en roles (RBAC)."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configuración de CORS para clientes web y móviles
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusión de Routers Modulares
app.include_router(auth_router)
app.include_router(units_router)
app.include_router(payments_router)
app.include_router(financial_router)
app.include_router(security_router)
app.include_router(reservations_router)


# ==============================================================================
# RUTAS DE CHEQUEO DE SALUD Y RAÍZ
# ==============================================================================

@app.get("/", tags=["Sistema"])
def root():
    return {
        "sistema": "API Administración de Condominios",
        "version": "1.0.0",
        "estado": "operativo",
        "docs": "/docs",
    }


@app.get("/health", tags=["Sistema"], status_code=status.HTTP_200_OK)
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
