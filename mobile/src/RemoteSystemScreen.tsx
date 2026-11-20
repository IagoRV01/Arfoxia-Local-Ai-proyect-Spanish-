import { useEffect, useRef, useState } from 'react';
import { AppState, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { ApiError, type ArfoxiaApi } from './api';
import type { RemotePcStatus } from './types';
import { Button, Card, ErrorBanner, Screen, SectionTitle, StatusPill, colors, sharedStyles } from './ui';

type Props = { api: ArfoxiaApi; onUnauthorized: () => void };

export function metric(value: number | null | undefined, unit = '', decimals = 0): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${value.toFixed(decimals)}${unit}` : 'No disponible';
}

export function RemoteSystemScreen({ api, onUnauthorized }: Props) {
  const [snapshot, setSnapshot] = useState<RemotePcStatus | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const refresh = useRef<() => Promise<void>>(async () => {});

  useEffect(() => {
    let mounted = true;
    let pending = false;
    const run = async () => {
      if (pending || AppState.currentState !== 'active') return;
      pending = true;
      if (mounted) setRefreshing(true);
      try {
        const response = await api.bc250Status();
        if (mounted) {
          setSnapshot(response);
          setError('');
        }
      } catch (reason) {
        if (mounted) {
          setSnapshot(null);
          setError(reason instanceof Error ? reason.message : 'No se pudo consultar la BC-250.');
          if (reason instanceof ApiError && reason.status === 401) onUnauthorized();
        }
      } finally {
        pending = false;
        if (mounted) setRefreshing(false);
      }
    };
    refresh.current = run;
    void run();
    const timer = setInterval(() => void run(), 20_000);
    const subscription = AppState.addEventListener('change', (state) => {
      // Never present an old pre-background measurement as a live reading.
      if (mounted) setSnapshot(null);
      if (state === 'active') void run();
    });
    return () => {
      mounted = false;
      clearInterval(timer);
      subscription.remove();
      refresh.current = async () => {};
    };
  }, [api, onUnauthorized]);

  const pc = snapshot?.online ? snapshot.status : null;
  return (
    <Screen refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => void refresh.current()} tintColor={colors.ice} />}>
      <SectionTitle title="BC-250" subtitle="Bazzite · Monitorización privada por SSH"
        trailing={<StatusPill label={snapshot?.online ? 'Conectada' : refreshing ? 'Consultando' : 'Sin conexión'} tone={snapshot?.online ? 'success' : 'neutral'} />} />
      <ErrorBanner message={error || snapshot?.error || ''} />
      <Card>
        <Text style={styles.title}>{pc?.hostname || 'BC-250 · Bazzite'}</Text>
        <Text style={sharedStyles.body}>{pc?.os_name || 'Estadísticas del equipo remoto, separadas del PC Windows.'}</Text>
        <Text style={sharedStyles.body}>Se actualiza cada 20 segundos mientras miras esta pantalla. No enciende la BC-250 ni carga modelos de IA.</Text>
        <Button label="Actualizar BC-250" busy={refreshing} onPress={() => void refresh.current()} />
        {snapshot?.sampled_at && snapshot.online ? <Text style={styles.note}>Lectura: {new Date(snapshot.sampled_at).toLocaleTimeString()}</Text> : null}
      </Card>
      {pc ? <>
        <Card>
          <SectionTitle title="CPU y memoria" subtitle={pc.cpu_name} />
          <Reading label="Uso de CPU" value={metric(pc.cpu_percent, ' %')} />
          <Reading label="Hilos de CPU" value={metric(pc.cpu_logical_cores)} />
          <Reading label="Temperatura CPU" value={metric(pc.cpu_temperature_c, ' °C')} />
          <Reading label="Uso de RAM" value={metric(pc.memory_percent, ' %')} />
          <Reading label="RAM usada / total" value={`${metric(pc.memory_used_gb, '', 1)} / ${metric(pc.memory_total_gb, ' GiB', 1)}`} />
          <Reading label="RAM disponible" value={metric(pc.memory_available_gb, ' GiB', 1)} />
        </Card>
        <Card>
          <SectionTitle title="Gráficos AMD" subtitle="Memoria según el controlador; no se suma a la RAM como si fuera memoria independiente." />
          {pc.gpus.length ? pc.gpus.map((gpu, index) => <View key={`${gpu.name}-${index}`} style={styles.gpu}>
            <Text style={styles.title}>{gpu.name}</Text>
            <Reading label="Uso de GPU" value={metric(gpu.utilization_percent, ' %')} />
            <Reading label="Temperatura GPU" value={metric(gpu.temperature_c, ' °C')} />
            <Reading label="Memoria gráfica usada / total" value={`${metric(gpu.memory_used_mb, '', 0)} / ${metric(gpu.memory_total_mb, ' MiB', 0)}`} />
            <Reading label="Potencia SoC (puede incluir CPU)" value={metric(gpu.soc_power_w, ' W', 1)} />
          </View>) : <Text style={sharedStyles.body}>El controlador no expone sensores AMD accesibles.</Text>}
        </Card>
        <Card>
          <SectionTitle title="Sistema y disco" subtitle={`Disco de datos (${pc.disk_path || '/'})`} />
          <Reading label="Disco usado" value={metric(pc.disk_percent, ' %')} />
          <Reading label="Espacio usado / total" value={`${metric(pc.disk_used_gb, '', 1)} / ${metric(pc.disk_total_gb, ' GiB', 1)}`} />
          <Reading label="Espacio libre" value={metric(pc.disk_free_gb, ' GiB', 1)} />
          <Reading label="Tiempo encendida" value={typeof pc.uptime_seconds === 'number' ? `${Math.floor(pc.uptime_seconds / 3600)} h ${Math.floor(pc.uptime_seconds % 3600 / 60)} min` : 'No disponible'} />
        </Card>
      </> : null}
    </Screen>
  );
}

function Reading({ label, value }: { label: string; value: string }) {
  return <View style={styles.reading}><Text style={styles.label}>{label}</Text><Text style={styles.value}>{value}</Text></View>;
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 20, fontWeight: '800' },
  reading: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', gap: 8, paddingVertical: 8 },
  label: { color: colors.muted, fontSize: 14, flexShrink: 1 },
  value: { color: colors.text, fontSize: 16, fontWeight: '700', flexShrink: 1 },
  gpu: { gap: 4, paddingVertical: 8 },
  note: { color: colors.muted, fontSize: 12 },
});
