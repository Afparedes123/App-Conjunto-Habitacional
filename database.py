"""
Configuración de la Base de Datos y Gestión de Sesiones para FastAPI.
Soporta SQLite para desarrollo local y PostgreSQL para producción SaaS.
"""

from __future__ import annotations

import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Configuración de URL de conexión a base de datos
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./condominio.db")

# Ajuste específico para SQLite (check_same_thread)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=os.getenv("SQL_DEBUG", "false").lower() == "true",
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """
    Dependencia de FastAPI que proporciona una sesión transaccional de SQLAlchemy.
    Garantiza el cierre automático de la sesión al finalizar el ciclo de vida del request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
