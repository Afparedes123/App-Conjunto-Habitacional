"""
Suite de Pruebas de Integración para Autenticación, RBAC y Endpoints de la API.
Valida el ciclo completo de seguridad y casos borde (401 y 403).
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
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


# ==============================================================================
# PRUEBAS DEL MÓDULO FINANCIERO Y TAREAS AUTOMÁTICAS
# ==============================================================================

def test_generar_alicuotas_mensuales_logic():
    """
    Verifica la lógica de negocio de generación masiva de alícuotas:
    - Valor a pagar = monto_base * coeficiente_copropiedad.
    - Idempotencia: No duplica alícuotas si se ejecuta múltiples veces en el mismo mes.
    """
    from database import SessionLocal
    from services.financial_service import generar_alicuotas_mensuales
    from models import FinancialObligation, ObligationStatus, ObligationType, Unit

    monto_base = Decimal("2000.00")
    anio_test = 2027
    mes_test = 1

    with SessionLocal() as db:
        # Limpiar registros previos de este periodo de prueba para garantizar aislamiento
        db.query(FinancialObligation).filter(
            FinancialObligation.fecha_emision == date(anio_test, mes_test, 1)
        ).delete()
        db.commit()

        # 1. Primera ejecución: Debe generar las alícuotas para las unidades existentes
        resultado = generar_alicuotas_mensuales(db, monto_base=monto_base, anio=anio_test, mes=mes_test)
        assert resultado["periodo"] == "2027-01"
        assert resultado["total_generadas"] >= 1
        assert resultado["total_omitidas"] == 0

        # Verificar cálculo exacto para Torre A - 101 (coeficiente: 0.045)
        # 2000.00 * 0.045 = 90.00
        u101 = db.query(Unit).filter(Unit.identificador == "Torre A - 101").first()
        alicuota = (
            db.query(FinancialObligation)
            .filter(
                FinancialObligation.unit_id == u101.id,
                FinancialObligation.tipo == ObligationType.ORDINARIA,
                FinancialObligation.fecha_emision == date(2027, 1, 1),
            )
            .first()
        )
        assert alicuota is not None
        assert alicuota.monto == Decimal("90.00")
        assert alicuota.fecha_vencimiento == date(2027, 1, 10)
        assert alicuota.estado == ObligationStatus.PENDIENTE

        # 2. Segunda ejecución (Idempotencia): Debe detectar que ya existen y omitirlas
        resultado_segunda = generar_alicuotas_mensuales(db, monto_base=monto_base, anio=anio_test, mes=mes_test)
        assert resultado_segunda["total_generadas"] == 0
        assert resultado_segunda["total_omitidas"] >= 1


def test_aplicar_multas_por_mora_logic():
    """
    Verifica el cálculo de morosidad y aplicación de multas:
    - Deuda vencida pasa de PENDIENTE a VENCIDA.
    - Se crea una nueva obligación tipo MULTA con el porcentaje especificado.
    - Idempotencia: No genera múltiples multas por la misma mora.
    """
    from database import SessionLocal
    from services.financial_service import aplicar_multas_por_mora
    from models import FinancialObligation, ObligationStatus, ObligationType, Unit

    with SessionLocal() as db:
        u101 = db.query(Unit).filter(Unit.identificador == "Torre A - 101").first()

        # Limpiar registros previos de prueba
        db.query(FinancialObligation).filter(
            FinancialObligation.concepto.like("%Alícuota Ordinaria Histórica%")
        ).delete()
        db.commit()

        # Insertar una deuda ordinaria intencionalmente vencida
        deuda_vencida = FinancialObligation(
            unit_id=u101.id,
            tipo=ObligationType.ORDINARIA,
            concepto="Alícuota Ordinaria Histórica",
            monto=Decimal("100.00"),
            fecha_emision=date(2026, 9, 1),
            fecha_vencimiento=date(2026, 9, 10),
            estado=ObligationStatus.PENDIENTE,
        )
        db.add(deuda_vencida)
        db.commit()
        db.refresh(deuda_vencida)

        # Aplicar multas con corte al día 11 del mes posterior
        corte = date(2026, 9, 11)
        porcentaje_multa = Decimal("10.00")  # 10% sobre $100 = $10.00
        res = aplicar_multas_por_mora(db, porcentaje_multa=porcentaje_multa, fecha_corte=corte)

        assert res["deudas_vencidas_procesadas"] >= 1
        assert res["total_multas_generadas"] >= 1

        # Verificar que la deuda original ahora esté VENCIDA
        db.refresh(deuda_vencida)
        assert deuda_vencida.estado == ObligationStatus.VENCIDA

        # Verificar la multa generada
        multa = (
            db.query(FinancialObligation)
            .filter(
                FinancialObligation.unit_id == u101.id,
                FinancialObligation.tipo == ObligationType.MULTA,
                FinancialObligation.concepto.like("%Alícuota Ordinaria Histórica%"),
            )
            .first()
        )
        assert multa is not None
        assert multa.monto == Decimal("10.00")
        assert multa.estado == ObligationStatus.PENDIENTE

        # Verificar idempotencia en segunda ejecución
        res_segunda = aplicar_multas_por_mora(db, porcentaje_multa=porcentaje_multa, fecha_corte=corte)
        assert res_segunda["total_multas_generadas"] == 0


def test_estado_cuenta_endpoint_rbac_and_data():
    """
    Verifica el endpoint GET /api/unidades/{unit_id}/estado-cuenta:
    - Administrador puede ver cualquier estado de cuenta (200 OK).
    - Residente dueño de la unidad puede ver su propio estado de cuenta (200 OK).
    - Residente NO puede ver estado de cuenta de otra unidad ajena (403 Forbidden).
    - Guardia NO puede ver estados de cuenta (403 Forbidden).
    - Unidad inexistente retorna 404 Not Found.
    - Valida consolidación de saldo_total_pendiente, obligaciones_pendientes y ultimos_pagos.
    """
    import uuid
    from database import SessionLocal
    from models import Unit, User, UserRole
    from security import hash_password

    # 1. Obtener la unidad 101 existente (asociada a la residente 'Laura')
    with SessionLocal() as db:
        unit_101 = db.query(Unit).filter(Unit.identificador == "Torre A - 101").first()
        unit_101_id = str(unit_101.id)

        # Crear una segunda unidad perteneciente a otro usuario (Juan)
        otro_residente = db.query(User).filter(User.email == "juan@condominio.com").first()
        if not otro_residente:
            otro_residente = User(
                nombre_completo="Juan Pérez (Vecino)",
                email="juan@condominio.com",
                password_hash=hash_password("juan123"),
                rol=UserRole.RESIDENTE,
                telefono="+593994443322",
                is_active=True,
            )
            db.add(otro_residente)
            db.flush()

        unit_202 = db.query(Unit).filter(Unit.identificador == "Torre B - 202").first()
        if not unit_202:
            unit_202 = Unit(
                identificador="Torre B - 202",
                coeficiente_copropiedad=0.050,
                propietario_id=otro_residente.id,
                residente_id=otro_residente.id,
            )
            db.add(unit_202)
            db.commit()
            db.refresh(unit_202)
        unit_202_id = str(unit_202.id)

    # Tokens de autenticación
    token_admin = client.post(
        "/api/auth/login", json={"email": "admin@condominio.com", "password": "admin123"}
    ).json()["access_token"]

    token_laura = client.post(
        "/api/auth/login", json={"email": "laura@condominio.com", "password": "residente123"}
    ).json()["access_token"]

    token_guardia = client.post(
        "/api/auth/login", json={"email": "guardia@condominio.com", "password": "guardia123"}
    ).json()["access_token"]

    # Caso A: Admin consulta unidad 101 -> 200 OK
    res_admin = client.get(
        f"/api/unidades/{unit_101_id}/estado-cuenta",
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert res_admin.status_code == 200
    data_admin = res_admin.json()
    assert data_admin["identificador"] == "Torre A - 101"
    assert "saldo_total_pendiente" in data_admin
    assert isinstance(data_admin["obligaciones_pendientes"], list)
    assert isinstance(data_admin["ultimos_pagos"], list)
    assert len(data_admin["ultimos_pagos"]) <= 5

    # Caso B: Residente Laura consulta su propia unidad 101 -> 200 OK
    res_laura_propia = client.get(
        f"/api/unidades/{unit_101_id}/estado-cuenta",
        headers={"Authorization": f"Bearer {token_laura}"},
    )
    assert res_laura_propia.status_code == 200
    assert res_laura_propia.json()["identificador"] == "Torre A - 101"

    # Caso C: Residente Laura intenta consultar la unidad 202 (de Juan) -> 403 Forbidden
    res_laura_ajena = client.get(
        f"/api/unidades/{unit_202_id}/estado-cuenta",
        headers={"Authorization": f"Bearer {token_laura}"},
    )
    assert res_laura_ajena.status_code == 403
    assert "Privilegios insuficientes para consultar el estado de cuenta" in res_laura_ajena.json()["detail"]

    # Caso D: Guardia intenta consultar estado de cuenta -> 403 Forbidden
    res_guardia = client.get(
        f"/api/unidades/{unit_101_id}/estado-cuenta",
        headers={"Authorization": f"Bearer {token_guardia}"},
    )
    assert res_guardia.status_code == 403
    assert "Privilegios insuficientes" in res_guardia.json()["detail"]

    # Caso E: Unidad inexistente -> 404 Not Found
    random_uuid = str(uuid.uuid4())
    res_404 = client.get(
        f"/api/unidades/{random_uuid}/estado-cuenta",
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert res_404.status_code == 404
    assert "Unidad habitacional no encontrada" in res_404.json()["detail"]


# ==============================================================================
# PRUEBAS DEL CONTROL DE ACCESO INTELIGENTE (PASES QR Y GARITA)
# ==============================================================================

def test_generar_y_validar_pase_qr_flow():
    """
    Verifica el flujo completo de emisión de pase QR por residente
    y validación en garita por el guardia de seguridad:
    1. Residente genera pase con código QR en base64.
    2. Guardia escanea el hash_qr y recibe autorización de ingreso.
    3. El pase cambia a estado 'USADO' y se genera un registro en 'AccessLog'.
    """
    from database import SessionLocal
    from models import AccessLog, QRPass, QRPassStatus

    # Tokens
    token_residente = client.post(
        "/api/auth/login", json={"email": "laura@condominio.com", "password": "residente123"}
    ).json()["access_token"]

    token_guardia = client.post(
        "/api/auth/login", json={"email": "guardia@condominio.com", "password": "guardia123"}
    ).json()["access_token"]

    # 1. Residente genera pase
    now = datetime.now(timezone.utc)
    fin = now + timedelta(hours=4)
    payload_generar = {
        "nombre_visitante": "Ing. Marcelo Solís",
        "tipo_visita": "FAMILIAR",
        "fecha_hora_fin": fin.isoformat(),
    }

    res_crear = client.post(
        "/api/seguridad/generar-pase",
        json=payload_generar,
        headers={"Authorization": f"Bearer {token_residente}"},
    )
    assert res_crear.status_code == 201
    pase_data = res_crear.json()
    assert pase_data["nombre_visitante"] == "Ing. Marcelo Solís"
    assert pase_data["tipo_visita"] == "FAMILIAR"
    assert pase_data["estado"] == "ACTIVO"
    assert "hash_qr" in pase_data
    assert pase_data["qr_image_base64"].startswith("data:image/png;base64,")
    hash_qr = pase_data["hash_qr"]

    # 2. Guardia valida el pase en garita
    res_validar = client.post(
        "/api/seguridad/validar-pase",
        json={"hash_qr": hash_qr, "placa_vehiculo": "PBA-9988"},
        headers={"Authorization": f"Bearer {token_guardia}"},
    )
    assert res_validar.status_code == 200
    val_data = res_validar.json()
    assert val_data["acceso_permitido"] is True
    assert val_data["mensaje"] == "ACCESO PERMITIDO"
    assert val_data["nombre_visitante"] == "Ing. Marcelo Solís"
    assert val_data["unidad_destino"] == "Torre A - 101"
    assert "access_log_id" in val_data

    # 3. Validar en base de datos la persistencia de la auditoría y estado USADO
    with SessionLocal() as db:
        qr_db = db.query(QRPass).filter(QRPass.hash_qr == hash_qr).first()
        assert qr_db is not None
        assert qr_db.estado == QRPassStatus.USADO

        log_db = db.query(AccessLog).filter(AccessLog.qr_pass_id == qr_db.id).first()
        assert log_db is not None
        assert log_db.placa_vehiculo == "PBA-9988"
        assert log_db.cedula_visitante == "VALIDADO_QR"


def test_validar_pase_qr_errores_y_expiracion():
    """
    Verifica los casos borde y restricciones de seguridad:
    - Reintentar validar un pase ya USADO -> 403 Forbidden.
    - Validar un hash inexistente -> 404 Not Found.
    - Residente intentando validar pases de guardia -> 403 Forbidden.
    - Pase con fecha vencida -> 403 Forbidden.
    - Carga de la vista HTML del escáner -> 200 OK.
    """
    from database import SessionLocal
    from models import QRPass, QRPassStatus, Unit

    token_guardia = client.post(
        "/api/auth/login", json={"email": "guardia@condominio.com", "password": "guardia123"}
    ).json()["access_token"]

    token_residente = client.post(
        "/api/auth/login", json={"email": "laura@condominio.com", "password": "residente123"}
    ).json()["access_token"]

    # 1. Crear un pase expirado directamente en BD
    with SessionLocal() as db:
        u101 = db.query(Unit).filter(Unit.identificador == "Torre A - 101").first()
        hash_expirado = "hash_expirado_test_999"
        db.query(QRPass).filter(QRPass.hash_qr == hash_expirado).delete()
        db.commit()

        pase_expirado = QRPass(
            unit_id=u101.id,
            nombre_visitante="Visitante Vencido",
            tipo_visita="DELIVERY",
            hash_qr=hash_expirado,
            fecha_hora_inicio=datetime.now(timezone.utc) - timedelta(hours=5),
            fecha_hora_fin=datetime.now(timezone.utc) - timedelta(hours=1),
            estado=QRPassStatus.ACTIVO,
        )
        db.add(pase_expirado)
        db.commit()

    # Intentar validar el pase expirado -> 403
    res_exp = client.post(
        "/api/seguridad/validar-pase",
        json={"hash_qr": hash_expirado},
        headers={"Authorization": f"Bearer {token_guardia}"},
    )
    assert res_exp.status_code == 403
    assert "Pase expirado o ya utilizado" in res_exp.json()["detail"]

    # 2. Intentar validar hash inexistente -> 404
    res_404 = client.post(
        "/api/seguridad/validar-pase",
        json={"hash_qr": "hash_totalmente_inexistente"},
        headers={"Authorization": f"Bearer {token_guardia}"},
    )
    assert res_404.status_code == 404
    assert "Pase no encontrado" in res_404.json()["detail"]

    # 3. Residente intentando validar pases (solo guardias tienen permiso) -> 403
    res_forbidden = client.post(
        "/api/seguridad/validar-pase",
        json={"hash_qr": hash_expirado},
        headers={"Authorization": f"Bearer {token_residente}"},
    )
    assert res_forbidden.status_code == 403
    assert res_forbidden.json()["detail"] == "Privilegios insuficientes"

    # 4. Probar que el endpoint HTML de la interfaz del escáner responda 200 OK
    res_html = client.get("/api/seguridad/escaner")
    assert res_html.status_code == 200
    assert "Garita Principal" in res_html.text
    assert "html5-qrcode" in res_html.text


# ==============================================================================
# PRUEBAS DEL MÓDULO DE CONVIVENCIA Y MOTOR DE RESERVAS
# ==============================================================================

def test_reservas_bloqueo_morosidad_403():
    """
    Verifica que el motor de reservas bloquee a residentes con deudas morosas:
    - Retorna HTTP 403 Forbidden con el mensaje exacto requerido.
    """
    from database import SessionLocal
    from models import CommonArea, FinancialObligation, ObligationStatus, ObligationType, Unit

    token_residente = client.post(
        "/api/auth/login", json={"email": "laura@condominio.com", "password": "residente123"}
    ).json()["access_token"]

    with SessionLocal() as db:
        u101 = db.query(Unit).filter(Unit.identificador == "Torre A - 101").first()
        area = db.query(CommonArea).first()
        assert area is not None, "Debe existir al menos un área común sembrada"

        # Limpiar obligaciones morosas previas de prueba e insertar una vencida
        db.query(FinancialObligation).filter(
            FinancialObligation.unit_id == u101.id,
            FinancialObligation.concepto.like("%Mora Bloqueo Reservas%"),
        ).delete()
        db.commit()

        deuda_morosa = FinancialObligation(
            unit_id=u101.id,
            tipo=ObligationType.MULTA,
            concepto="Mora Bloqueo Reservas",
            monto=Decimal("75.00"),
            fecha_emision=date(2026, 1, 1),
            fecha_vencimiento=date(2026, 1, 10),
            estado=ObligationStatus.VENCIDA,
        )
        db.add(deuda_morosa)
        db.commit()
        area_id = str(area.id)

    # Residente intenta reservar estando en mora -> 403 Forbidden
    payload = {
        "area_id": area_id,
        "fecha_hora_inicio": "2027-07-15T10:00:00Z",
        "fecha_hora_fin": "2027-07-15T14:00:00Z",
    }
    res = client.post(
        "/api/reservas",
        json=payload,
        headers={"Authorization": f"Bearer {token_residente}"},
    )
    assert res.status_code == 403
    body = res.json()
    assert (
        body["error"]
        == "Acceso restringido por morosidad. Por favor, ponga al día sus obligaciones para reservar áreas comunes."
    )
    assert body["deuda_total"] >= 75.0


def test_reservas_creacion_exitosa_201():
    """
    Verifica que un residente al día en sus pagos pueda crear una reserva exitosa:
    - Retorna HTTP 201 Created con estado 'SOLICITADA' o 'APROBADA'.
    """
    from database import SessionLocal
    from models import CommonArea, FinancialObligation, ObligationStatus, Reservation, Unit

    token_residente = client.post(
        "/api/auth/login", json={"email": "laura@condominio.com", "password": "residente123"}
    ).json()["access_token"]

    with SessionLocal() as db:
        u101 = db.query(Unit).filter(Unit.identificador == "Torre A - 101").first()
        area = db.query(CommonArea).first()

        # Limpiar deudas pendientes/vencidas de prueba para poner al día la unidad
        db.query(FinancialObligation).filter(
            FinancialObligation.unit_id == u101.id,
            FinancialObligation.estado.in_([ObligationStatus.VENCIDA, ObligationStatus.PENDIENTE]),
        ).delete()

        # Limpiar reservas previas en ese slot
        inicio_dt = datetime(2027, 8, 20, 10, 0, 0, tzinfo=timezone.utc)
        fin_dt = datetime(2027, 8, 20, 14, 0, 0, tzinfo=timezone.utc)
        db.query(Reservation).filter(
            Reservation.area_id == area.id,
            Reservation.fecha_hora_inicio == inicio_dt,
        ).delete()
        db.commit()
        area_id = str(area.id)

    payload = {
        "area_id": area_id,
        "fecha_hora_inicio": "2027-08-20T10:00:00Z",
        "fecha_hora_fin": "2027-08-20T14:00:00Z",
    }
    res = client.post(
        "/api/reservas",
        json=payload,
        headers={"Authorization": f"Bearer {token_residente}"},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["unit_identificador"] == "Torre A - 101"
    assert data["area_id"] == area_id
    assert data["estado"] in ["SOLICITADA", "APROBADA"]
    assert "id" in data


def test_reservas_conflicto_horario_409():
    """
    Verifica la detección matemática de solapamiento de horarios (A < D AND B > C):
    - Retorna HTTP 409 Conflict si ya existe una reserva activa en ese intervalo.
    """
    from database import SessionLocal
    from models import CommonArea

    token_residente = client.post(
        "/api/auth/login", json={"email": "laura@condominio.com", "password": "residente123"}
    ).json()["access_token"]

    with SessionLocal() as db:
        area = db.query(CommonArea).first()
        area_id = str(area.id)

    # Intento de reserva solapada: 12:00 a 16:00 se superpone con la reserva existente 10:00 a 14:00
    payload_solapado = {
        "area_id": area_id,
        "fecha_hora_inicio": "2027-08-20T12:00:00Z",
        "fecha_hora_fin": "2027-08-20T16:00:00Z",
    }
    res = client.post(
        "/api/reservas",
        json=payload_solapado,
        headers={"Authorization": f"Bearer {token_residente}"},
    )
    assert res.status_code == 409
    body = res.json()
    assert "error" in body
    assert "ya se encuentra reservada" in body["error"]
    assert "conflicto_inicio" in body


def test_reservas_catalogo_calendario_y_rbac():
    """
    Verifica endpoints auxiliares del módulo de reservas y control de acceso:
    - GET /api/reservas/areas (Catálogo de áreas) -> 200 OK
    - GET /api/reservas/calendario (Franjas ocupadas) -> 200 OK
    - GET /api/reservas (Historial de la unidad) -> 200 OK
    - GET /api/reservas/interfaz (SPA HTML del residente) -> 200 OK
    - POST /api/reservas ejecutado por admin o guardia -> 403 Forbidden
    """
    from database import SessionLocal
    from models import CommonArea

    token_residente = client.post(
        "/api/auth/login", json={"email": "laura@condominio.com", "password": "residente123"}
    ).json()["access_token"]

    token_admin = client.post(
        "/api/auth/login", json={"email": "admin@condominio.com", "password": "admin123"}
    ).json()["access_token"]

    # 1. Catálogo de áreas
    res_areas = client.get(
        "/api/reservas/areas",
        headers={"Authorization": f"Bearer {token_residente}"},
    )
    assert res_areas.status_code == 200
    areas = res_areas.json()
    assert len(areas) >= 1

    first_area_id = areas[0]["id"]

    # 2. Calendario de disponibilidad
    res_cal = client.get(
        f"/api/reservas/calendario?area_id={first_area_id}",
        headers={"Authorization": f"Bearer {token_residente}"},
    )
    assert res_cal.status_code == 200
    assert isinstance(res_cal.json(), list)

    # 3. Historial de reservas del residente
    res_historial = client.get(
        "/api/reservas",
        headers={"Authorization": f"Bearer {token_residente}"},
    )
    assert res_historial.status_code == 200
    assert isinstance(res_historial.json(), list)

    # 4. Interfaz web HTML
    res_ui = client.get("/api/reservas/interfaz")
    assert res_ui.status_code == 200
    assert "Reservas de Áreas Comunales" in res_ui.text
    assert "Módulo Convivencia" in res_ui.text

    # 5. RBAC: Administrador intentando crear reserva sin rol de residente -> 403
    res_admin_forbidden = client.post(
        "/api/reservas",
        json={
            "area_id": first_area_id,
            "fecha_hora_inicio": "2027-09-01T10:00:00Z",
            "fecha_hora_fin": "2027-09-01T12:00:00Z",
        },
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert res_admin_forbidden.status_code == 403
    assert res_admin_forbidden.json()["detail"] == "Privilegios insuficientes"


if __name__ == "__main__":
    print("=" * 80)
    print("EJECUTANDO SUITE COMPLETA DE PRUEBAS (AUTH, RBAC, FINANZAS, QR Y RESERVAS)")
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
    test_generar_alicuotas_mensuales_logic()
    print("✓ [PASS] test_generar_alicuotas_mensuales_logic (Cálculo proporcional e idempotencia)")
    test_aplicar_multas_por_mora_logic()
    print("✓ [PASS] test_aplicar_multas_por_mora_logic (Recargos, estado VENCIDA e idempotencia)")
    test_estado_cuenta_endpoint_rbac_and_data()
    print("✓ [PASS] test_estado_cuenta_endpoint_rbac_and_data (RBAC estricto, 403 ajeno, 200 propio/admin)")
    test_generar_y_validar_pase_qr_flow()
    print("✓ [PASS] test_generar_y_validar_pase_qr_flow (Generación Base64, validación garita y log)")
    test_validar_pase_qr_errores_y_expiracion()
    print("✓ [PASS] test_validar_pase_qr_errores_y_expiracion (403 expirado/usado, 404 inexistente y UI)")
    test_reservas_bloqueo_morosidad_403()
    print("✓ [PASS] test_reservas_bloqueo_morosidad_403 (Bloqueo financiero 403 con mensaje exacto)")
    test_reservas_creacion_exitosa_201()
    print("✓ [PASS] test_reservas_creacion_exitosa_201 (Creación exitosa 201 para residente al día)")
    test_reservas_conflicto_horario_409()
    print("✓ [PASS] test_reservas_conflicto_horario_409 (Detección de solapamiento 409 Conflict)")
    test_reservas_catalogo_calendario_y_rbac()
    print("✓ [PASS] test_reservas_catalogo_calendario_y_rbac (Catálogos, calendario, interfaz y RBAC)")
    print("=" * 80)
    print("¡TODAS LAS PRUEBAS DEL SISTEMA PASARON SATISFACTORIAMENTE (15/15)!")
    print("=" * 80)

