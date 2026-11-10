"""
Controlador de Autenticación y Perfil de Usuario.
Rutas:
- POST /api/auth/login
- GET  /api/perfil
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user
from models import User
from schemas import LoginRequest, TokenResponse, UserProfileResponse
from security import create_access_token, verify_password

router = APIRouter(tags=["Autenticación y Perfil"])


@router.post(
    "/api/auth/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Iniciar sesión y obtener token JWT",
)
def login(credentials: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """
    Autentica un usuario verificando su correo electrónico y contraseña hasheada.
    Si las credenciales son válidas, devuelve el token JWT con su rol y datos básicos.
    """
    clean_email = credentials.email.lower().strip()
    user = db.scalar(select(User).where(User.email == clean_email))

    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas (correo o contraseña incorrectos)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta de usuario se encuentra inactiva",
        )

    access_token = create_access_token(user_id=user.id, rol=user.rol)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user.id,
        nombre_completo=user.nombre_completo,
        email=user.email,
        rol=user.rol,
    )


@router.get(
    "/api/perfil",
    response_model=UserProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener perfil del usuario autenticado",
)
def get_profile(current_user: User = Depends(get_current_user)) -> UserProfileResponse:
    """
    Accesible para CUALQUIER usuario con token JWT activo.
    Devuelve los datos del perfil (nombre_completo, email, rol, teléfono, estado y fecha de registro).
    """
    return UserProfileResponse.model_validate(current_user)
