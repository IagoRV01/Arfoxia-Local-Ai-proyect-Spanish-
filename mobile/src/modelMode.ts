import type { ModelStatus, RequestedModelMode } from './types';

export const MODEL_MODE_ENDPOINT = '/api/model/mode';
export const MODEL_MODES: RequestedModelMode[] = [
  'gaming_gpu',
  'normal',
  'power',
  'dual',
];

export function modelModeRequest(mode: RequestedModelMode): {
  mode: RequestedModelMode;
} {
  return { mode };
}

export function requestedModelMode(
  status: ModelStatus | null,
): RequestedModelMode {
  if (
    status?.requested_mode === 'gaming_gpu' ||
    status?.requested_mode === 'power' || status?.requested_mode === 'dual'
  ) {
    return status.requested_mode;
  }
  return 'normal';
}

// Kept for older consumers that present Normal/Potencia as a two-state toggle.
export function nextRequestedModelMode(
  status: ModelStatus | null,
): RequestedModelMode {
  return requestedModelMode(status) === 'normal' ? 'power' : 'normal';
}

export function modelTierLabel(status: ModelStatus | null): string {
  if (status?.model_mode === 'dual') return 'DUAL';
  if (
    requestedModelMode(status) === 'gaming_gpu' ||
    status?.model_mode === 'small'
  ) {
    return 'LIGERO';
  }
  if (status?.model_mode === 'power') {
    return 'POTENCIA';
  }
  if (status?.model_mode === 'large') {
    return 'NORMAL';
  }
  return '—';
}

export function modelModeTitle(mode: RequestedModelMode): string {
  const labels: Record<RequestedModelMode, string> = {
    gaming_gpu: 'Ligero · GPU de juego',
    normal: 'Normal · GPU de IA',
    power: 'Potencia · GPU de IA',
    dual: 'Dual · Extra High',
  };
  return labels[mode];
}

export function modelModeDescription(mode: RequestedModelMode): string {
  const descriptions: Record<RequestedModelMode, string> = {
    gaming_gpu: 'Modelo pequeño en la gráfica de 8 GB',
    normal: 'Modelo habitual, rápido y equilibrado',
    power: 'Qwen3.6 para las tareas más exigentes',
    dual: 'Qwen3.8 27B Extra High · 16 + 5,5 GB · descarga manual',
  };
  return descriptions[mode];
}

export function modelForMode(
  status: ModelStatus | null,
  mode: RequestedModelMode,
): string | undefined {
  if (mode === 'dual') return status?.dual_model;
  if (mode === 'gaming_gpu') {
    return status?.gaming_gpu_model ?? status?.small_model;
  }
  if (mode === 'power') {
    return status?.power_model;
  }
  return status?.large_model;
}

export function modelModeAvailable(
  status: ModelStatus | null,
  mode: RequestedModelMode,
): boolean {
  if (!status) {
    return false;
  }
  if (mode === 'dual') {
    return status.dual_model_installed === true && !status.dual_blocked_by_game &&
      !status.game?.active && !status.game?.error;
  }
  if (mode === 'power') {
    return status.power_model_installed !== false;
  }
  if (mode === 'normal') {
    return (
      status.large_model_installed !== false ||
      status.small_model_installed !== false
    );
  }
  return (
    status.gaming_gpu_blocked_by_game !== true &&
    status.gaming_gpu_model_installed !== false &&
    status.small_model_installed !== false &&
    !(
      status.gaming_gpu_server_running === true &&
      status.gaming_gpu_server_owned === false
    )
  );
}

