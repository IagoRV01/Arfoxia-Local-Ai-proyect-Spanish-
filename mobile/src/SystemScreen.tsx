import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { ApiError, ArfoxiaApi } from './api';
import {
  displayGpus,
  gpuRoleLabel,
  isGamingGpu,
  shortGpuUuid,
  type DisplayGpuStatus,
} from './gpuStatus';
import {
  MODEL_MODES,
  modelForMode,
  modelModeActionLabel,
  modelModeAvailable,
  modelModeDescription,
  modelModeReason,
  modelModeTitle,
  modelTierLabel,
  requestedModelMode,
} from './modelMode';
import type {
  ModelStatus,
  PcStatus,
  RequestedModelMode,
} from './types';
import {
  Button,
  Card,
  ErrorBanner,
  Screen,
  ScreenshotModal,
  SectionTitle,
  StatusPill,
  colors,
  sharedStyles,
} from './ui';

type Props = {
  api: ArfoxiaApi;
  onUnauthorized: () => void;
};

const appButtons = [
  { id: 'steam', label: 'Steam' },
  { id: 'discord', label: 'Discord' },
  { id: 'chrome', label: 'Chrome' },
  { id: 'explorer', label: 'Explorador' },
];

function formatNumber(value: number | undefined, suffix = ''): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${Math.round(value)}${suffix}`
    : '—';
}

function formatDecimal(value: number | undefined, suffix = ''): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${value.toFixed(1)}${suffix}`
    : '—';
}

function formatUptime(seconds: number | undefined): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) {
    return '—';
  }
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (days) {
    return `${days} d ${hours} h`;
  }
  if (hours) {
    return `${hours} h ${minutes} min`;
  }
  return `${minutes} min`;
}

function modelBusyKey(mode: RequestedModelMode): string {
  return `model-mode:${mode}`;
}

