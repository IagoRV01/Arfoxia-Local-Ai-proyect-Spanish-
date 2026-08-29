import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  AppState,
  KeyboardAvoidingView,
  Linking,
  Modal,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import * as Clipboard from 'expo-clipboard';

import { ApiError, ArfoxiaApi } from './api';
import {
  MOONLIGHT_APP_STORE_URL,
  moonlightShortcutUrl,
  normalizeMoonlightPin,
  usableMoonlightHost,
} from './moonlight';
import type { GameStreamingStatus } from './types';
import {
  Button,
  ErrorBanner,
  SectionTitle,
  StatusPill,
  colors,
  sharedStyles,
} from './ui';

type Props = {
  api: ArfoxiaApi;
  onUnauthorized: () => void;
};

export function GamingLauncher({ api, onUnauthorized }: Props) {
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pairing, setPairing] = useState(false);
  const [status, setStatus] = useState<GameStreamingStatus | null>(null);
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  const handleError = useCallback(
    (reason: unknown) => {
      if (reason instanceof ApiError && reason.status === 401) {
        setVisible(false);
        onUnauthorized();
        return;
      }
      setError(
        reason instanceof Error
          ? reason.message
          : 'No se ha podido preparar el juego remoto.',
      );
    },
    [onUnauthorized],
  );

  const openShortcut = useCallback(async () => {
    try {
      await Linking.openURL(moonlightShortcutUrl());
    } catch {
      setVisible(true);
      Alert.alert(
        'Falta el Atajo',
        'Crea en Atajos uno llamado «Abrir Moonlight» con la acción «Abrir app → Moonlight».',
      );
    }
  }, []);

  const prepare = useCallback(async () => {
    setBusy(true);
    setError('');
    setCopied(false);
    try {
      const nextStatus = await api.prepareGameStreaming();
      setStatus(nextStatus);
      if (nextStatus.paired) {
        setVisible(false);
        await openShortcut();
      } else {
        setVisible(true);
      }
    } catch (reason) {
      setVisible(true);
      handleError(reason);
      try {
        setStatus(await api.gameStreamingStatus());
      } catch {
        // The original actionable error is more useful than a second failure.
      }
    } finally {
      setBusy(false);
    }
  }, [api, handleError, openShortcut]);

  const launch = useCallback(() => {
    if (status?.paired) {
      void openShortcut();
      return;
    }
    void prepare();
  }, [openShortcut, prepare, status]);

  const refresh = useCallback(async () => {
    setBusy(true);
    setError('');
    try {
      setStatus(await api.gameStreamingStatus());
    } catch (reason) {
      handleError(reason);
    } finally {
      setBusy(false);
    }
  }, [api, handleError]);

  const pair = useCallback(async () => {
    if (pin.length !== 4) {
      return;
    }
    setPairing(true);
    setError('');
    try {
      const result = await api.pairGameStreaming(pin);
      setPin('');
      if (result.requires_authorization) {
        Alert.alert(
          'Autoriza este iPhone en el PC',
          'Arfoxia mostrará una solicitud privada en Windows. Apruébala allí mientras Moonlight sigue enseñando el PIN y después vuelve a comprobar el estado.',
        );
        return;
      }
      if (!result.success) {
        throw new Error(result.message);
      }
      const nextStatus = result.data as unknown as GameStreamingStatus | null;
      if (nextStatus && typeof nextStatus.ready === 'boolean') {
        setStatus(nextStatus);
      }
      Alert.alert('PIN enviado a Sunshine', result.message || 'Vuelve a Moonlight.');
    } catch (reason) {
      handleError(reason);
    } finally {
      setPairing(false);
    }
  }, [api, handleError, pin]);

  const host = useMemo(
    () => usableMoonlightHost(status?.host, status?.tailscale_ip),
    [status],
  );

  const copyHost = useCallback(async () => {
    if (!host) {
      return;
    }
    await Clipboard.setStringAsync(host);
    setCopied(true);
  }, [host]);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => {
      if (visible && nextState === 'active' && !busy && !pairing) {
        void refresh();
      }
    });
    return () => subscription.remove();
  }, [busy, pairing, refresh, visible]);

  const openStore = useCallback(async () => {
    const target = status?.moonlight_app_store_url || MOONLIGHT_APP_STORE_URL;
    try {
      await Linking.openURL(target);
    } catch {
      setError('iOS no ha podido abrir la ficha oficial de Moonlight.');
    }
  }, [status]);

  return (
    <>
      <View style={styles.launcherBar}>
        <Button
          label="Jugar en mi PC"
          icon="🎮"
          busy={busy && !visible}
          onPress={launch}
          style={styles.launcherButton}
        />
      </View>

      <Modal
        visible={visible}
        transparent
        animationType="slide"
        onRequestClose={() => setVisible(false)}
      >
        <KeyboardAvoidingView
          style={styles.backdrop}
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        >
          <View style={styles.sheet}>
            <View style={styles.sheetHeader}>
              <View style={styles.sheetTitle}>
                <Text style={sharedStyles.label}>Sunshine + Tailscale</Text>
                <Text style={styles.title}>Jugar en mi PC</Text>
              </View>
              <Button
                label="Cerrar"
                variant="ghost"
                compact
                onPress={() => setVisible(false)}
              />
            </View>

            <ScrollView
              contentContainerStyle={styles.content}
              keyboardShouldPersistTaps="handled"
              showsVerticalScrollIndicator={false}
            >
              {error ? <ErrorBanner message={error} /> : null}

              <View style={styles.statusCard}>
                <SectionTitle
                  title="PC de juego"
                  subtitle={status?.message || 'Comprobando Sunshine…'}
                  trailing={
                    <StatusPill
                      label={
                        status?.ready
                          ? 'Listo'
                          : busy
                            ? 'Preparando'
                            : 'Revisar'
                      }
                      tone={status?.ready ? 'success' : busy ? 'warning' : 'danger'}
                    />
                  }
                />
                <View style={styles.facts}>
                  <Fact
                    label="Sunshine"
                    value={status?.running ? 'Servicio activo' : 'No disponible'}
                  />
                  <Fact
                    label="Tailscale"
                    value={status?.tailscale_ready ? 'Conectado' : 'Sin conexión'}
                  />
                  <Fact
                    label="Captura"
                    value={status?.capture_gpu || 'RTX 5060 Ti de juego'}
                    wide
                  />
                  <Fact
                    label="Mando virtual"
                    value={status?.gamepad_ready ? 'Preparado' : 'Pendiente'}
                  />
                  <Fact
                    label="Moonlight"
                    value={status?.paired ? 'Emparejado' : 'Sin emparejar'}
                  />
                </View>
                <Button
                  label="Volver a comprobar"
                  variant="ghost"
                  compact
                  busy={busy}
                  disabled={pairing}
                  onPress={() => void refresh()}
                />
              </View>

              <View style={styles.stepCard}>
                <Text style={styles.stepNumber}>1</Text>
                <View style={styles.stepBody}>
                  <Text style={styles.stepTitle}>Añade este PC en Moonlight</Text>
                  <Text style={styles.stepText}>
                    En Moonlight pulsa «+» y pega este host privado. Para el primer
                    emparejamiento, mantén el iPhone en la Wi‑Fi de casa.
                  </Text>
                  <View style={styles.hostBox}>
                    <Text selectable style={styles.host} numberOfLines={2}>
                      {host || 'Esperando a Tailscale…'}
                    </Text>
                    <Button
                      label={copied ? 'Copiado' : 'Copiar'}
                      variant="secondary"
                      compact
                      disabled={!host}
                      onPress={() => void copyHost()}
                    />
                  </View>
                </View>
              </View>

              <View style={styles.stepCard}>
                <Text style={styles.stepNumber}>2</Text>
                <View style={styles.stepBody}>
                  <Text style={styles.stepTitle}>Confirma el PIN</Text>
                  {status?.pin_submission_available ? (
                    <>
                      <Text style={styles.stepText}>
                        Moonlight mostrará cuatro cifras. Escríbelas aquí mientras la
                        solicitud siga abierta.
                      </Text>
                      <View style={styles.pinRow}>
                        <TextInput
                          value={pin}
                          onChangeText={(value) => setPin(normalizeMoonlightPin(value))}
                          keyboardType="number-pad"
                          maxLength={4}
                          placeholder="0000"
                          placeholderTextColor={colors.muted}
                          style={styles.pinInput}
                          textContentType="oneTimeCode"
                          accessibilityLabel="PIN de Moonlight"
                        />
                        <Button
                          label="Emparejar"
                          busy={pairing}
                          disabled={pin.length !== 4 || !status?.sunshine_ready || busy}
                          onPress={() => void pair()}
                        />
                      </View>
                    </>
                  ) : (
                    <Text style={styles.stepText}>
                      Si Sunshine ya tenía una cuenta propia, introduce el PIN una vez
                      desde https://localhost:47990 en el PC.
                    </Text>
                  )}
                </View>
              </View>

              <View style={styles.stepCard}>
                <Text style={styles.stepNumber}>3</Text>
                <View style={styles.stepBody}>
                  <Text style={styles.stepTitle}>Abre Moonlight y juega</Text>
                  <Text style={styles.stepText}>
                    iOS no permite a Expo abrir Moonlight por su cuenta. Para un toque,
                    crea un Atajo llamado «Abrir Moonlight»; si no, usa su ficha oficial
                    y pulsa «Abrir».
                  </Text>
                  <View style={styles.actions}>
                    <Button
                      label="Abrir con Atajo"
                      icon="▶"
                      onPress={() => void openShortcut()}
                    />
                    <Button
                      label="Instalar / abrir Moonlight"
                      variant="secondary"
                      onPress={() => void openStore()}
                    />
                  </View>
                </View>
              </View>

              <View style={styles.note}>
                <Text style={styles.noteTitle}>Encendido remoto</Text>
                <Text style={styles.noteText}>
                  {status?.wake_reason ||
                    'Para encender el PC desde fuera hará falta más adelante un router, NAS o Raspberry Pi siempre activo en casa.'}
                </Text>
              </View>
            </ScrollView>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </>
  );
}

