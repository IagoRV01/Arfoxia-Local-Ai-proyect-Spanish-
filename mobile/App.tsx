import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import {
  SafeAreaProvider,
  SafeAreaView,
} from 'react-native-safe-area-context';

import { ApiError, ArfoxiaApi } from './src/api';
import { ChatScreen } from './src/ChatScreen';
import { CompanionScreen } from './src/CompanionScreen';
import {
  clearCredentials,
  loadCredentials,
} from './src/credentials';
import { PairScreen } from './src/PairScreen';
import { GamingLauncher } from './src/GamingLauncher';
import {
  MOONLIGHT_APP_STORE_URL,
  moonlightShortcutUrl,
} from './src/moonlight';
import { SettingsScreen } from './src/SettingsScreen';
import { SystemScreen } from './src/SystemScreen';
import type { Credentials, Health, TabKey } from './src/types';
import {
  Button,
  Card,
  ErrorBanner,
  colors,
  sharedStyles,
} from './src/ui';

type Phase = 'loading' | 'pairing' | 'ready' | 'offline';

const tabs: Array<{ key: TabKey; icon: string; label: string }> = [
  { key: 'companion', icon: '⌂', label: 'Arfoxia' },
  { key: 'chat', icon: '✦', label: 'Chat' },
  { key: 'system', icon: '▣', label: 'PC' },
  { key: 'settings', icon: '⚙', label: 'Ajustes' },
];

export default function App() {
  const [phase, setPhase] = useState<Phase>('loading');
  const [credentials, setCredentials] = useState<Credentials | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [tab, setTab] = useState<TabKey>('companion');
  const [startupError, setStartupError] = useState('');

  const api = useMemo(
    () => (credentials ? new ArfoxiaApi(credentials) : null),
    [credentials],
  );

  const connect = useCallback(async (saved: Credentials) => {
    setPhase('loading');
    setStartupError('');
    setCredentials(saved);
    const candidate = new ArfoxiaApi(saved);
    try {
      const [nextHealth] = await Promise.all([
        candidate.health(),
        candidate.state(),
      ]);
      setHealth(nextHealth);
      setPhase('ready');
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) {
        await clearCredentials();
        setCredentials(null);
        setHealth(null);
        setStartupError(
          'La clave guardada ya no es válida. Escanea de nuevo el QR de Arfoxia.',
        );
        setPhase('pairing');
        return;
      }
      setStartupError(
        reason instanceof Error
          ? reason.message
          : 'No se ha podido conectar con Arfoxia.',
      );
      setPhase('offline');
    }
  }, []);

  useEffect(() => {
    void loadCredentials()
      .then((saved) => {
        if (!saved) {
          setPhase('pairing');
          return;
        }
        return connect(saved);
      })
      .catch(() => {
        setStartupError('No se ha podido leer el emparejamiento del llavero.');
        setPhase('pairing');
      });
  }, [connect]);

  const unauthorized = useCallback(() => {
    void clearCredentials().finally(() => {
      setCredentials(null);
      setHealth(null);
      setPhase('pairing');
      setStartupError(
        'El emparejamiento ha caducado. Vuelve a escanear el QR de Arfoxia.',
      );
      Alert.alert(
        'Vuelve a emparejar',
        'La clave de Arfoxia ya no es válida y se ha borrado de este iPhone.',
      );
    });
  }, []);

  const unpair = useCallback(async () => {
    await clearCredentials();
    setCredentials(null);
    setHealth(null);
    setTab('companion');
    setStartupError('');
    setPhase('pairing');
  }, []);

  const paired = useCallback(
    (nextCredentials: Credentials, nextHealth: Health) => {
      setCredentials(nextCredentials);
      setHealth(nextHealth);
      setStartupError('');
      setTab('companion');
      setPhase('ready');
    },
    [],
  );

  let content;
  if (phase === 'loading') {
    content = <LoadingScreen />;
  } else if (phase === 'pairing' || !credentials || !api) {
    content = (
      <View style={styles.flex}>
        {startupError ? (
          <View style={styles.startupBanner}>
            <ErrorBanner message={startupError} />
          </View>
        ) : null}
        <PairScreen onPaired={paired} />
      </View>
    );
  } else if (phase === 'offline') {
    content = (
      <OfflineScreen
        message={startupError}
        onRetry={() => void connect(credentials)}
        onUnpair={() => void unpair()}
      />
    );
  } else {
    content = (
      <View style={styles.app}>
        <View style={styles.content}>
          {tab === 'companion' ? (
            <CompanionScreen api={api} onUnauthorized={unauthorized} />
          ) : null}
          <View
            style={[
              styles.tabPanel,
              tab !== 'chat' && styles.tabPanelHidden,
            ]}
          >
            <ChatScreen
              api={api}
              active={tab === 'chat'}
              onUnauthorized={unauthorized}
            />
          </View>
          {tab === 'system' ? (
            <SystemScreen api={api} onUnauthorized={unauthorized} />
          ) : null}
          {tab === 'settings' ? (
            <SettingsScreen
              api={api}
              health={health}
              onUnpair={unpair}
              onUnauthorized={unauthorized}
            />
          ) : null}
        </View>
        <GamingLauncher api={api} onUnauthorized={unauthorized} />
        <BottomNavigation active={tab} onChange={setTab} />
      </View>
    );
  }

  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      <SafeAreaView style={styles.safeArea} edges={['top', 'bottom']}>
        {content}
      </SafeAreaView>
    </SafeAreaProvider>
  );
}

