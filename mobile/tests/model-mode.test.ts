import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MODEL_MODE_ENDPOINT,
  modelModeButtonLabel,
  modelModeActionLabel,
  modelModeAvailable,
  modelModeReason,
  modelModeRequest,
  modelTierLabel,
  nextRequestedModelMode,
  requestedModelMode,
} from '../src/modelMode';
import type { ModelStatus } from '../src/types';

test('dual is manual, game-gated, and never offered by an older backend', () => {
  assert.deepEqual(modelModeRequest('dual'), { mode: 'dual' });
  assert.equal(modelModeAvailable(status(), 'dual'), false);
  const dual = status({ requested_mode: 'dual', model_mode: 'dual', dual_model_installed: true });
  assert.equal(requestedModelMode(dual), 'dual');
  assert.equal(modelTierLabel(dual), 'DUAL');
  assert.equal(nextRequestedModelMode(dual), 'normal');
  assert.equal(modelModeAvailable(dual, 'dual'), true);
  assert.equal(modelModeAvailable({ ...dual, dual_blocked_by_game: true }, 'dual'), false);
  assert.equal(modelModeAvailable({ ...dual, game: { active: false, processes: [], error: 'probe failed' } }, 'dual'), false);
});

function status(overrides: Partial<ModelStatus> = {}): ModelStatus {
  return {
    requested_mode: 'normal',
    model_mode: 'large',
    model: 'qwen3.5:9b-q4_K_M',
    small_model: 'qwen3.5:4b',
    gaming_gpu_model: 'qwen3.5:4b',
    gaming_gpu_model_installed: true,
    power_model: 'qwen3.6:27b-q4_K_M',
    power_model_installed: true,
    power_context_tokens: 16_384,
    switching: false,
    ...overrides,
  };
}

test('uses the authenticated model mode endpoint with the exact strict body', () => {
  assert.equal(MODEL_MODE_ENDPOINT, '/api/model/mode');
  assert.deepEqual(modelModeRequest('power'), { mode: 'power' });
  assert.deepEqual(modelModeRequest('normal'), { mode: 'normal' });
  assert.deepEqual(modelModeRequest('gaming_gpu'), { mode: 'gaming_gpu' });
});

test('selects the lightweight model on the gaming GPU with its own state', () => {
  const gaming = status({
    requested_mode: 'gaming_gpu',
    model_mode: 'small',
    model: 'qwen3.5:4b',
  });

  assert.equal(requestedModelMode(gaming), 'gaming_gpu');
  assert.equal(nextRequestedModelMode(gaming), 'normal');
  assert.equal(modelModeActionLabel(gaming, 'gaming_gpu'), 'Activo');
  assert.equal(modelTierLabel(gaming), 'LIGERO');
  assert.equal(modelModeAvailable(gaming, 'gaming_gpu'), true);
});

test('disables the gaming GPU mode while a game is active', () => {
  const blocked = status({ gaming_gpu_blocked_by_game: true });

  assert.equal(modelModeAvailable(blocked, 'gaming_gpu'), false);
  assert.equal(
    modelModeActionLabel(blocked, 'gaming_gpu'),
    'Bloqueado mientras juegas',
  );
});

test('explains a failed game probe without claiming that a game is running', () => {
  const blocked = status({
    gaming_gpu_blocked_by_game: true,
    game: {
      active: false,
      processes: [],
      error: 'nvidia-smi no disponible',
    },
  });

  assert.equal(modelModeAvailable(blocked, 'gaming_gpu'), false);
  assert.equal(
    modelModeActionLabel(blocked, 'gaming_gpu'),
    'Esperando comprobación de juegos',
  );
});

test('one tap moves from normal to power and then back to normal', () => {
  const normal = status();
  const power = status({
    requested_mode: 'power',
    model_mode: 'power',
  });

  assert.equal(requestedModelMode(normal), 'normal');
  assert.equal(nextRequestedModelMode(normal), 'power');
  assert.equal(modelModeButtonLabel(normal), 'Activar modo Potencia');
  assert.equal(modelTierLabel(normal), 'NORMAL');

  assert.equal(requestedModelMode(power), 'power');
  assert.equal(nextRequestedModelMode(power), 'normal');
  assert.equal(modelModeButtonLabel(power), 'Volver al modo normal');
  assert.equal(modelTierLabel(power), 'POTENCIA');
});

test('reports loading and missing power model states without claiming activation', () => {
  const loading = status({
    requested_mode: 'power',
    model_mode: 'large',
    switching: true,
  });
  const missing = status({ power_model_installed: false });

  assert.equal(modelModeButtonLabel(loading), 'Cargando Potencia…');
  assert.equal(modelTierLabel(loading), 'NORMAL');
  assert.equal(modelModeButtonLabel(missing), 'Modelo Potencia no instalado');
});

test('reports the remote switching target even before requested mode changes', () => {
  assert.equal(
    modelModeButtonLabel(
      status({
        requested_mode: 'normal',
        switching: true,
        switching_to: 'power',
      }),
    ),
    'Cargando Potencia…',
  );
  assert.equal(
    modelModeButtonLabel(
      status({
        requested_mode: 'normal',
        switching: true,
        switching_to: 'gaming_gpu',
      }),
    ),
    'Cargando modelo en GPU de 8 GB…',
  );
});

test('normal remains available when only the lightweight fallback is installed', () => {
  assert.equal(
    modelModeAvailable(
      status({
        large_model_installed: false,
        small_model_installed: true,
      }),
      'normal',
    ),
    true,
  );
});

test('explains power success and runtime fallback in Spanish', () => {
  assert.equal(
    modelModeReason(status({ reason: 'manual_power' })),
    'Modo Potencia seleccionado',
  );
  assert.equal(
    modelModeReason(status({ reason: 'power_runtime_failed' })),
    'El modelo Potencia falló y Arfoxia mantiene el modo normal',
  );
  assert.equal(
    modelModeReason(status({ reason: 'gaming_gpu_selected' })),
    'Modelo ligero activo en la GPU de juego',
  );
});