function Fact({
  label,
  value,
  wide = false,
}: {
  label: string;
  value: string;
  wide?: boolean;
}) {
  return (
    <View style={[styles.fact, wide && styles.factWide]}>
      <Text style={styles.factLabel}>{label}</Text>
      <Text style={styles.factValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  launcherBar: {
    paddingHorizontal: 10,
    paddingVertical: 7,
    backgroundColor: '#071A28',
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  launcherButton: {
    minHeight: 46,
  },
  backdrop: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(1, 7, 12, 0.78)',
  },
  sheet: {
    height: '92%',
    overflow: 'hidden',
    borderTopLeftRadius: 26,
    borderTopRightRadius: 26,
    borderWidth: 1,
    borderBottomWidth: 0,
    borderColor: colors.border,
    backgroundColor: colors.background,
  },
  sheetHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 18,
    paddingVertical: 15,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.backgroundRaised,
  },
  sheetTitle: {
    flex: 1,
    gap: 2,
  },
  title: {
    color: colors.text,
    fontSize: 24,
    lineHeight: 29,
    fontWeight: '900',
  },
  content: {
    padding: 16,
    paddingBottom: 38,
    gap: 13,
  },
  statusCard: {
    gap: 14,
    padding: 16,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  facts: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  fact: {
    width: '47%',
    flexGrow: 1,
    gap: 3,
    padding: 10,
    borderRadius: 12,
    backgroundColor: '#081E2E',
  },
  factWide: {
    width: '100%',
  },
  factLabel: {
    color: colors.muted,
    fontSize: 9,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  factValue: {
    color: colors.text,
    fontSize: 12,
    lineHeight: 17,
    fontWeight: '800',
  },
  stepCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
    padding: 15,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  stepNumber: {
    width: 31,
    height: 31,
    borderRadius: 16,
    overflow: 'hidden',
    color: colors.background,
    backgroundColor: colors.ice,
    textAlign: 'center',
    lineHeight: 31,
    fontSize: 15,
    fontWeight: '900',
  },
  stepBody: {
    flex: 1,
    gap: 10,
  },
  stepTitle: {
    color: colors.text,
    fontSize: 16,
    lineHeight: 21,
    fontWeight: '900',
  },
  stepText: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 19,
  },
  hostBox: {
    gap: 9,
    padding: 11,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: 'rgba(131, 232, 255, 0.34)',
    backgroundColor: '#061522',
  },
  host: {
    color: colors.ice,
    fontSize: 13,
    lineHeight: 18,
    fontWeight: '800',
  },
  pinRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'stretch',
    gap: 9,
  },
  pinInput: {
    flex: 1,
    minWidth: 150,
    minHeight: 50,
    borderRadius: 15,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: '#061522',
    color: colors.text,
    paddingHorizontal: 15,
    textAlign: 'center',
    fontSize: 22,
    fontWeight: '900',
    letterSpacing: 7,
    fontVariant: ['tabular-nums'],
  },
  actions: {
    gap: 9,
  },
  note: {
    gap: 5,
    padding: 13,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: 'rgba(255, 210, 131, 0.40)',
    backgroundColor: 'rgba(255, 210, 131, 0.08)',
  },
  noteTitle: {
    color: colors.warning,
    fontSize: 12,
    fontWeight: '900',
  },
  noteText: {
    color: colors.muted,
    fontSize: 11,
    lineHeight: 17,
  },
});