export function SystemScreen({ api, onUnauthorized }: Props) {
  const [model, setModel] = useState<ModelStatus | null>(null);
  const [pc, setPc] = useState<PcStatus | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [busyAction, setBusyAction] = useState('');
  const [error, setError] = useState('');
  const [screenshotId, setScreenshotId] = useState<string | null>(null);

  const handleError = useCallback(
    (reason: unknown) => {
      if (reason instanceof ApiError && reason.status === 401) {
        onUnauthorized();
        return;
      }
      setError(
        reason instanceof Error
          ? reason.message
          : 'No se ha podido consultar el ordenador.',
      );
    },
    [onUnauthorized],
  );

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError('');
    const [modelResult, pcResult] = await Promise.allSettled([
      api.modelStatus(),
      api.pcStatus(),
    ]);
    if (modelResult.status === 'fulfilled') {
      setModel(modelResult.value);
      if (modelResult.value.error) {
        setError(modelResult.value.error);
      }
    } else {
      handleError(modelResult.reason);
    }
    if (pcResult.status === 'fulfilled') {
      setPc(pcResult.value.status);
      if (!pcResult.value.result.success) {
        setError(pcResult.value.result.message);
      }
    } else {
      handleError(pcResult.reason);
    }
    setRefreshing(false);
  }, [api, handleError]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const switchModelMode = useCallback(
    async (targetMode: RequestedModelMode) => {
      if (requestedModelMode(model) === targetMode) {
        return;
      }
      setBusyAction(modelBusyKey(targetMode));
      setError('');
      try {
        const result = await api.setModelMode(targetMode);
        setModel(result);
        if (result.error) {
          setError(result.error);
        }
        const pcResult = await api.pcStatus();
        setPc(pcResult.status);
        if (!pcResult.result.success) {
          setError(pcResult.result.message);
        }
      } catch (reason) {
        handleError(reason);
      } finally {
        setBusyAction('');
      }
    },
    [api, handleError, model],
  );

  const screenshot = useCallback(async () => {
    setBusyAction('screenshot');
    setError('');
    try {
      const result = await api.action('take_screenshot');
      if (!result.success) {
        throw new Error(result.message);
      }
      const id = result.data?.screenshot_id;
      if (typeof id !== 'string') {
        throw new Error('Arfoxia no ha devuelto la captura.');
      }
      setScreenshotId(id);
    } catch (reason) {
      handleError(reason);
    } finally {
      setBusyAction('');
    }
  }, [api, handleError]);

  const openApp = useCallback(
    async (app: string, label: string) => {
      setBusyAction(app);
      setError('');
      try {
        const result = await api.action('open_app', { app });
        if (result.requires_authorization) {
          Alert.alert(
            'Autorización en el PC',
            'Termina esta autorización en el diálogo privado del ordenador.',
          );
        } else if (!result.success) {
          throw new Error(result.message);
        } else {
          Alert.alert(label, result.message);
        }
      } catch (reason) {
        handleError(reason);
      } finally {
        setBusyAction('');
      }
    },
    [api, handleError],
  );

  const unload = useCallback(() => {
    Alert.alert(
      'Liberar la VRAM',
      'Arfoxia descargará sus modelos de las gráficas. Se volverán a cargar al hablar con ella.',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Liberar',
          onPress: () => {
            setBusyAction('unload');
            void api
              .unloadModel()
              .then(() => {
                Alert.alert(
                  'VRAM liberada',
                  'Los modelos locales se han descargado.',
                );
                return refresh();
              })
              .catch(handleError)
              .finally(() => setBusyAction(''));
          },
        },
      ],
    );
  }, [api, handleError, refresh]);

  const gpus = useMemo(() => displayGpus(model, pc), [model, pc]);
  const currentMode = requestedModelMode(model);
  const gameProbeFailed = Boolean(model?.game?.error);
  const residentModels =
    currentMode === 'dual' ? model?.dual_loaded_models : currentMode === 'gaming_gpu'
      ? model?.gaming_gpu_loaded_models
      : model?.loaded_models;
  const memoryUsed =
    pc?.memory_used_gb ??
    (typeof pc?.memory_total_gb === 'number' &&
    typeof pc?.memory_available_gb === 'number'
      ? Math.max(0, pc.memory_total_gb - pc.memory_available_gb)
      : undefined);
  const systemInfo =
    pc?.system && typeof pc.system === 'object' ? pc.system : null;
  const osName =
    systemInfo?.os_name ||
    pc?.os_name ||
    pc?.os ||
    (typeof pc?.system === 'string' ? pc.system : undefined);
  const osVersion = systemInfo?.os_version || pc?.os_version;
  const uptimeSeconds =
    systemInfo?.uptime_seconds ?? pc?.uptime_seconds;
  const coreSummary =
    typeof pc?.cpu_physical_cores === 'number' ||
    typeof pc?.cpu_logical_cores === 'number'
      ? [
          typeof pc?.cpu_physical_cores === 'number'
            ? `${pc.cpu_physical_cores} físicos`
            : null,
          typeof pc?.cpu_logical_cores === 'number'
            ? `${pc.cpu_logical_cores} hilos`
            : null,
        ]
          .filter(Boolean)
          .join(' · ')
      : typeof pc?.cpu_cores === 'number'
        ? `${pc.cpu_cores} núcleos`
        : '';

  return (
    <Screen
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => void refresh()}
          tintColor={colors.ice}
        />
      }
    >
      <View style={styles.header}>
        <View style={styles.headerText}>
          <Text style={sharedStyles.label}>Control en tiempo real</Text>
          <Text style={sharedStyles.title}>Tu PC</Text>
        </View>
        <StatusPill
          label={
            model?.game?.active
              ? 'Jugando'
              : gameProbeFailed
                ? 'Comprobación pendiente'
                : 'Disponible'
          }
          tone={
            model?.game?.active || gameProbeFailed ? 'warning' : 'success'
          }
        />
      </View>

      {error ? <ErrorBanner message={error} /> : null}

      <Card style={styles.modelCard}>
        <SectionTitle
          title="Arfoxia"
          subtitle={modelModeReason(model)}
          trailing={
            <View style={styles.modeBadge}>
              <Text style={styles.modeBadgeText}>
                {modelTierLabel(model)}
              </Text>
            </View>
          }
        />
        <View style={styles.currentModel}>
          <Text style={styles.currentModelLabel}>Modelo actual</Text>
          <Text style={styles.modelName}>
            {model?.model || 'Consultando…'}
          </Text>
          {residentModels?.length ? (
            <Text style={styles.currentModelMeta}>
              {residentModels.length} modelo
              {residentModels.length === 1 ? '' : 's'} cargado
              {residentModels.length === 1 ? '' : 's'}
            </Text>
          ) : (
            <Text style={styles.currentModelMeta}>
              Sin modelos residentes o estado pendiente
            </Text>
          )}
        </View>

        {model?.game?.active && model.game.processes.length ? (
          <Text style={styles.gameText}>
            Juego detectado: {model.game.processes.join(', ')}
          </Text>
        ) : null}
        {gameProbeFailed ? (
          <Text style={styles.gameText}>
            Arfoxia no puede verificar ahora si la GPU de juego está libre y
            mantendrá bloqueado el perfil de 8 GB.
          </Text>
        ) : null}

        <Text style={styles.subsectionLabel}>Perfil de ejecución</Text>
        <View style={styles.modeList}>
          {MODEL_MODES.map((mode) => (
            <ModeOption
              key={mode}
              mode={mode}
              status={model}
              active={currentMode === mode}
              busy={
                busyAction === modelBusyKey(mode) ||
                Boolean(model?.switching && model.switching_to === mode)
              }
              disabled={
                !model ||
                Boolean(busyAction) ||
                Boolean(model.switching) ||
                !modelModeAvailable(model, mode)
              }
              onPress={() => void switchModelMode(mode)}
            />
          ))}
        </View>

        <Button
          label="Liberar toda la VRAM de Arfoxia"
          variant="ghost"
          busy={busyAction === 'unload'}
          disabled={Boolean(busyAction) || Boolean(model?.switching)}
          onPress={unload}
        />
      </Card>

      <Card style={styles.gpuManagerCard}>
        <SectionTitle
          title="Gestor de GPU"
          subtitle={
            gpus.length > 1
              ? `${gpus.length} gráficas detectadas por separado`
              : 'Telemetría disponible de la gráfica'
          }
        />
        {gpus.length ? (
          <View style={styles.gpuList}>
            {gpus.map((gpu) => (
              <GpuCard
                key={gpu.uuid || String(gpu.index)}
                gpu={gpu}
                gamingModeActive={currentMode === 'gaming_gpu'}
                buttonBusy={
                  busyAction === modelBusyKey('gaming_gpu') ||
                  Boolean(
                    model?.switching &&
                      model.switching_to === 'gaming_gpu',
                  )
                }
                buttonDisabled={
                  !model ||
                  Boolean(busyAction) ||
                  Boolean(model.switching) ||
                  !modelModeAvailable(model, 'gaming_gpu')
                }
                onUseGamingGpu={() =>
                  void switchModelMode('gaming_gpu')
                }
              />
            ))}
          </View>
        ) : (
          <Text style={styles.emptyDetail}>
            Esperando la telemetría individual de las GPU…
          </Text>
        )}
      </Card>

      <Card style={styles.pcCard}>
        <SectionTitle
          title="Sistema"
          subtitle="Información ampliada del ordenador"
        />
        {osName || pc?.cpu_name ? (
          <View style={styles.systemDetails}>
            {osName ? (
              <SystemDetail
                label="Sistema operativo"
                value={[osName, osVersion].filter(Boolean).join(' · ')}
                detail={systemInfo?.architecture}
              />
            ) : null}
            {pc?.cpu_name ? (
              <SystemDetail
                label="Procesador"
                value={pc.cpu_name}
                detail={[
                  coreSummary,
                  typeof pc.cpu_frequency_mhz === 'number'
                    ? `${Math.round(pc.cpu_frequency_mhz)} MHz`
                    : '',
                ]
                  .filter(Boolean)
                  .join(' · ')}
              />
            ) : null}
          </View>
        ) : null}
        <View style={styles.metricsWrap}>
          <Metric label="CPU" value={formatNumber(pc?.cpu_percent, '%')} />
          <Metric label="RAM" value={formatNumber(pc?.memory_percent, '%')} />
          <Metric
            label="RAM usada"
            value={
              typeof memoryUsed === 'number' &&
              typeof pc?.memory_total_gb === 'number'
                ? `${memoryUsed.toFixed(1)} / ${pc.memory_total_gb.toFixed(1)} GB`
                : formatDecimal(memoryUsed, ' GB')
            }
            wide
          />
          <Metric
            label="RAM disponible"
            value={formatDecimal(pc?.memory_available_gb, ' GB')}
            wide
          />
          <Metric label="Disco" value={formatNumber(pc?.disk_percent, '%')} />
          <Metric
            label="Disco libre"
            value={formatDecimal(pc?.disk_free_gb, ' GB')}
          />
          <Metric
            label="Disco usado"
            value={
              typeof pc?.disk_used_gb === 'number' &&
              typeof pc?.disk_total_gb === 'number'
                ? `${pc.disk_used_gb.toFixed(0)} / ${pc.disk_total_gb.toFixed(0)} GB`
                : formatDecimal(pc?.disk_used_gb, ' GB')
            }
            wide
          />
          <Metric
            label="Tiempo activo"
            value={formatUptime(uptimeSeconds)}
            wide
          />
          {pc?.battery ? (
            <Metric
              label="Batería"
              value={`${Math.round(pc.battery.percent)}%${
                pc.battery.plugged ? ' · cargando' : ''
              }`}
              wide
            />
          ) : null}
        </View>
        <Button
          label="Ver captura del monitor"
          icon="▣"
          busy={busyAction === 'screenshot'}
          disabled={Boolean(busyAction)}
          onPress={() => void screenshot()}
        />
      </Card>

      <Card style={styles.appsCard}>
        <SectionTitle
          title="Abrir en el PC"
          subtitle="Aplicaciones autorizadas en Arfoxia"
        />
        <View style={styles.appGrid}>
          {appButtons.map((app) => (
            <Button
              key={app.id}
              label={app.label}
              variant="secondary"
              busy={busyAction === app.id}
              disabled={Boolean(busyAction)}
              onPress={() => void openApp(app.id, app.label)}
              style={styles.appButton}
            />
          ))}
        </View>
      </Card>

      <ScreenshotModal
        visible={Boolean(screenshotId)}
        source={screenshotId ? api.screenshotSource(screenshotId) : null}
        onClose={() => setScreenshotId(null)}
      />
    </Screen>
  );
}

