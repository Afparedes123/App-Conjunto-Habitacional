/**
 * Componente Funcional de React: ResidentReservations.jsx
 * Módulo de Convivencia y Reservas de Áreas Comunales para el Portal del Residente.
 *
 * Características:
 * - Selección de Área Comunal, fecha y rango de horas.
 * - Validación cruzada y manejo estricto de códigos HTTP del backend:
 *   * HTTP 403: Modal rojo de advertencia por morosidad con redirección a pagos.
 *   * HTTP 409: Alerta amarilla de conflicto de horarios (overlapping).
 *   * HTTP 201: Notificación verde de éxito y actualización inmediata del calendario.
 */

import React, { useState, useEffect, useCallback } from "react";

export default function ResidentReservations({
  apiBaseUrl = "",
  authToken = "",
  onNavigateToBilling = () => {},
}) {
  // Estados del Formulario
  const [areas, setAreas] = useState([]);
  const [selectedAreaId, setSelectedAreaId] = useState("");
  const [date, setDate] = useState(() => new Date().toISOString().split("T")[0]);
  const [timeStart, setTimeStart] = useState("14:00");
  const [timeEnd, setTimeEnd] = useState("18:00");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Estados de Datos
  const [busySlots, setBusySlots] = useState([]);
  const [myReservations, setMyReservations] = useState([]);

  // Estados de Modales y Notificaciones (UI/UX)
  const [delinquencyError, setDelinquencyError] = useState(null); // HTTP 403
  const [conflictWarning, setConflictWarning] = useState(null); // HTTP 409
  const [toast, setToast] = useState(null); // { type: 'success' | 'warning' | 'error', message: string }

  // Función auxiliar para Toasts con auto-cierre
  const triggerToast = useCallback((type, message) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 4000);
  }, []);

  // 1. Cargar Catálogo de Áreas Comunales
  const fetchAreas = useCallback(async () => {
    try {
      const res = await fetch(`${apiBaseUrl}/api/reservas/areas`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (res.ok) {
        const data = await res.json();
        setAreas(data);
        if (data.length > 0 && !selectedAreaId) {
          setSelectedAreaId(data[0].id);
        }
      }
    } catch (err) {
      console.error("Error al cargar áreas:", err);
    }
  }, [apiBaseUrl, authToken, selectedAreaId]);

  // 2. Cargar Franjas Ocupadas del Calendario para el área y fecha elegida
  const fetchBusySlots = useCallback(async () => {
    if (!selectedAreaId || !date) return;
    try {
      const startOfDay = `${date}T00:00:00Z`;
      const endOfDay = `${date}T23:59:59Z`;
      const res = await fetch(
        `${apiBaseUrl}/api/reservas/calendario?area_id=${selectedAreaId}&fecha_desde=${startOfDay}&fecha_hasta=${endOfDay}`,
        {
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        }
      );
      if (res.ok) {
        const slots = await res.json();
        setBusySlots(slots);
      }
    } catch (err) {
      console.error("Error al cargar calendario:", err);
    }
  }, [apiBaseUrl, authToken, selectedAreaId, date]);

  // 3. Cargar Mis Reservas Activas
  const fetchMyReservations = useCallback(async () => {
    if (!authToken) return;
    try {
      const res = await fetch(`${apiBaseUrl}/api/reservas`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (res.ok) {
        const list = await res.json();
        setMyReservations(list);
      }
    } catch (err) {
      console.error("Error al cargar reservas del usuario:", err);
    }
  }, [apiBaseUrl, authToken]);

  useEffect(() => {
    fetchAreas();
  }, [fetchAreas]);

  useEffect(() => {
    fetchBusySlots();
  }, [fetchBusySlots]);

  useEffect(() => {
    fetchMyReservations();
  }, [fetchMyReservations]);

  // 4. Enviar Solicitud de Reserva con Validación Cruzada
  const handleSubmitReservation = async (e) => {
    e.preventDefault();

    if (!authToken) {
      triggerToast("error", "Debe iniciar sesión para realizar reservas.");
      return;
    }

    const inicioIso = new Date(`${date}T${timeStart}:00`).toISOString();
    const finIso = new Date(`${date}T${timeEnd}:00`).toISOString();

    if (new Date(finIso) <= new Date(inicioIso)) {
      triggerToast("warning", "La hora de fin debe ser posterior a la de inicio.");
      return;
    }

    setIsSubmitting(true);

    try {
      const response = await fetch(`${apiBaseUrl}/api/reservas`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken.trim()}`,
        },
        body: JSON.stringify({
          area_id: selectedAreaId,
          fecha_hora_inicio: inicioIso,
          fecha_hora_fin: finIso,
        }),
      });

      const data = await response.json();

      // a) HTTP 403: Bloqueo a Morosos
      if (response.status === 403) {
        setDelinquencyError(
          data.error || data.detail || "Acceso restringido por morosidad."
        );
        triggerToast("error", "Reserva denegada por mora en alícuotas.");
      }
      // b) HTTP 409: Conflicto de Horario (Overlapping)
      else if (response.status === 409) {
        setConflictWarning(
          data.error || data.detail || "El área comunal ya se encuentra reservada en ese horario."
        );
        triggerToast("warning", "Horario no disponible. Elija otra hora.");
      }
      // c) HTTP 201: Éxito
      else if (response.status === 201) {
        triggerToast("success", `¡Reserva creada exitosamente (${data.estado})!`);
        fetchBusySlots();
        fetchMyReservations();
      }
      // Otros
      else {
        triggerToast("error", data.detail || "No se pudo procesar la solicitud.");
      }
    } catch (networkErr) {
      triggerToast("error", "Error de conexión: " + networkErr.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const selectedAreaObj = areas.find((a) => a.id === selectedAreaId);

  return (
    <div className="w-full max-w-5xl mx-auto p-4 sm:p-6 text-slate-100 font-sans">
      {/* Toast Flotante */}
      {toast && (
        <div
          className={`fixed top-5 right-5 z-50 p-4 rounded-2xl border shadow-2xl flex items-center gap-3 text-xs animate-bounce transition-all ${
            toast.type === "success"
              ? "bg-emerald-950/95 border-emerald-500 text-emerald-100"
              : toast.type === "warning"
              ? "bg-amber-950/95 border-amber-500 text-amber-100"
              : "bg-rose-950/95 border-rose-500 text-rose-100"
          }`}
        >
          <span>{toast.type === "success" ? "✅" : toast.type === "warning" ? "⚠️" : "🛑"}</span>
          <p className="font-semibold">{toast.message}</p>
        </div>
      )}

      {/* Grid de Formulario y Calendario */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Formulario */}
        <div className="lg:col-span-5 bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-xl">
          <h2 className="text-lg font-bold text-white mb-1">Nueva Solicitud de Reserva</h2>
          <p className="text-xs text-slate-400 mb-4">Seleccione el área comunal y horario deseado</p>

          <form onSubmit={handleSubmitReservation} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Área Comunal:</label>
              <select
                value={selectedAreaId}
                onChange={(e) => setSelectedAreaId(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2.5 text-sm text-white outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {areas.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.nombre} {a.costo_reserva > 0 ? `($${a.costo_reserva})` : "(Gratis)"}
                  </option>
                ))}
              </select>
              {selectedAreaObj && (
                <div className="mt-2 p-2.5 rounded-xl bg-slate-950/60 border border-slate-800 text-xs text-slate-400 flex justify-between">
                  <span>Aforo: {selectedAreaObj.aforo_maximo} personas</span>
                  <span>{selectedAreaObj.requiere_aprobacion ? "Requiere Aprobación" : "Inmediata"}</span>
                </div>
              )}
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Fecha:</label>
              <input
                type="date"
                value={date}
                min={new Date().toISOString().split("T")[0]}
                onChange={(e) => setDate(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-white outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Inicio:</label>
                <input
                  type="time"
                  value={timeStart}
                  onChange={(e) => setTimeStart(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-white outline-none"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Fin:</label>
                <input
                  type="time"
                  value={timeEnd}
                  onChange={(e) => setTimeEnd(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-sm text-white outline-none"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-3 bg-indigo-600 hover:bg-indigo-500 text-white font-bold rounded-xl text-sm transition shadow-lg shadow-indigo-600/30 flex items-center justify-center gap-2"
            >
              {isSubmitting ? "Validando requisitos..." : "Confirmar Reserva"}
            </button>
          </form>
        </div>

        {/* Panel de Horarios y Mis Reservas */}
        <div className="lg:col-span-7 space-y-6">
          {/* Horarios Ocupados */}
          <div className="bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-xl">
            <h3 className="text-base font-bold text-white mb-1">Disponibilidad del Día</h3>
            <p className="text-xs text-slate-400 mb-3">Franjas horarias ocupadas en la fecha seleccionada</p>
            {busySlots.length === 0 ? (
              <div className="p-3 bg-emerald-950/40 border border-emerald-900/50 rounded-xl text-xs text-emerald-300 text-center">
                ✨ Día disponible sin reservas previas
              </div>
            ) : (
              <div className="space-y-2">
                {busySlots.map((s) => (
                  <div
                    key={s.id}
                    className="flex justify-between items-center p-2.5 rounded-xl bg-slate-950/60 border border-slate-800 text-xs"
                  >
                    <span>
                      {new Date(s.fecha_hora_inicio).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} -{" "}
                      {new Date(s.fecha_hora_fin).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </span>
                    <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-400 uppercase font-bold text-[10px]">
                      {s.estado}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Mis Reservas */}
          <div className="bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-xl">
            <h3 className="text-base font-bold text-white mb-3">Mis Solicitudes de Reserva</h3>
            {myReservations.length === 0 ? (
              <p className="text-xs text-slate-500 italic text-center py-2">No tiene reservas registradas.</p>
            ) : (
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {myReservations.map((r) => (
                  <div
                    key={r.id}
                    className="p-3 bg-slate-950/60 border border-slate-800 rounded-xl flex justify-between items-center text-xs"
                  >
                    <div>
                      <p className="font-bold text-white">{r.area_nombre}</p>
                      <p className="text-[11px] text-slate-400">
                        {new Date(r.fecha_hora_inicio).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}
                      </p>
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded uppercase font-bold text-[10px] ${
                        r.estado === "APROBADA"
                          ? "bg-emerald-500/20 text-emerald-400"
                          : "bg-amber-500/20 text-amber-400"
                      }`}
                    >
                      {r.estado}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* =====================================================================
          MODAL 1: ALERTA ROJA DE MOROSIDAD (HTTP 403)
          ===================================================================== */}
      {delinquencyError && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border-2 border-rose-500 rounded-3xl max-w-md w-full p-6 text-center shadow-2xl">
            <div className="w-16 h-16 rounded-full bg-rose-500/20 text-rose-400 border border-rose-400/40 flex items-center justify-center text-3xl mx-auto mb-4">
              ⚠️
            </div>
            <h3 className="text-xl font-extrabold text-rose-400 uppercase tracking-tight mb-2">
              Acceso Restringido por Morosidad
            </h3>
            <p className="text-xs text-slate-200 mb-6">{delinquencyError}</p>

            <div className="flex gap-2">
              <button
                onClick={() => setDelinquencyError(null)}
                className="flex-1 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-semibold"
              >
                Cerrar
              </button>
              <button
                onClick={() => {
                  setDelinquencyError(null);
                  onNavigateToBilling();
                }}
                className="flex-1 py-2.5 bg-rose-600 hover:bg-rose-500 text-white font-bold rounded-xl text-xs shadow-lg shadow-rose-600/30"
              >
                💳 Pagar Deuda
              </button>
            </div>
          </div>
        </div>
      )}

      {/* =====================================================================
          MODAL 2: ALERTA AMARILLA DE CONFLICTO DE HORARIOS (HTTP 409)
          ===================================================================== */}
      {conflictWarning && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border-2 border-amber-500 rounded-3xl max-w-md w-full p-6 text-center shadow-2xl">
            <div className="w-16 h-16 rounded-full bg-amber-500/20 text-amber-400 border border-amber-400/40 flex items-center justify-center text-3xl mx-auto mb-4">
              📅
            </div>
            <h3 className="text-xl font-extrabold text-amber-400 uppercase tracking-tight mb-2">
              Horario No Disponible
            </h3>
            <p className="text-xs text-slate-200 mb-6">{conflictWarning}</p>

            <button
              onClick={() => setConflictWarning(null)}
              className="w-full py-2.5 bg-amber-600 hover:bg-amber-500 text-white font-bold rounded-xl text-xs"
            >
              Elegir Otro Horario
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
