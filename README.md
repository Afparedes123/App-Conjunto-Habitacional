# Arquitectura Backend & API REST - App Conjunto Habitacional (SaaS)

Plataforma backend SaaS para la administración de condominios y conjuntos habitacionales (similar a Habitanto o Mi Casita), implementada en **Python**, **SQLAlchemy 2.0 (ORM)** y el framework **FastAPI**, con tipado estático (**Type Hints** y **Pydantic v2**), autenticación **JWT**, control de acceso basado en roles (**RBAC**) y **motor financiero con tareas programadas (CRON jobs)**.

---

## 🏛️ Estructura del Proyecto

```
App-Conjunto-Habitacional/
├── models.py                   # Esquema relacional SQLAlchemy 2.0 (9 modelos con cascadas e índices)
├── database.py                 # Configuración del motor relacional y dependencia get_db
├── security.py                 # Hashing de contraseñas con bcrypt y generación/decodificación JWT
├── schemas.py                  # Modelos Pydantic v2 para validación de entrada/salida
├── dependencies.py             # Inyección de dependencias RBAC (get_current_user, require_admin, etc.)
├── services/
│   ├── __init__.py
│   └── financial_service.py    # Lógica financiera: alícuotas masivas y cálculo de mora
├── scheduler.py                # Orquestación de tareas programadas (APScheduler / CRON / Celery)
├── routers/
│   ├── __init__.py
│   ├── auth.py                 # Endpoints /api/auth/login y /api/perfil
│   ├── units.py                # Endpoints /api/unidades y /api/unidades/{id}/estado-cuenta
│   ├── payments.py             # Endpoint /api/pagos (Solo Residentes)
│   └── financial.py            # Endpoints administrativos de facturación masiva
├── main.py                     # Servidor FastAPI, middleware CORS, lifespan y seed inicial
├── test_api.py                 # Suite de pruebas automatizadas (Auth, RBAC y Finanzas)
└── README.md                   # Documentación técnica
```

---

## 🔐 Matriz de Control de Acceso (RBAC) y Endpoints

| Endpoint | Método | Dependencia RBAC | Rol Permitido | Descripción |
| :--- | :---: | :--- | :--- | :--- |
| `/api/auth/login` | `POST` | *Público* | Cualquiera | Iniciar sesión y emitir token Bearer JWT |
| `/api/perfil` | `GET` | `get_current_user` | Autenticado | Ver datos del usuario en sesión |
| `/api/unidades` | `GET` | `require_admin` | `ADMINISTRADOR` | Listar unidades con coeficientes y habitantes |
| `/api/unidades/{id}/estado-cuenta` | `GET` | `get_current_user` | `ADMIN` o `RESIDENTE` titular | Estado de cuenta consolidado (saldo, deudas, últimos 5 pagos) |
| `/api/pagos` | `POST` | `require_residente` | `RESIDENTE` | Registrar pago para la unidad del residente |
| `/api/finanzas/generar-alicuotas` | `POST` | `require_admin` | `ADMINISTRADOR` | Disparar facturación masiva de alícuotas |
| `/api/finanzas/aplicar-multas` | `POST` | `require_admin` | `ADMINISTRADOR` | Disparar corte de morosidad y aplicar multas |

---

## 💰 Módulo Financiero y Tareas Automáticas

### 1. Generación Masiva de Alícuotas (`generar_alicuotas_mensuales`)
- **Frecuencia**: Ejecución automática el día 1 de cada mes a las 00:05 UTC.
- **Fórmula de cálculo**: $\text{Monto Alícuota} = \text{Monto Base Total} \times \text{Coeficiente Copropiedad}$.
- **Vencimiento**: Fijado al día 10 del mes en curso.
- **Idempotencia**: Verifica si la unidad ya tiene emitida su alícuota ordinaria en ese periodo para evitar cobros duplicados ante reintentos.
- **Transacción Atómica**: `db.commit()` atómico al finalizar la iteración con `db.rollback()` ante excepciones.