function ModeOption({
  mode,
  status,
  active,
  busy,
  disabled,
  onPress,
}: {
  mode: RequestedModelMode;
  status: ModelStatus | null;
  active: boolean;
  busy: boolean;
  disabled: boolean;
  onPress: () => void;
}) {
  const modelName = modelForMode(status, mode);
  const blocked =
    (mode === 'gaming_gpu' && status?.gaming_gpu_blocked_by_game === true) ||
    (mode === 'dual' && status?.dual_blocked_by_game === true);
  const gameProbeFailed = blocked && Boolean(status?.game?.error);
  const available = modelModeAvailable(status, mode);
  const contextTokens =
    mode === 'dual' ? status?.dual_context_tokens : mode === 'gaming_gpu'
      ? status?.gaming_gpu_context_tokens
      : mode === 'power'
        ? status?.power_context_tokens
        : undefined;
  const modeFacts = [
    typeof contextTokens === 'number'
      ? `${contextTokens.toLocaleString('es-ES')} tokens`
      : '',
    mode === 'gaming_gpu'
      ? status?.gaming_gpu_server_running
        ? status.gaming_gpu_server_owned === false
          ? 'Puerto ocupado por otro servicio'
          : 'Servidor privado activo'
        : 'Servidor privado detenido'
      : '',
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <View style={[styles.modeOption, active && styles.modeOptionActive]}>
      <View style={styles.modeOptionHeader}>
        <View style={styles.modeOptionText}>
          <Text style={styles.modeOptionTitle}>{modelModeTitle(mode)}</Text>
          <Text style={styles.modeOptionDescription}>
            {blocked
              ? gameProbeFailed
                ? 'No se ha podido comprobar si hay un juego; Arfoxia espera por seguridad'
                : 'Un juego está usando esta gráfica; Arfoxia no la tocará'
              : modelModeDescription(mode)}
          </Text>
        </View>
        <StatusPill
          label={
            active
              ? 'Activo'
              : gameProbeFailed
                ? 'Comprobando'
                : blocked
                  ? 'En juego'
                  : available
                    ? 'Listo'
                    : 'Falta'
          }
          tone={
            active
              ? 'success'
              : blocked
                ? 'warning'
                : available
                ? 'neutral'
                : 'danger'
          }
        />
      </View>
      <Text style={styles.modeOptionModel} numberOfLines={2}>
        {modelName || 'Modelo pendiente de identificar'}
      </Text>
      {modeFacts ? (
        <Text style={styles.modeOptionFacts}>{modeFacts}</Text>
      ) : null}
      <Button
        label={modelModeActionLabel(status, mode)}
        icon={mode === 'gaming_gpu' ? '▣' : mode === 'power' ? '✦' : '◇'}
        variant={active ? 'ghost' : mode === 'power' ? 'primary' : 'secondary'}
        compact
        busy={busy}
        disabled={disabled || active}
        onPress={onPress}
      />
    </View>
  );
}

