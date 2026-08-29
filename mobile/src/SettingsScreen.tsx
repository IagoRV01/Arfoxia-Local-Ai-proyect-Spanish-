import { useCallback, useState } from 'react';
import { Alert, StyleSheet, Text, View } from 'react-native';

import { ApiError, ArfoxiaApi } from './api';
import type { Health } from './types';
import {
  Button,
  Card,
  ErrorBanner,
  Screen,
  SectionTitle,
  StatusPill,
  colors,
  sharedStyles,
} from './ui';

type Props = {
  api: ArfoxiaApi;
  health: Health | null;
  onUnpair: () => Promise<void>;
  onUnauthorized: () => void;
};

export function SettingsScreen({
  api,
  health,
  onUnpair,
  onUnauthorized,
}: Props) {
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const handleError = useCallback(
    (reason: unknown) => {
      if (reason instanceof ApiError && reason.status === 401) {
        onUnauthorized();
        return;
      }
      setError(
        reason instanceof Error ? reason.message : 'No se ha podido completar la acción.',
      );
    },
    [onUnauthorized],
  );

  const testConnection = useCallback(async () => {
    setBusy('test');
    setError('');
    try {
      const result = await api.health();
      await api.state();
      Alert.alert(
        'Conexión correcta',
        `${result.name} ${result.version} responde a través de Tailscale.`,
      );
    } catch (reason) {
      handleError(reason);
    } finally {
      setBusy('');
    }
  }, [api, handleError]);

  const showDesktopChat = useCallback(async () => {
    setBusy('desktop');
    setError('');
    try {
      await api.showDesktopChat();
      Alert.alert('Listo', 'He abierto el chat de Arfoxia en el PC.');
    } catch (reason) {
      handleError(reason);
    } finally {
      setBusy('');
    }
  }, [api, handleError]);

  const confirmUnpair = useCallback(() => {
    Alert.alert(
      'Desemparejar este iPhone',
      'Se borrará la clave de Arfoxia del llavero del iPhone. Para volver a usarla tendrás que escanear el QR.',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Desemparejar',
          style: 'destructive',
          onPress: () => void onUnpair(),
        },
      ],
    );
  }, [onUnpair]);

  return (
    <Screen>
      <View style={styles.header}>
        <View style={styles.headerText}>
          <Text style={sharedStyles.label}>Privacidad y conexión</Text>
          <Text style={sharedStyles.title}>Ajustes</Text>
        </View>
        <StatusPill label="Emparejado" tone="success" />
      </View>

      {error ? <ErrorBanner message={error} /> : null}

      <Card style={styles.connectionCard}>
        <SectionTitle
          title="Arfoxia"
          subtitle="Conexión privada mediante Tailscale"
        />
        <View style={styles.infoRows}>
          <InfoRow label="Servidor" value="pciagorv.tail122075.ts.net" />
          <InfoRow label="Versión" value={health?.version || '0.11.4'} />
          <InfoRow
            label="Búsqueda web"
            value={health?.online_search ? 'Disponible' : 'No disponible'}
          />
          <InfoRow
            label="Adjuntos"
            value={health?.attachments ? 'Disponible' : 'No disponible'}
          />
        </View>
        <Button
          label="Comprobar conexión"
          variant="secondary"
          busy={busy === 'test'}
          disabled={Boolean(busy)}
          onPress={() => void testConnection()}
        />
      </Card>

      <Card style={styles.securityCard}>
        <Text style={styles.securityIcon}>◇</Text>
        <View style={styles.securityContent}>
          <Text style={styles.securityTitle}>Clave protegida</Text>
          <Text style={sharedStyles.muted}>
            La clave de emparejamiento está en el llavero cifrado de iOS. La app
            nunca la muestra ni la guarda en el historial del chat.
          </Text>
        </View>
      </Card>

      <Card style={styles.expoCard}>
        <SectionTitle title="Modo Expo Go" subtitle="Sin cuenta de Apple de pago" />
        <Text style={sharedStyles.body}>
          Esta versión funciona dentro de Expo Go. Arfoxia inicia y supervisa el
          servidor de desarrollo automáticamente cuando Tailscale está listo.
          Mantén Arfoxia y Tailscale activos para usar sus funciones.
        </Text>
      </Card>

      <Button
        label="Abrir el chat en el PC"
        icon="▣"
        variant="ghost"
        busy={busy === 'desktop'}
        disabled={Boolean(busy)}
        onPress={() => void showDesktopChat()}
      />
      <Button
        label="Desemparejar este iPhone"
        variant="danger"
        disabled={Boolean(busy)}
        onPress={confirmUnpair}
      />
    </Screen>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.infoRow}>
      <Text style={styles.infoLabel}>{label}</Text>
      <Text style={styles.infoValue} numberOfLines={1}>
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
    gap: 2,
  },
  connectionCard: {
    gap: 16,
  },
  infoRows: {
    gap: 11,
  },
  infoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 14,
    paddingBottom: 10,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(35, 85, 114, 0.50)',
  },
  infoLabel: {
    color: colors.muted,
    fontSize: 13,
  },
  infoValue: {
    flexShrink: 1,
    color: colors.text,
    fontSize: 13,
    fontWeight: '700',
    textAlign: 'right',
  },
  securityCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 13,
  },
  securityIcon: {
    color: colors.success,
    fontSize: 24,
    lineHeight: 28,
  },
  securityContent: {
    flex: 1,
    gap: 5,
  },
  securityTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '800',
  },
  expoCard: {
    gap: 13,
    backgroundColor: '#102C42',
  },
});
