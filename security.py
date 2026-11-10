"""
Módulo de Seguridad Criptográfica y Gestión de Tokens JWT.
Utiliza bcrypt nativo para hashing seguro y PyJWT para tokens de sesión.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union

import bcrypt
import jwt
from models import UserRole

# Configuración de Secretos y Parámetros Criptográficos
SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY",
    "f8a3c9e2b1d0476a89c5e3f1b2d4a6e879c0b2d4e6f8a0b2c4d6e8f0a2b4c6d8",  # 256-bit default key
)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "24"))


# ==============================================================================
# GESTIÓN DE CONTRASEÑAS (BCRYPT)
# ==============================================================================

def hash_password(password: str) -> str:
    """
    Genera un hash seguro utilizando bcrypt con salting aleatorio.
    Maneja el límite estándar de 72 bytes de bcrypt.
    """
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica si una contraseña en texto plano coincide con el hash almacenado en base de datos.
    """
    try:
        pwd_bytes = plain_password.encode("utf-8")[:72]
        hash_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except (ValueError, TypeError):
        return False


# ==============================================================================
# GESTIÓN DE TOKENS JWT
# ==============================================================================

def create_access_token(
    user_id: Union[uuid.UUID, str],
    rol: Union[UserRole, str],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Genera un token JWT firmado criptográficamente con el ID del usuario y su rol.
    
    Payload estándar:
    - sub: Identificador del usuario (Subject)
    - user_id: UUID del usuario en formato string
    - rol: Rol del usuario ('ADMINISTRADOR', 'RESIDENTE', 'GUARDIA')
    - iat: Timestamp de emisión (Issued At)
    - exp: Timestamp de expiración (por defecto 24 horas)
    """
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)

    rol_str = rol.value if isinstance(rol, UserRole) else str(rol)
    user_id_str = str(user_id)

    payload: Dict[str, Any] = {
        "sub": user_id_str,
        "user_id": user_id_str,
        "rol": rol_str,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decodifica y valida la firma y expiración de un token JWT.
    Lanza jwt.PyJWTError si el token es inválido o ha expirado.
    """
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
