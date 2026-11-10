"""
Dependencias de Control de Acceso (RBAC) y Seguridad para FastAPI.
Maneja la autenticación por token Bearer JWT y la verificación granular de roles.
"""

from __future__ import annotations

import uuid
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import User, UserRole
from security import decode_access_token

# Extractor del esquema HTTP Bearer para cabecera Authorization
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Extrae el token Bearer del Header, lo decodifica y consulta al usuario activo en la BD.
    
    Lanza:
    - HTTP 401 Unauthorized: Si el token está ausente, malformado, vencido o el usuario no existe/está inactivo.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales de autenticación no proporcionadas",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El token de autenticación ha expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticación inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str: Optional[str] = payload.get("sub") or payload.get("user_id")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token no contiene identificador de usuario válido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Formato de identificador de usuario inválido en token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.scalar(select(User).where(User.id == user_uuid))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario asociado al token no encontrado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La cuenta de usuario está desactivada",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# ==============================================================================
# CONTROL DE ACCESO BASADO EN ROLES (RBAC)
# ==============================================================================

class RoleChecker:
    """
    Clase reutilizable para validar roles requeridos en endpoints de FastAPI.
    Lanza HTTP 403 Forbidden con el mensaje exacto 'Privilegios insuficientes'.
    """
    def __init__(self, allowed_roles: list[UserRole]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: User = Depends(get_current_user)) -> User:
        if current_user.rol not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Privilegios insuficientes",
            )
        return current_user


# Dependencias específicas de roles requeridas por las especificaciones
require_admin = RoleChecker([UserRole.ADMINISTRADOR])
require_residente = RoleChecker([UserRole.RESIDENTE])
require_guardia = RoleChecker([UserRole.GUARDIA])
