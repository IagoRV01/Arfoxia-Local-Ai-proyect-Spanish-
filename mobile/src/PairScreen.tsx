import { useCallback, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { Image } from 'expo-image';

import { ArfoxiaApi } from './api';
import { saveCredentials } from './credentials';
import { parsePairingCode } from './pairing';
import type { Credentials, Health } from './types';
import {
  Button,
  Card,
  ErrorBanner,
  Screen,
  colors,
  sharedStyles,
} from './ui';

type Props = {
  onPaired: (credentials: Credentials, health: Health) => void;
};

export function PairScreen({ onPaired }: Props) {
  const [permission, requestPermission] = useCameraPermissions();
  const [scannerOpen, setScannerOpen] = useState(false);
  const [scannerLocked, setScannerLocked] = useState(false);
  const [manualCode, setManualCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const pair = useCallback(
    async (raw: string) => {
      if (busy) {
        return;
      }
      setBusy(true);
      setError('');
      try {
        const credentials = parsePairingCode(raw);
        const api = new ArfoxiaApi(credentials);
        const health = await api.health();
        if (!health.ok) {
          throw new Error('El servicio de Arfoxia no está preparado.');
        }
        await api.state();
        await saveCredentials(credentials);
        setManualCode('');
        setScannerOpen(false);
        onPaired(credentials, health);
      } catch (reason) {
        setScannerLocked(false);
        setError(
          reason instanceof Error
            ? reason.message
            : 'No se ha podido completar el emparejamiento.',
        );
      } finally {
        setBusy(false);
      }
    },
    [busy, onPaired],
  );

  const openScanner = useCallback(async () => {
    setError('');
    let granted = permission?.granted ?? false;
    if (!granted) {
      const requested = await requestPermission();
      granted = requested.granted;
    }
    if (!granted) {
      setError(
        'Necesito permiso para la cámara. También puedes pegar el enlace de emparejamiento debajo.',
      );
      return;
    }
    setScannerLocked(false);
    setScannerOpen(true);
  }, [permission?.granted, requestPermission]);

  if (scannerOpen) {
    return (
      <View style={styles.scannerPage}>
        <CameraView
          style={StyleSheet.absoluteFill}
          facing="back"
          barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
          onBarcodeScanned={
            scannerLocked
              ? undefined
              : ({ data }) => {
                  setScannerLocked(true);
                  void pair(data);
                }
          }
        />
        <View style={styles.scannerShade}>
          <View style={styles.scannerHeader}>
            <Text style={styles.scannerTitle}>Escanea el QR de Arfoxia</Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Cerrar escáner"
              onPress={() => setScannerOpen(false)}
              style={styles.closeButton}
            >
              <Text style={styles.closeText}>×</Text>
            </Pressable>
          </View>
          <View style={styles.finder}>
            <View style={[styles.corner, styles.cornerTopLeft]} />
            <View style={[styles.corner, styles.cornerTopRight]} />
            <View style={[styles.corner, styles.cornerBottomLeft]} />
            <View style={[styles.corner, styles.cornerBottomRight]} />
          </View>
          <View style={styles.scannerFooter}>
            <Text style={styles.scannerHelp}>
              En el PC, abre Arfoxia y pulsa «Emparejar iPhone».
            </Text>
            {busy ? <Text style={styles.checking}>Comprobando conexión segura…</Text> : null}
            {error ? <ErrorBanner message={error} /> : null}
            {!busy && scannerLocked ? (
              <Button
                label="Escanear de nuevo"
                variant="secondary"
                onPress={() => setScannerLocked(false)}
              />
            ) : null}
          </View>
        </View>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <Screen contentContainerStyle={styles.content}>
        <View style={styles.hero}>
          <View style={styles.logoHalo}>
            <Image
              source={require('../assets/arfoxia.png')}
              style={styles.mascot}
              contentFit="contain"
            />
          </View>
          <Text style={sharedStyles.title}>Arfoxia en tu iPhone</Text>
          <Text style={[sharedStyles.subtitle, styles.center]}>
            Una app nativa para cuidar, hablar y consultar tu PC sin depender de
            Safari.
          </Text>
        </View>

        {error ? <ErrorBanner message={error} /> : null}

        <Button
          label="Escanear QR de Arfoxia"
          icon="⌁"
          busy={busy}
          onPress={() => void openScanner()}
        />

        <Card style={styles.manualCard}>
          <Text style={sharedStyles.label}>Alternativa manual</Text>
          <Text style={sharedStyles.muted}>
            Si no puedes usar la cámara, copia el enlace completo del QR desde el
            PC y pégalo aquí. La clave se guardará en el llavero cifrado.
          </Text>
          <TextInput
            value={manualCode}
            onChangeText={setManualCode}
            placeholder="https://…ts.net/#token=…"
            placeholderTextColor="#6E91A4"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            multiline
            secureTextEntry
            style={styles.input}
          />
          <Button
            label="Emparejar"
            variant="secondary"
            busy={busy}
            disabled={!manualCode.trim()}
            onPress={() => void pair(manualCode)}
          />
        </Card>

        <View style={styles.securityNote}>
          <Text style={styles.securityIcon}>◇</Text>
          <Text style={styles.securityText}>
            La comunicación usa tu red privada de Tailscale. Mantén Tailscale
            conectado en el iPhone para llegar a Arfoxia.
          </Text>
        </View>
      </Screen>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    flexGrow: 1,
    justifyContent: 'center',
    paddingHorizontal: 24,
    paddingVertical: 38,
  },
  hero: {
    alignItems: 'center',
    gap: 10,
    marginBottom: 10,
  },
  logoHalo: {
    width: 150,
    height: 150,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 75,
    marginBottom: 5,
    backgroundColor: '#103B56',
    borderWidth: 1,
    borderColor: '#2B7899',
    shadowColor: colors.iceStrong,
    shadowOpacity: 0.28,
    shadowRadius: 28,
    shadowOffset: { width: 0, height: 7 },
  },
  mascot: {
    width: 128,
    height: 128,
  },
  center: {
    textAlign: 'center',
    maxWidth: 330,
  },
  manualCard: {
    gap: 12,
  },
  input: {
    minHeight: 72,
    padding: 13,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 14,
    backgroundColor: '#071B2A',
    color: colors.text,
    fontSize: 14,
    lineHeight: 20,
    textAlignVertical: 'top',
  },
  securityNote: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    paddingHorizontal: 5,
  },
  securityIcon: {
    color: colors.success,
    fontSize: 18,
    lineHeight: 21,
  },
  securityText: {
    flex: 1,
    color: colors.muted,
    fontSize: 12,
    lineHeight: 19,
  },
  scannerPage: {
    flex: 1,
    backgroundColor: '#000',
  },
  scannerShade: {
    ...StyleSheet.absoluteFillObject,
    paddingHorizontal: 22,
    paddingTop: 58,
    paddingBottom: 45,
    justifyContent: 'space-between',
    backgroundColor: 'rgba(0, 8, 14, 0.32)',
  },
  scannerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  scannerTitle: {
    flex: 1,
    color: '#FFF',
    fontSize: 21,
    lineHeight: 27,
    fontWeight: '800',
    textShadowColor: '#000',
    textShadowRadius: 10,
  },
  closeButton: {
    width: 43,
    height: 43,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 22,
    backgroundColor: 'rgba(0, 17, 28, 0.76)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.45)',
  },
  closeText: {
    color: '#FFF',
    fontSize: 30,
    lineHeight: 31,
  },
  finder: {
    alignSelf: 'center',
    width: 260,
    height: 260,
    borderRadius: 24,
    backgroundColor: 'rgba(255,255,255,0.03)',
  },
  corner: {
    position: 'absolute',
    width: 48,
    height: 48,
    borderColor: colors.ice,
  },
  cornerTopLeft: {
    top: 0,
    left: 0,
    borderTopWidth: 4,
    borderLeftWidth: 4,
    borderTopLeftRadius: 20,
  },
  cornerTopRight: {
    top: 0,
    right: 0,
    borderTopWidth: 4,
    borderRightWidth: 4,
    borderTopRightRadius: 20,
  },
  cornerBottomLeft: {
    bottom: 0,
    left: 0,
    borderBottomWidth: 4,
    borderLeftWidth: 4,
    borderBottomLeftRadius: 20,
  },
  cornerBottomRight: {
    right: 0,
    bottom: 0,
    borderRightWidth: 4,
    borderBottomWidth: 4,
    borderBottomRightRadius: 20,
  },
  scannerFooter: {
    gap: 12,
    padding: 15,
    borderRadius: 20,
    backgroundColor: 'rgba(4, 22, 34, 0.88)',
    borderWidth: 1,
    borderColor: 'rgba(131, 232, 255, 0.40)',
  },
  scannerHelp: {
    color: '#FFF',
    textAlign: 'center',
    fontSize: 14,
    lineHeight: 21,
  },
  checking: {
    color: colors.ice,
    textAlign: 'center',
    fontSize: 13,
    fontWeight: '700',
  },
});
