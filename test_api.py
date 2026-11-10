"""
Suite de Pruebas de Integración para Autenticación, RBAC y Endpoints de la API.
Valida el ciclo completo de seguridad y casos borde (401 y 403).
"""

from __future__ import annotations

import os
from decimal import Decimal
from fastapi.testclient import TestClient

# Aseguramos base de datos de pruebas aislada
os.environ["DATABASE_URL"] = "sqlite:///./test_condominio.db"

from main import app, seed_database_if_empty

client = TestClient(app)


def setup_module():
    """Inicializa la base de datos de pruebas antes de correr los tests."""
    seed_database_if_empty()


def test_auth_login_invalid_credentials():
    """Verifica que un intento con contraseña errónea retorne HTTP 401."""
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@condominio.com", "password": "wrong_password"},
    )
    assert response.status_code == 401
    assert "Credenciales inválidas" in response.json()["detail"]


def test_auth_login_success_roles():
    """Verifica el login exitoso de cada rol y la emisión del token JWT."""
    # 1. Login Admin
    res_admin = client.post(
        "/api/auth/login",
        json={"email": "admin@condominio.com", "password": "admin123"},
    )
    assert res_admin.status_code == 200
    data_admin = res_admin.json()
    assert "access_token" in data_admin
    assert data_admin["rol"] == "ADMINISTRADOR"
    assert data_admin["nombre_completo"] == "Carlos Méndez (Admin)"

    # 2. Login Residente
    res_res = client.post(
        "/api/auth/login",
        json={"email": "laura@condominio.com", "password": "residente123"},
    )
    assert res_res.status_code == 200
    data_res = res_res.json()
    assert data_res["rol"] == "RESIDENTE"

    # 3. Login Guardia
    res_guard = client.post(
        "/api/auth/login",
        json={"email": "guardia@condominio.com", "password": "guardia123"},
    )
    assert res_guard.status_code == 200
    data_guard = res_guard.json()
    assert data_guard["rol"] == "GUARDIA"


def test_get_perfil_without_token():
    """Verifica que acceder a /api/perfil sin token retorne HTTP 401."""
    response = client.get("/api/perfil")
    assert response.status_code == 401
    assert "Credenciales de autenticación no proporcionadas" in response.json()["detail"]


