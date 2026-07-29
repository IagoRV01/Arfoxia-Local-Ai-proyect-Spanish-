import { modelForMode, requestedModelMode } from './modelMode';
import type {
  DetailedGpuStatus,
  ModelStatus,
  PcStatus,
  RequestedModelMode,
} from './types';

export interface DisplayGpuStatus {
  index: number;
  uuid: string;
  name: string;
  role: string;
  total_vram_gb: number;
  used_vram_gb: number;
  free_vram_gb: number;
  utilization_percent: number;
  temperature_c: number;
  driver_version?: string;
  pci_bus_id?: string;
  power_draw_w?: number;
  power_limit_w?: number;
  active: boolean;
  model: string | null;
  status: string;
}

function finite(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value)
    ? value
    : fallback;
}

function normalizedRole(role: unknown): string {
  return typeof role === 'string' && role.trim()
    ? role.trim().toLowerCase()
    : 'unknown';
}

export function isGamingGpu(role: string): boolean {
  return ['gaming', 'game', 'gaming_gpu', 'secondary'].includes(
    normalizedRole(role),
  );
}

export function isAiGpu(role: string): boolean {
  return ['ai', 'ia', 'arfoxia', 'primary', 'compute'].includes(
    normalizedRole(role),
  );
}

export function gpuRoleLabel(role: string, index: number): string {
  if (isGamingGpu(role)) {
    return 'GPU de juego';
  }
  if (isAiGpu(role)) {
    return 'GPU de Arfoxia';
  }
  return `GPU ${index + 1}`;
}

export function modeUsesGpu(
  mode: RequestedModelMode,
  gpu: Pick<DetailedGpuStatus, 'role'>,
): boolean {
  return mode === 'gaming_gpu' ? isGamingGpu(gpu.role) : isAiGpu(gpu.role);
}

function loadedModelForGpu(
  gpu: Pick<DetailedGpuStatus, 'index' | 'uuid'>,
  status: ModelStatus | null,
) {
  return status?.loaded_models?.find((loaded) => {
    if (loaded.gpu_uuid && gpu.uuid) {
      return loaded.gpu_uuid.toLowerCase() === gpu.uuid.toLowerCase();
    }
    return loaded.gpu_index === gpu.index;
  });
}

function normalizeGpu(
  gpu: DetailedGpuStatus,
  status: ModelStatus | null,
): DisplayGpuStatus {
  const total = Math.max(
    0,
    finite(
      gpu.total_gb,
      finite(
        gpu.total_vram_gb,
        finite(gpu.memory_total_mb) / 1024,
      ),
    ),
  );
  const used = Math.max(
    0,
    finite(
      gpu.used_gb,
      finite(gpu.used_vram_gb, finite(gpu.memory_used_mb) / 1024),
    ),
  );
  const free = Math.max(
    0,
    finite(
      gpu.free_gb,
      finite(
        gpu.free_vram_gb,
        finite(gpu.memory_free_mb, Math.max(0, total - used) * 1024) /
          1024,
      ),
    ),
  );
  const selectedMode = requestedModelMode(status);
  const loaded = loadedModelForGpu(gpu, status);
  const assigned = modeUsesGpu(selectedMode, gpu);
  const gamingServerActive =
    isGamingGpu(gpu.role) &&
    status?.gaming_gpu_server_running === true &&
    Boolean(status.gaming_gpu_loaded_models?.length);
  const gamingLoaded = isGamingGpu(gpu.role)
    ? status?.gaming_gpu_loaded_models?.[0]
    : undefined;
  const mainServerLoaded =
    isAiGpu(gpu.role) &&
    selectedMode !== 'gaming_gpu' &&
    Boolean(status?.loaded_models?.length);
  const active =
    typeof gpu.active === 'boolean'
      ? gpu.active
      : Boolean(loaded || gamingServerActive || mainServerLoaded);
  const model =
    gpu.model ??
    loaded?.name ??
    gamingLoaded?.name ??
    (assigned ? status?.model ?? modelForMode(status, selectedMode) : null) ??
    null;

  return {
    index: Math.max(0, Math.round(finite(gpu.index))),
    uuid: typeof gpu.uuid === 'string' ? gpu.uuid : '',
    name:
      typeof gpu.name === 'string' && gpu.name.trim()
        ? gpu.name.trim()
        : `GPU ${Math.max(0, Math.round(finite(gpu.index))) + 1}`,
    role: normalizedRole(gpu.role),
    total_vram_gb: total,
    used_vram_gb: Math.min(used, total || used),
    free_vram_gb: Math.min(free, total || free),
    utilization_percent: Math.max(
      0,
      Math.min(100, finite(gpu.utilization_percent)),
    ),
    temperature_c: Math.max(0, finite(gpu.temperature_c)),
    driver_version: gpu.driver_version,
    pci_bus_id: gpu.pci_bus_id,
    power_draw_w:
      typeof gpu.power_draw_w === 'number' ? gpu.power_draw_w : undefined,
    power_limit_w:
      typeof gpu.power_limit_w === 'number' ? gpu.power_limit_w : undefined,
    active,
    model,
    status:
      typeof gpu.status === 'string' && gpu.status.trim()
        ? gpu.status.trim()
        : active
          ? 'Modelo activo'
          : assigned
            ? 'Perfil asignado'
          : 'Disponible',
  };
}

export function displayGpus(
  status: ModelStatus | null,
  pc: PcStatus | null,
): DisplayGpuStatus[] {
  const detailed = status?.gpus?.length
    ? [
        ...status.gpus.map((modelGpu) => ({
          ...(pc?.gpus?.find(
            (pcGpu) =>
              (modelGpu.uuid &&
                pcGpu.uuid.toLowerCase() === modelGpu.uuid.toLowerCase()) ||
              pcGpu.index === modelGpu.index,
          ) ?? {}),
          ...modelGpu,
        })),
        ...(pc?.gpus?.filter(
          (pcGpu) =>
            !status.gpus?.some(
              (modelGpu) =>
                (pcGpu.uuid &&
                  modelGpu.uuid.toLowerCase() === pcGpu.uuid.toLowerCase()) ||
                modelGpu.index === pcGpu.index,
            ),
        ) ?? []),
      ]
    : pc?.gpus?.length
      ? pc.gpus
      : null;

  if (detailed) {
    return detailed
      .map((gpu) => normalizeGpu(gpu, status))
      .sort((left, right) => left.index - right.index);
  }

  if (!pc?.gpu && !status?.gpu) {
    return [];
  }

  const total =
    pc?.gpu && finite(pc.gpu.memory_total_mb) > 0
      ? pc.gpu.memory_total_mb / 1024
      : finite(status?.gpu?.total_gb);
  const used = pc?.gpu
    ? finite(pc.gpu.memory_used_mb) / 1024
    : Math.max(0, total - finite(status?.gpu?.free_gb, total));

  return [
    normalizeGpu(
      {
        index: 0,
        uuid: '',
        name: 'GPU NVIDIA',
        role: 'ai',
        total_gb: total,
        used_gb: used,
        free_gb: Math.max(
          0,
          finite(status?.gpu?.free_gb, total - used),
        ),
        utilization_percent: finite(pc?.gpu?.utilization_percent),
        temperature_c: finite(pc?.gpu?.temperature_c),
      },
      status,
    ),
  ];
}

export function shortGpuUuid(uuid: string): string {
  if (!uuid) {
    return '';
  }
  return uuid.length > 18
    ? `${uuid.slice(0, 10)}…${uuid.slice(-6)}`
    : uuid;
}