### 2. Cálculo de Morosidad y Multas (`aplicar_multas_por_mora`)
- **Frecuencia**: Ejecución automática el día 11 de cada mes a las 00:05 UTC (post-vencimiento).
- **Criterio**: Obligaciones `ORDINARIA` en estado `PENDIENTE` cuya `fecha_vencimiento < fecha_corte`.
- **Acción**:
  1. Transiciona el estado de la deuda original de `PENDIENTE` a `VENCIDA`.
  2. Genera una nueva obligación tipo `MULTA` calculada sobre el porcentaje de recargo configurado ($\text{Monto Multa} = \text{Deuda} \times \frac{\%}{100}$).
- **Idempotencia**: Valida que no se dupliquen multas sobre deudas previamente penalizadas.

---

## ⏰ Opciones de Despliegue de Tareas Programadas (CRON)

### Opción A: APScheduler (Integrado en FastAPI)
Ideal para despliegues ligeros y monolitos en un solo contenedor. Activado mediante variable de entorno:
```bash
export ENABLE_SCHEDULER=true
python main.py
```

### Opción B: CRON Nativo de Linux / Contenedor Docker
Ejecución mediante `crontab -e`:
```cron
# Día 1 de cada mes a las 00:05 UTC: Generar alícuotas
5 0 1 * * /home/antigravity/Afparedes123/App-Conjunto-Habitacional/.venv/bin/python /home/antigravity/Afparedes123/App-Conjunto-Habitacional/services/financial_service.py --tarea alicuotas --monto-base 2500 >> /var/log/condo_alicuotas.log 2>&1

# Día 11 de cada mes a las 00:05 UTC: Aplicar multas por mora
5 0 11 * * /home/antigravity/Afparedes123/App-Conjunto-Habitacional/.venv/bin/python /home/antigravity/Afparedes123/App-Conjunto-Habitacional/services/financial_service.py --tarea multas --porcentaje-multa 10 >> /var/log/condo_multas.log 2>&1
```

### Opción C: Celery Beat + Redis / RabbitMQ (SaaS Empresarial)
Para arquitecturas multi-tenant distribuidas con múltiples réplicas de API:
```python
# celery_app.py
from celery import Celery
from celery.schedules import crontab

app = Celery("condo_tasks", broker="redis://localhost:6379/0")

app.conf.beat_schedule = {
    "generar-alicuotas-dia-1": {
        "task": "tasks.job_generar_alicuotas",
        "schedule": crontab(day_of_month=1, hour=0, minute=5),
    },
    "aplicar-multas-dia-11": {
        "task": "tasks.job_aplicar_multas",
        "schedule": crontab(day_of_month=11, hour=0, minute=5),
    },
}
```

---

## 🚀 Puesta en Marcha y Pruebas

### 1. Instalación de dependencias
```bash
uv venv
uv pip install fastapi uvicorn "pydantic[email]" pyjwt bcrypt passlib httpx pytest sqlalchemy apscheduler
source .venv/bin/activate
```

### 2. Ejecutar la Suite Completa de Pruebas
```bash
pytest -v test_api.py
```

Resultado verificado:
```
test_api.py::test_auth_login_invalid_credentials PASSED                  [ 11%]
test_api.py::test_auth_login_success_roles PASSED                        [ 22%]
test_api.py::test_get_perfil_without_token PASSED                        [ 33%]
test_api.py::test_get_perfil_with_valid_token PASSED                     [ 44%]
test_api.py::test_unidades_rbac_protection PASSED                        [ 55%]
test_api.py::test_pagos_rbac_and_creation PASSED                         [ 66%]
test_api.py::test_generar_alicuotas_mensuales_logic PASSED               [ 77%]
test_api.py::test_aplicar_multas_por_mora_logic PASSED                   [ 88%]
test_api.py::test_estado_cuenta_endpoint_rbac_and_data PASSED            [100%]
========================= 9 passed in 4.44s =========================
```

### 3. Iniciar el Servidor de API
```bash
python main.py
# Servidor en http://localhost:8000
# Swagger UI en http://localhost:8000/docs
```
