/**
 * Componente Funcional de React: GuardScanner.jsx
 * Diseñado para tablets o dispositivos móviles del personal de garita.
 *
 * Dependencias sugeridas en package.json:
 *   "html5-qrcode": "^2.3.8",
 *   "lucide-react": "^0.300.0" (opcional para íconos)
 *
 * Guía de Configuración de Permisos de Cámara:
 * 1. HTTPS Obligatorio: En navegadores modernos (Chrome, Safari, Firefox), `navigator.mediaDevices.getUserMedia`
 *    está bloqueado en HTTP no seguro (excepto `localhost`). En producción sobre tablets en LAN, use HTTPS.
 * 2. `facingMode: "environment"`: Indica al navegador que use la cámara trasera de la tablet.
 * 3. Permisos en Android/iPad: En Chrome para Android, configurar 'Sitios web -> Cámara -> Permitir siempre'.
 */

import React, { useEffect, useRef, useState, useCallback } from "react";
import { Html5Qrcode } from "html5-qrcode";

export default function GuardScanner({ apiBaseUrl = "", authToken = "", onAccessLogged }) {
  const [scanResult, setScanResult] = useState(null); // { allowed: bool, title: string, details: object, message: string }
  const [isProcessing, setIsProcessing] = useState(false);
  const [countdown, setCountdown] = useState(3);
  const [cameraError, setCameraError] = useState(null);
  const [isScanning, setIsScanning] = useState(false);

  const scannerRef = useRef(null);
  const html5QrCodeRef = useRef(null);
  const countdownTimerRef = useRef(null);
  const resumeTimeoutRef = useRef(null);

  // Síntesis auditiva básica para garita
  const playAudioTone = (isSuccess) => {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);

      if (isSuccess) {
        osc.type = "sine";
        osc.frequency.setValueAtTime(587.33, ctx.currentTime);
        osc.frequency.setValueAtTime(880, ctx.currentTime + 0.12);
        gain.gain.setValueAtTime(0.3, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.45);
        osc.start();
        osc.stop(ctx.currentTime + 0.45);
      } else {
        osc.type = "sawtooth";
        osc.frequency.setValueAtTime(160, ctx.currentTime);
        gain.gain.setValueAtTime(0.4, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
        osc.start();
        osc.stop(ctx.currentTime + 0.5);
      }
    } catch (e) {
      console.warn("Audio Context error:", e);
    }
  };

  // Reanudar escáner tras el temporizador de 3 segundos
  const resumeScanner = useCallback(() => {
    if (countdownTimerRef.current) clearInterval(countdownTimerRef.current);
    if (resumeTimeoutRef.current) clearTimeout(resumeTimeoutRef.current);

    setScanResult(null);
    setIsProcessing(false);
    setCountdown(3);

    if (html5QrCodeRef.current && html5QrCodeRef.current.isScanning) {
      try {
        html5QrCodeRef.current.resume();
      } catch (err) {
        console.warn("Error al reanudar cámara:", err);
      }
    }
  }, []);

  // Validación de pase con la API Backend
  const handleValidatePass = async (qrHash) => {
    if (isProcessing) return;
    setIsProcessing(true);

    // Pausar escáner momentáneamente
    if (html5QrCodeRef.current && html5QrCodeRef.current.isScanning) {
      try {
        await html5QrCodeRef.current.pause();
      } catch (err) {
        console.warn("Error al pausar:", err);
      }
    }

    try {
      const response = await fetch(`${apiBaseUrl}/api/seguridad/validar-pase`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({ hash_qr: qrHash }),
      });

      const data = await response.json();

      if (response.ok && data.acceso_permitido) {
        // 🟢 Acceso Concedido
        playAudioTone(true);
        setScanResult({
          allowed: true,
          title: "ACCESO PERMITIDO",
          visitor: data.nombre_visitante,
          unit: data.unidad_destino,
          type: data.tipo_visita,
          guard: data.guardia_nombre,
        });
        if (onAccessLogged) onAccessLogged(data);
      } else {
        // 🔴 Acceso Denegado
        playAudioTone(false);
        setScanResult({
          allowed: false,
          title: "ACCESO DENEGADO",
          message: data.detail || "Pase no encontrado o expirado",
        });
      }
    } catch (error) {
      playAudioTone(false);
      setScanResult({
        allowed: false,
        title: "ERROR DE CONEXIÓN",
        message: "No se pudo contactar al servidor: " + error.message,
      });
    }

    // Temporizador de cuenta regresiva de 3 segundos
    let remaining = 3;
    setCountdown(3);
    countdownTimerRef.current = setInterval(() => {
      remaining -= 1;
      setCountdown(remaining);
      if (remaining <= 0) {
        clearInterval(countdownTimerRef.current);
      }
    }, 1000);

    // Reanudar automáticamente a los 3 segundos
    resumeTimeoutRef.current = setTimeout(() => {
      resumeScanner();
    }, 3000);
  };

  // Inicialización de Html5Qrcode
  useEffect(() => {
    const elementId = "qr-reader-container";
    const qrScanner = new Html5Qrcode(elementId);
    html5QrCodeRef.current = qrScanner;

    const qrConfig = {
      fps: 15,
      qrbox: { width: 260, height: 260 },
      aspectRatio: 1.0,
    };

    // Solicitar cámara trasera por defecto
    qrScanner
      .start(
        { facingMode: "environment" },
        qrConfig,
        (decodedText) => handleValidatePass(decodedText),
        () => {} // Ignorar errores de frames continuos sin QR
      )
      .then(() => {
        setIsScanning(true);
        setCameraError(null);
      })
      .catch((err) => {
        console.error("Error al arrancar cámara:", err);
        setCameraError("No se pudo iniciar la cámara. Verifique permisos HTTPS y configuración del navegador.");
        setIsScanning(false);
      });

    // Cleanup al desmontar el componente
    return () => {
      if (countdownTimerRef.current) clearInterval(countdownTimerRef.current);
      if (resumeTimeoutRef.current) clearTimeout(resumeTimeoutRef.current);
      if (qrScanner && qrScanner.isScanning) {
        qrScanner.stop().catch(() => {});
      }
    };
  }, []);

  return (
    <div className="relative w-full max-w-xl mx-auto bg-slate-900 border-2 border-slate-800 rounded-3xl p-6 shadow-2xl text-slate-100 flex flex-col items-center select-none">
      <div className="w-full flex items-center justify-between pb-4 border-b border-slate-800 mb-4">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-emerald-500 animate-pulse"></span>
            Escáner Garita
          </h2>
          <p className="text-xs text-slate-400">Control de Visitas con Código QR</p>
        </div>
        <span className="text-xs px-2.5 py-1 bg-slate-800 border border-slate-700 rounded-full font-mono text-emerald-400">
          {isScanning ? "Cámara Activa" : "Iniciando..."}
        </span>
      </div>

      {cameraError && (
        <div className="w-full bg-rose-950/80 border border-rose-600 rounded-xl p-3 text-xs text-rose-200 mb-4 text-center">
          {cameraError}
        </div>
      )}

      {/* Contenedor del Visor de Cámara */}
      <div className="relative w-full aspect-square max-w-sm rounded-2xl overflow-hidden bg-black border border-slate-800 flex items-center justify-center">
        <div id="qr-reader-container" className="w-full h-full" ref={scannerRef}></div>
      </div>

      <p className="text-xs text-slate-400 mt-4 text-center">
        Apunte la cámara hacia el pase QR en la pantalla del visitante o papel impreso.
      </p>

      {/* =====================================================================
          BANNER GIGANTE DE ALERTA (SUPERPUESTO EN PANTALLA COMPLETA)
          ===================================================================== */}
      {scanResult && (
        <div className="absolute inset-0 z-50 bg-slate-950/95 backdrop-blur-md rounded-3xl p-6 flex flex-col items-center justify-center text-center animate-fade-in">
          <div
            className={`w-full rounded-2xl p-8 flex flex-col items-center border-4 shadow-2xl ${
              scanResult.allowed
                ? "bg-emerald-950/90 border-emerald-500 text-emerald-100 shadow-emerald-500/20"
                : "bg-rose-950/90 border-rose-500 text-rose-100 shadow-rose-500/20"
            }`}
          >
            <div
              className={`w-20 h-20 rounded-full flex items-center justify-center text-4xl mb-4 border-2 ${
                scanResult.allowed
                  ? "bg-emerald-500/20 text-emerald-400 border-emerald-400"
                  : "bg-rose-500/20 text-rose-400 border-rose-400"
              }`}
            >
              {scanResult.allowed ? "✓" : "✕"}
            </div>

            <h3
              className={`text-2xl sm:text-3xl font-extrabold uppercase tracking-tight mb-2 ${
                scanResult.allowed ? "text-emerald-400" : "text-rose-400"
              }`}
            >
              {scanResult.title}
            </h3>

            {scanResult.allowed ? (
              <div className="space-y-1 mb-6">
                <p className="text-xl font-bold text-white">{scanResult.visitor}</p>
                <p className="text-lg text-emerald-300 font-semibold">
                  Destino: Unidad {scanResult.unit}
                </p>
                <p className="text-xs text-slate-300">
                  Tipo: <span className="uppercase">{scanResult.type}</span> • Guardia:{" "}
                  {scanResult.guard}
                </p>
              </div>
            ) : (
              <p className="text-base font-semibold text-rose-300 mb-6">
                {scanResult.message}
              </p>
            )}

            {/* Cuenta Regresiva de 3 Segundos */}
            <div className="w-48 bg-slate-800 h-2 rounded-full overflow-hidden mb-2">
              <div
                className={`h-full transition-all duration-1000 ${
                  scanResult.allowed ? "bg-emerald-400" : "bg-rose-400"
                }`}
                style={{ width: `${(countdown / 3) * 100}%` }}
              ></div>
            </div>

            <p className="text-xs text-slate-400">
              Reanudando en <span className="font-bold text-white">{countdown}</span> segundos...
            </p>

            <button
              onClick={resumeScanner}
              className="mt-6 px-6 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-semibold border border-slate-700 transition"
            >
              Escanear Siguiente Ahora
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
