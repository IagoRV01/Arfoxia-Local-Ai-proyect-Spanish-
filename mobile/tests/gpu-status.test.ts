import assert from 'node:assert/strict';
import test from 'node:test';

import {
  displayGpus,
  gpuRoleLabel,
  modeUsesGpu,
  shortGpuUuid,
} from '../src/gpuStatus';
import type { ModelStatus, PcStatus } from '../src/types';

const dualGpuStatus: ModelStatus = {
  requested_mode: 'gaming_gpu',
  model_mode: 'small',
  model: 'qwen3.5:4b',
  small_model: 'qwen3.5:4b',
  gaming_gpu_model: 'qwen3.5:4b',
  gaming_gpu_server_running: true,
  gaming_gpu_loaded_models: [{ name: 'qwen3.5:4b', vram_gb: 4.2 }],
  gpus: [
    {
      index: 0,
      uuid: 'GPU-a068595b-3e42-ee40-6292-5572abbbdc72',
      name: 'NVIDIA GeForce RTX 5060 Ti',
      role: 'gaming',
      total_gb: 8,
      used_gb: 4.5,
      free_gb: 3.5,
      utilization_percent: 76,
      temperature_c: 61,
    },
    {
      index: 1,
      uuid: 'GPU-1ad4d697-126f-1101-233d-e079c4eb6f3b',
      name: 'NVIDIA GeForce RTX 5060 Ti',
      role: 'ai',
      total_gb: 16,
      used_gb: 0.8,
      free_gb: 15.2,
      utilization_percent: 4,
      temperature_c: 37,
    },
  ],
};

test('keeps both GPUs separate and assigns the small model to gaming', () => {
  const pc: PcStatus = {
    gpus: [
      {
        index: 0,
        uuid: 'GPU-a068595b-3e42-ee40-6292-5572abbbdc72',
        name: 'NVIDIA GeForce RTX 5060 Ti',
        role: 'gaming',
        utilization_percent: 77,
        temperature_c: 62,
        memory_total_mb: 8192,
        memory_used_mb: 4608,
        memory_free_mb: 3584,
        driver_version: '591.86',
        pci_bus_id: '00000000:04:00.0',
        power_draw_w: 83,
        power_limit_w: 180,
      },
    ],
  };
  const gpus = displayGpus(dualGpuStatus, pc);

  assert.equal(gpus.length, 2);
  assert.equal(gpuRoleLabel(gpus[0].role, gpus[0].index), 'GPU de juego');
  assert.equal(gpus[0].total_vram_gb, 8);
  assert.equal(gpus[0].free_vram_gb, 3.5);
  assert.equal(gpus[0].active, true);
  assert.equal(gpus[0].model, 'qwen3.5:4b');
  assert.equal(gpus[0].driver_version, '591.86');
  assert.equal(gpus[0].power_draw_w, 83);
  assert.equal(gpuRoleLabel(gpus[1].role, gpus[1].index), 'GPU de Arfoxia');
  assert.equal(gpus[1].active, false);
});

test('maps Normal and Potencia to AI and gaming_gpu to the game card', () => {
  assert.equal(modeUsesGpu('gaming_gpu', dualGpuStatus.gpus![0]), true);
  assert.equal(modeUsesGpu('normal', dualGpuStatus.gpus![0]), false);
  assert.equal(modeUsesGpu('normal', dualGpuStatus.gpus![1]), true);
  assert.equal(modeUsesGpu('power', dualGpuStatus.gpus![1]), true);
});

test('falls back to the previous single-GPU telemetry payload', () => {
  const pc: PcStatus = {
    gpu: {
      utilization_percent: 12,
      memory_used_mb: 2048,
      memory_total_mb: 8192,
      temperature_c: 42,
    },
  };
  const legacyModel: ModelStatus = {
    requested_mode: 'normal',
    model_mode: 'large',
    model: 'qwen3.5:9b-q4_K_M',
    gpu: { total_gb: 8, free_gb: 6 },
  };
  const gpus = displayGpus(legacyModel, pc);

  assert.equal(gpus.length, 1);
  assert.equal(gpus[0].used_vram_gb, 2);
  assert.equal(gpus[0].total_vram_gb, 8);
  assert.equal(gpus[0].utilization_percent, 12);
});

test('shortens long GPU identifiers for a compact phone card', () => {
  assert.equal(shortGpuUuid(''), '');
  assert.equal(
    shortGpuUuid('GPU-a068595b-3e42-ee40-6292-5572abbbdc72'),
    'GPU-a06859…bbdc72',
  );
});