function GpuCard({
  gpu,
  gamingModeActive,
  buttonBusy,
  buttonDisabled,
  onUseGamingGpu,
}: {
  gpu: DisplayGpuStatus;
  gamingModeActive: boolean;
  buttonBusy: boolean;
  buttonDisabled: boolean;
  onUseGamingGpu: () => void;
}) {
  const vramPercent =
    gpu.total_vram_gb > 0
      ? Math.max(
          0,
          Math.min(100, (gpu.used_vram_gb / gpu.total_vram_gb) * 100),
        )
      : 0;
  const gaming = isGamingGpu(gpu.role);

  return (
    <View style={[styles.gpuCard, gpu.active && styles.gpuCardActive]}>
      <View style={styles.gpuHeader}>
        <View style={styles.gpuHeading}>
          <Text style={styles.gpuRole}>
            {gpuRoleLabel(gpu.role, gpu.index)}
          </Text>
          <Text style={styles.gpuName}>{gpu.name}</Text>
          {shortGpuUuid(gpu.uuid) ? (
            <Text style={styles.gpuUuid}>{shortGpuUuid(gpu.uuid)}</Text>
          ) : null}
          {gpu.driver_version || gpu.pci_bus_id ? (
            <Text style={styles.gpuTechnical}>
              {[
                gpu.driver_version ? `Driver ${gpu.driver_version}` : '',
                gpu.pci_bus_id ? `PCI ${gpu.pci_bus_id}` : '',
              ]
                .filter(Boolean)
                .join(' · ')}
            </Text>
          ) : null}
        </View>
        <StatusPill
          label={gpu.active ? 'Arfoxia activa' : gpu.status}
          tone={gpu.active ? 'success' : 'neutral'}
        />
      </View>

      <View style={styles.gpuModelBox}>
        <Text style={styles.gpuModelLabel}>Modelo asignado</Text>
        <Text style={styles.gpuModelName} numberOfLines={2}>
          {gpu.model || 'Ningún modelo de Arfoxia'}
        </Text>
      </View>

      <View style={styles.gpuMetrics}>
        <Metric
          label="Uso"
          value={`${Math.round(gpu.utilization_percent)}%`}
        />
        <Metric
          label="Temperatura"
          value={gpu.temperature_c ? `${Math.round(gpu.temperature_c)} °C` : '—'}
        />
        <Metric
          label="VRAM usada"
          value={`${gpu.used_vram_gb.toFixed(1)} GB`}
        />
        <Metric
          label="VRAM libre"
          value={`${gpu.free_vram_gb.toFixed(1)} GB`}
        />
        {typeof gpu.power_draw_w === 'number' ? (
          <Metric
            label="Potencia"
            value={
              typeof gpu.power_limit_w === 'number'
                ? `${gpu.power_draw_w.toFixed(0)} / ${gpu.power_limit_w.toFixed(0)} W`
                : `${gpu.power_draw_w.toFixed(0)} W`
            }
            wide
          />
        ) : null}
      </View>

      <View style={styles.vramHeader}>
        <Text style={styles.vramLabel}>VRAM</Text>
        <Text style={styles.vramValue}>
          {gpu.used_vram_gb.toFixed(1)} / {gpu.total_vram_gb.toFixed(1)} GB
        </Text>
      </View>
      <View style={styles.vramTrack}>
        <View
          style={[
            styles.vramFill,
            { width: `${vramPercent}%` },
            vramPercent > 90 && styles.vramFillHot,
          ]}
        />
      </View>

      {gaming ? (
        <Button
          label={
            gamingModeActive
              ? 'Modelo ligero activo aquí'
              : 'Cargar modelo ligero en esta GPU'
          }
          icon="▣"
          variant={gamingModeActive ? 'ghost' : 'secondary'}
          busy={buttonBusy}
          disabled={buttonDisabled || gamingModeActive}
          onPress={onUseGamingGpu}
        />
      ) : null}
    </View>
  );
}