export function modelModeActionLabel(
  status: ModelStatus | null,
  mode: RequestedModelMode,
): string {
  if (!status) {
    return 'Consultando…';
  }
  if (requestedModelMode(status) === mode) {
    return 'Activo';
  }
  if ((mode === 'gaming_gpu' && status.gaming_gpu_blocked_by_game) ||
      (mode === 'dual' && (status.dual_blocked_by_game || status.game?.active || status.game?.error))) {
    return status.game?.error
      ? 'Esperando comprobación de juegos'
      : 'Bloqueado mientras juegas';
  }
  if (
    mode === 'gaming_gpu' &&
    status.gaming_gpu_server_running === true &&
    status.gaming_gpu_server_owned === false
  ) {
    return 'Puerto privado ocupado';
  }
  if (!modelModeAvailable(status, mode)) {
    return 'No instalado';
  }
  if (mode === 'dual') return 'Activar Dual';
  if (mode === 'gaming_gpu') {
    return 'Usar GPU de 8 GB';
  }
  if (mode === 'power') {
    return 'Activar Potencia';
  }
  return 'Volver a Normal';
}

export function modelModeButtonLabel(status: ModelStatus | null): string {
  if (!status) {
    return 'Consultando modelos…';
  }
  if (status.switching) {
    const switchingTarget =
      status.switching_to ?? requestedModelMode(status);
    if (switchingTarget === 'dual') return 'Cargando Qwen3.8 en ambas GPU…';
    if (switchingTarget === 'power') {
      return 'Cargando Potencia…';
    }
    if (switchingTarget === 'gaming_gpu') {
      return 'Cargando modelo en GPU de 8 GB…';
    }
    return 'Cargando modo normal…';
  }
  if (['power', 'dual'].includes(requestedModelMode(status))) {
    return 'Volver al modo normal';
  }
  if (status.power_model_installed === false) {
    return 'Modelo Potencia no instalado';
  }
  return 'Activar modo Potencia';
}

export function modelModeReason(status: ModelStatus | null): string {
  if (status?.switching_to === 'dual') return 'Cargando el modo Dual sin offload a RAM';
  if (status?.requested_mode === 'dual') return status.dual_warning ||
    'Extra High en ambas GPU · vigilancia cada 20 s · libera la VRAM manualmente antes de jugar';
  if (status?.dual_last_error) return status.dual_last_error;
  if (status?.switching) {
    if (status.switching_to === 'power') {
      return 'Cargando Potencia en la GPU de IA';
    }
    if (status.switching_to === 'gaming_gpu') {
      return 'Cargando el modelo ligero en la GPU de juego';
    }
    return 'Volviendo al perfil normal';
  }
  const reason = status?.reason;
  const messages: Record<string, string> = {
    game_active: 'Modo ligero porque hay un juego activo',
    gaming_gpu_selected: 'Modelo ligero activo en la GPU de juego',
    dual_selected: 'Qwen3.8 activo en ambas GPU',
    dual_runtime_failed: 'El modo Dual se detuvo; Arfoxia vuelve al perfil normal',
    manual_gaming_gpu: 'GPU de juego seleccionada manualmente',
    gaming_gpu_runtime_failed:
      'El modelo ligero no pudo cargarse en la GPU de juego',
    gaming_gpu_busy: 'La GPU de juego está ocupada',
    large_fits: 'Hay VRAM suficiente para el modo normal',
    large_fits_after_reclaim:
      'Modo normal disponible al liberar el modelo anterior',
    power_fits: 'Modo Potencia activo en la gráfica dedicada a Arfoxia',
    power_fits_after_reclaim:
      'Modo Potencia activo tras liberar el modelo anterior',
    manual_normal: 'Modo normal seleccionado',
    manual_power: 'Modo Potencia seleccionado',
    power_selected: 'Modo Potencia activo al 100 % en GPU',
    insufficient_vram: 'No hay suficiente VRAM libre para este modelo',
    gpu_unavailable: 'No se ha podido consultar la GPU de Arfoxia',
    large_not_installed: 'El modelo normal todavía no está instalado',
    power_not_installed: 'El modelo Potencia todavía no está instalado',
    adaptive_disabled: 'Modo normal seleccionado manualmente',
    config_invalid: 'Hay que revisar la configuración del modelo',
    large_runtime_failed: 'El modelo normal falló y Arfoxia usa el ligero',
    power_runtime_failed:
      'El modelo Potencia falló y Arfoxia mantiene el modo normal',
  };
  return (
    (reason && messages[reason]) ||
    reason ||
    'Estado del modelo no disponible'
  );
}