function LoadingScreen() {
  return (
    <View style={styles.loading}>
      <View style={styles.loadingMark}>
        <Text style={styles.loadingSnow}>❄</Text>
      </View>
      <ActivityIndicator color={colors.ice} />
      <Text style={styles.loadingText}>Buscando a Arfoxia…</Text>
    </View>
  );
}

function OfflineScreen({
  message,
  onRetry,
  onUnpair,
}: {
  message: string;
  onRetry: () => void;
  onUnpair: () => void;
}) {
  return (
    <View style={styles.offline}>
      <Card style={styles.offlineCard}>
        <Text style={styles.offlineIcon}>☾</Text>
        <Text style={[sharedStyles.title, styles.center]}>Arfoxia no responde</Text>
        <Text style={[sharedStyles.subtitle, styles.center]}>
          {message ||
            'Comprueba que el PC esté encendido y Tailscale conectado en el iPhone.'}
        </Text>
        <View style={styles.offlineActions}>
          <Button
            label="Abrir Moonlight"
            icon="🎮"
            onPress={() => void openMoonlightOffline()}
          />
          <Button label="Volver a intentar" onPress={onRetry} />
          <Button
            label="Desemparejar"
            variant="ghost"
            onPress={onUnpair}
          />
        </View>
      </Card>
    </View>
  );
}

async function openMoonlightOffline() {
  try {
    await Linking.openURL(moonlightShortcutUrl());
  } catch {
    try {
      await Linking.openURL(MOONLIGHT_APP_STORE_URL);
    } catch {
      Alert.alert(
        'No se ha podido abrir Moonlight',
        'Abre Moonlight manualmente o comprueba que esté instalado.',
      );
    }
  }
}

function BottomNavigation({
  active,
  onChange,
}: {
  active: TabKey;
  onChange: (tab: TabKey) => void;
}) {
  return (
    <View style={styles.navigation}>
      {tabs.map((item) => {
        const selected = item.key === active;
        return (
          <Pressable
            key={item.key}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            onPress={() => onChange(item.key)}
            style={({ pressed }) => [
              styles.navItem,
              selected && styles.navItemSelected,
              pressed && styles.navItemPressed,
            ]}
          >
            <Text style={[styles.navIcon, selected && styles.navTextSelected]}>
              {item.icon}
            </Text>
            <Text style={[styles.navLabel, selected && styles.navTextSelected]}>
              {item.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.background,
  },
  flex: {
    flex: 1,
  },
  app: {
    flex: 1,
  },
  content: {
    flex: 1,
  },
  tabPanel: {
    flex: 1,
  },
  tabPanelHidden: {
    display: 'none',
  },
  startupBanner: {
    paddingHorizontal: 20,
    paddingTop: 12,
    backgroundColor: colors.background,
  },
  loading: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 14,
    backgroundColor: colors.background,
  },
  loadingMark: {
    width: 76,
    height: 76,
    borderRadius: 38,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 5,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  loadingSnow: {
    color: colors.ice,
    fontSize: 34,
  },
  loadingText: {
    color: colors.muted,
    fontSize: 14,
    fontWeight: '700',
  },
  offline: {
    flex: 1,
    justifyContent: 'center',
    padding: 22,
    backgroundColor: colors.background,
  },
  offlineCard: {
    alignItems: 'center',
    gap: 13,
    paddingVertical: 30,
  },
  offlineIcon: {
    color: colors.ice,
    fontSize: 45,
  },
  center: {
    textAlign: 'center',
  },
  offlineActions: {
    alignSelf: 'stretch',
    gap: 9,
    marginTop: 7,
  },
  navigation: {
    minHeight: 65,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 7,
    backgroundColor: '#081C2B',
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  navItem: {
    flex: 1,
    minHeight: 51,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
    borderRadius: 14,
  },
  navItemSelected: {
    backgroundColor: 'rgba(131, 232, 255, 0.10)',
  },
  navItemPressed: {
    opacity: 0.72,
  },
  navIcon: {
    color: colors.muted,
    fontSize: 18,
    lineHeight: 21,
  },
  navLabel: {
    color: colors.muted,
    fontSize: 10,
    lineHeight: 13,
    fontWeight: '800',
  },
  navTextSelected: {
    color: colors.ice,
  },
});