function SystemDetail({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <View style={styles.systemDetail}>
      <Text style={styles.systemDetailLabel}>{label}</Text>
      <Text style={styles.systemDetailValue}>{value}</Text>
      {detail ? <Text style={styles.systemDetailMeta}>{detail}</Text> : null}
    </View>
  );
}

function Metric({
  label,
  value,
  wide = false,
}: {
  label: string;
  value: string;
  wide?: boolean;
}) {
  return (
    <View style={[styles.metric, wide && styles.metricWide]}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue} numberOfLines={2} adjustsFontSizeToFit>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    paddingTop: 3,
  },
  headerText: {
    flex: 1,
    gap: 2,
  },
  modelCard: {
    gap: 15,
    backgroundColor: '#0D3048',
  },
  modeBadge: {
    paddingHorizontal: 9,
    paddingVertical: 6,
    borderRadius: 9,
    backgroundColor: 'rgba(131, 232, 255, 0.12)',
    borderWidth: 1,
    borderColor: 'rgba(131, 232, 255, 0.42)',
  },
  modeBadgeText: {
    color: colors.ice,
    fontSize: 10,
    fontWeight: '900',
    letterSpacing: 0.7,
  },
  currentModel: {
    gap: 4,
    padding: 13,
    borderRadius: 14,
    backgroundColor: '#081E2E',
    borderWidth: 1,
    borderColor: 'rgba(131, 232, 255, 0.24)',
  },
  currentModelLabel: {
    color: colors.muted,
    fontSize: 10,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  modelName: {
    color: colors.ice,
    fontSize: 15,
    lineHeight: 20,
    fontWeight: '800',
  },
  currentModelMeta: {
    color: colors.muted,
    fontSize: 11,
    lineHeight: 16,
  },
  gameText: {
    color: colors.warning,
    fontSize: 12,
    lineHeight: 18,
  },
  subsectionLabel: {
    color: colors.ice,
    fontSize: 11,
    fontWeight: '900',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  modeList: {
    gap: 10,
  },
  modeOption: {
    gap: 10,
    padding: 13,
    borderRadius: 16,
    backgroundColor: '#081E2E',
    borderWidth: 1,
    borderColor: 'rgba(35, 85, 114, 0.82)',
  },
  modeOptionActive: {
    borderColor: colors.success,
    backgroundColor: 'rgba(31, 90, 79, 0.35)',
  },
  modeOptionHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  modeOptionText: {
    flex: 1,
    gap: 2,
  },
  modeOptionTitle: {
    color: colors.text,
    fontSize: 15,
    lineHeight: 19,
    fontWeight: '800',
  },
  modeOptionDescription: {
    color: colors.muted,
    fontSize: 11,
    lineHeight: 16,
  },
  modeOptionModel: {
    color: colors.ice,
    fontSize: 12,
    lineHeight: 17,
    fontWeight: '700',
  },
  modeOptionFacts: {
    color: colors.muted,
    fontSize: 10,
    lineHeight: 15,
    fontWeight: '700',
  },
  gpuManagerCard: {
    gap: 15,
  },
  gpuList: {
    gap: 12,
  },
  gpuCard: {
    gap: 13,
    padding: 14,
    borderRadius: 18,
    backgroundColor: '#081E2E',
    borderWidth: 1,
    borderColor: 'rgba(35, 85, 114, 0.82)',
  },
  gpuCardActive: {
    borderColor: 'rgba(123, 224, 179, 0.82)',
  },
  gpuHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  gpuHeading: {
    flex: 1,
    gap: 2,
  },
  gpuRole: {
    color: colors.ice,
    fontSize: 11,
    fontWeight: '900',
    textTransform: 'uppercase',
    letterSpacing: 0.7,
  },
  gpuName: {
    color: colors.text,
    fontSize: 16,
    lineHeight: 21,
    fontWeight: '800',
  },
  gpuUuid: {
    color: colors.muted,
    fontSize: 10,
    lineHeight: 14,
    fontVariant: ['tabular-nums'],
  },
  gpuTechnical: {
    color: colors.muted,
    fontSize: 9,
    lineHeight: 13,
  },
  gpuModelBox: {
    gap: 3,
    padding: 11,
    borderRadius: 12,
    backgroundColor: 'rgba(18, 56, 82, 0.62)',
  },
  gpuModelLabel: {
    color: colors.muted,
    fontSize: 9,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  gpuModelName: {
    color: colors.text,
    fontSize: 13,
    lineHeight: 18,
    fontWeight: '800',
  },
  gpuMetrics: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  vramHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  vramLabel: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: '800',
  },
  vramValue: {
    color: colors.text,
    fontSize: 11,
    fontWeight: '800',
    fontVariant: ['tabular-nums'],
  },
  vramTrack: {
    height: 9,
    marginTop: -7,
    overflow: 'hidden',
    borderRadius: 99,
    backgroundColor: '#061522',
  },
  vramFill: {
    height: '100%',
    borderRadius: 99,
    backgroundColor: colors.iceStrong,
  },
  vramFillHot: {
    backgroundColor: colors.warning,
  },
  pcCard: {
    gap: 16,
  },
  systemDetails: {
    gap: 9,
  },
  systemDetail: {
    gap: 3,
    padding: 12,
    borderRadius: 14,
    backgroundColor: '#081E2E',
    borderWidth: 1,
    borderColor: 'rgba(35, 85, 114, 0.75)',
  },
  systemDetailLabel: {
    color: colors.muted,
    fontSize: 10,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  systemDetailValue: {
    color: colors.text,
    fontSize: 14,
    lineHeight: 19,
    fontWeight: '800',
  },
  systemDetailMeta: {
    color: colors.ice,
    fontSize: 11,
    lineHeight: 16,
  },
  metricsWrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 9,
  },
  metric: {
    width: '31%',
    minWidth: 90,
    flexGrow: 1,
    padding: 11,
    borderRadius: 14,
    backgroundColor: '#081E2E',
    borderWidth: 1,
    borderColor: 'rgba(35, 85, 114, 0.75)',
    gap: 5,
  },
  metricWide: {
    width: '47%',
  },
  metricLabel: {
    color: colors.muted,
    fontSize: 9,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 0.45,
  },
  metricValue: {
    color: colors.text,
    fontSize: 17,
    lineHeight: 21,
    fontWeight: '800',
    fontVariant: ['tabular-nums'],
  },
  emptyDetail: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 19,
    textAlign: 'center',
    paddingVertical: 8,
  },
  appsCard: {
    gap: 15,
  },
  appGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 9,
  },
  appButton: {
    width: '48%',
    flexGrow: 1,
  },
});