def test_get_perfil_with_valid_token():
    """Verifica que cualquier usuario con token válido pueda ver su perfil."""
    # Obtenemos token del residente
    login_res = client.post(
        "/api/auth/login",
        json={"email": "laura@condominio.com", "password": "residente123"},
    ).json()
    token = login_res["access_token"]

    response = client.get(
        "/api/perfil",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "laura@condominio.com"
    assert data["rol"] == "RESIDENTE"
    assert data["is_active"] is True
    assert "telefono" in data


def test_unidades_rbac_protection():
    """
    Verifica que /api/unidades:
    - Retorne 403 Forbidden ('Privilegios insuficientes') para Residentes y Guardias.
    - Retorne 200 OK con la lista de unidades para el Administrador.
    """
    # 1. Intentar como Residente -> 403
    token_residente = client.post(
        "/api/auth/login",
        json={"email": "laura@condominio.com", "password": "residente123"},
    ).json()["access_token"]

    res_forbidden_res = client.get(
        "/api/unidades",
        headers={"Authorization": f"Bearer {token_residente}"},
    )
    assert res_forbidden_res.status_code == 403
    assert res_forbidden_res.json()["detail"] == "Privilegios insuficientes"

    # 2. Intentar como Guardia -> 403
    token_guardia = client.post(
        "/api/auth/login",
        json={"email": "guardia@condominio.com", "password": "guardia123"},
    ).json()["access_token"]

    res_forbidden_guard = client.get(
        "/api/unidades",
        headers={"Authorization": f"Bearer {token_guardia}"},
    )
    assert res_forbidden_guard.status_code == 403
    assert res_forbidden_guard.json()["detail"] == "Privilegios insuficientes"

    # 3. Intentar como Administrador -> 200 OK
    token_admin = client.post(
        "/api/auth/login",
        json={"email": "admin@condominio.com", "password": "admin123"},
    ).json()["access_token"]

    res_ok = client.get(
        "/api/unidades",
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert res_ok.status_code == 200
    units = res_ok.json()
    assert isinstance(units, list)
    assert len(units) >= 1
    u = units[0]
    assert u["identificador"] == "Torre A - 101"
    assert u["coeficiente_copropiedad"] == 0.045
    assert "propietario_nombre" in u
    assert "residente_nombre" in u


def test_pagos_rbac_and_creation():
    """
    Verifica que /api/pagos:
    - Retorne 403 Forbidden para Administradores y Guardias.
    - Permita a un Residente registrar un pago en estado 'EN_REVISION'.
    """
    pago_payload = {
        "monto": 95.50,
        "metodo": "TRANSFERENCIA",
        "comprobante_url": "https://s3.amazonaws.com/condo-receipts/recibo-101.pdf",
    }

    # 1. Administrador intenta pagar -> 403
    token_admin = client.post(
        "/api/auth/login",
        json={"email": "admin@condominio.com", "password": "admin123"},
    ).json()["access_token"]

    res_admin = client.post(
        "/api/pagos",
        json=pago_payload,
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert res_admin.status_code == 403
    assert res_admin.json()["detail"] == "Privilegios insuficientes"

    # 2. Guardia intenta pagar -> 403
    token_guardia = client.post(
        "/api/auth/login",
        json={"email": "guardia@condominio.com", "password": "guardia123"},
    ).json()["access_token"]

    res_guardia = client.post(
        "/api/pagos",
        json=pago_payload,
        headers={"Authorization": f"Bearer {token_guardia}"},
    )
    assert res_guardia.status_code == 403
    assert res_guardia.json()["detail"] == "Privilegios insuficientes"

    # 3. Residente registra el pago -> 201 Created
    token_residente = client.post(
        "/api/auth/login",
        json={"email": "laura@condominio.com", "password": "residente123"},
    ).json()["access_token"]

    res_pago = client.post(
        "/api/pagos",
        json=pago_payload,
        headers={"Authorization": f"Bearer {token_residente}"},
    )
    assert res_pago.status_code == 201
    pago_creado = res_pago.json()
    assert pago_creado["monto_pagado"] == "95.50"
    assert pago_creado["metodo"] == "TRANSFERENCIA"
    assert pago_creado["estado_validacion"] == "EN_REVISION"
    assert pago_creado["comprobante_url"] == pago_payload["comprobante_url"]
    assert "id" in pago_creado
    assert "unit_id" in pago_creado


if __name__ == "__main__":
    print("=" * 80)
    print("EJECUTANDO SUITE DE PRUEBAS DE AUTENTICACIÓN Y RBAC")
    print("=" * 80)
    setup_module()
    test_auth_login_invalid_credentials()
    print("✓ [PASS] test_auth_login_invalid_credentials (401)")
    test_auth_login_success_roles()
    print("✓ [PASS] test_auth_login_success_roles (Token JWT emitido para cada rol)")
    test_get_perfil_without_token()
    print("✓ [PASS] test_get_perfil_without_token (401 sin Bearer)")
    test_get_perfil_with_valid_token()
    print("✓ [PASS] test_get_perfil_with_valid_token (200 OK perfil retornado)")
    test_unidades_rbac_protection()
    print("✓ [PASS] test_unidades_rbac_protection (403 para residente/guardia, 200 para admin)")
    test_pagos_rbac_and_creation()
    print("✓ [PASS] test_pagos_rbac_and_creation (403 para admin/guardia, 201 para residente)")
    print("=" * 80)
    print("¡TODAS LAS PRUEBAS DE SEGURIDAD Y RBAC PASARON SATISFACTORIAMENTE!")
    print("=" * 80)
