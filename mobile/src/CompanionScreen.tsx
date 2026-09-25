import { useCallback, useEffect, useState } from 'react';
import {
  AppState,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Image } from 'expo-image';

import { ApiError, ArfoxiaApi } from './api';
import type { InteractionKind, PetState } from './types';
import {
  Button,
  Card,
  ErrorBanner,
  Meter,
  Screen,
  SectionTitle,
  StatusPill,
  colors,
  sharedStyles,
} from './ui';

type Props = {
  api: ArfoxiaApi;
  onUnauthorized: () => void;
};

const interactionLabels: Array<{
  kind: InteractionKind;
  label: string;
  icon: string;
}> = [
  { kind: 'pet', label: 'Acariciar', icon: '♡' },
  { kind: 'feed', label: 'Dar una baya', icon: '●' },
  { kind: 'play', label: 'Jugar', icon: '✦' },
];

export function CompanionScreen({ api, onUnauthorized }: Props) {
  const [state, setState] = useState<PetState | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [interaction, setInteraction] = useState<InteractionKind | null>(null);
  const [error, setError] = useState('');

  const handleError = useCallback(
    (reason: unknown) => {
      if (reason instanceof ApiError && reason.status === 401) {
        onUnauthorized();
        return;
      }
      setError(
        reason instanceof Error ? reason.message : 'No se ha podido consultar el estado.',
      );
    },
    [onUnauthorized],
  );

  const refresh = useCallback(
    async (showSpinner = false) => {
      if (showSpinner) {
        setRefreshing(true);
      }
      try {
        const next = await api.state();
        setState(next);
        setError('');
      } catch (reason) {
        handleError(reason);
      } finally {
        setRefreshing(false);
      }
    },
    [api, handleError],
  );

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 60_000);
    const subscription = AppState.addEventListener('change', (next) => {
      if (next === 'active') {
        void refresh();
      }
    });
    return () => {
      clearInterval(timer);
      subscription.remove();
    };
  }, [refresh]);

  const interact = useCallback(
    async (kind: InteractionKind) => {
      if (interaction) {
        return;
      }
      setInteraction(kind);
      setError('');
      try {
        const next = await api.interact(kind);
        setState((current) => ({ ...current, ...next }) as PetState);
      } catch (reason) {
        handleError(reason);
      } finally {
        setInteraction(null);
      }
    },
    [api, handleError, interaction],
  );

  const mood = state?.mood
    ? state.mood.charAt(0).toUpperCase() + state.mood.slice(1)
    : 'Conectando…';

  return (
    <Screen
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => void refresh(true)}
          tintColor={colors.ice}
        />
      }
    >
      <View style={styles.header}>
        <View style={styles.headerText}>
          <Text style={sharedStyles.label}>Tu compañera local</Text>
          <Text style={sharedStyles.title}>Arfoxia</Text>
        </View>
        <StatusPill
          label={state ? 'Conectada' : 'Comprobando'}
          tone={state ? 'success' : 'neutral'}
        />
      </View>

      {error ? <ErrorBanner message={error} /> : null}

      <Card style={styles.heroCard}>
        <View style={styles.auroraOne} />
        <View style={styles.auroraTwo} />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Acariciar a Arfoxia"
          disabled={Boolean(interaction)}
          onPress={() => void interact('pet')}
          style={({ pressed }) => [
            styles.mascotButton,
            pressed && styles.mascotPressed,
          ]}
        >
          <View style={styles.mascotGlow}>
            <Image
              source={require('../assets/arfoxia.png')}
              style={styles.mascot}
              contentFit="contain"
              transition={120}
            />
          </View>
        </Pressable>
        <View style={styles.moodRow}>
          <View>
            <Text style={styles.mood}>{mood}</Text>
            <Text style={styles.moodHint}>
              {state?.seated
                ? 'Sentado y despierto. No paseará mientras juegas.'
                : state?.asleep
                ? 'Está descansando. Puedes despertarla cuando quieras.'
                : 'Toca a Arfoxia para acariciarla.'}
            </Text>
          </View>
          <Text style={styles.snowflake}>❄</Text>
        </View>
      </Card>

      <Card style={styles.vitalsCard}>
        <SectionTitle title="Cómo se encuentra" subtitle="Estado actualizado desde el PC" />
        <View style={styles.meters}>
          <Meter label="Hambre" value={state?.hunger ?? 0} invert />
          <Meter label="Felicidad" value={state?.happiness ?? 0} />
          <Meter label="Energía" value={state?.energy ?? 0} />
          <Meter label="Confianza" value={state?.trust ?? 0} />
        </View>
      </Card>

      <View style={styles.actions}>
        {interactionLabels.map((item) => (
          <Button
            key={item.kind}
            label={item.label}
            icon={item.icon}
            variant="secondary"
            busy={interaction === item.kind}
            disabled={!state || Boolean(interaction)}
            onPress={() => void interact(item.kind)}
            style={styles.actionButton}
          />
        ))}
      </View>

      {typeof state?.seated === 'boolean' ? (
        <Button
          label={state.seated ? 'Volver a pasear' : 'Quedarse sentado (sin dormir)'}
          icon="❄"
          variant={state.seated ? 'primary' : 'secondary'}
          busy={interaction === (state.seated ? 'resume' : 'sit')}
          disabled={Boolean(interaction)}
          onPress={() => void interact(state.seated ? 'resume' : 'sit')}
        />
      ) : null}
      <Button
        label={state?.asleep ? 'Despertar a Arfoxia' : 'Ir a dormir'}
        icon={state?.asleep ? '☀' : '☾'}
        variant={state?.asleep ? 'primary' : 'ghost'}
        busy={interaction === (state?.asleep ? 'wake' : 'sleep')}
        disabled={!state || Boolean(interaction)}
        onPress={() => void interact(state?.asleep ? 'wake' : 'sleep')}
      />
    </Screen>
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
  heroCard: {
    minHeight: 314,
    padding: 0,
    overflow: 'hidden',
    justifyContent: 'space-between',
    backgroundColor: '#0B2A42',
  },
  auroraOne: {
    position: 'absolute',
    width: 270,
    height: 270,
    borderRadius: 150,
    top: -135,
    left: -75,
    backgroundColor: 'rgba(51, 208, 244, 0.19)',
  },
  auroraTwo: {
    position: 'absolute',
    width: 250,
    height: 250,
    borderRadius: 150,
    right: -120,
    top: 40,
    backgroundColor: 'rgba(96, 130, 244, 0.17)',
  },
  mascotButton: {
    alignSelf: 'center',
    marginTop: 20,
  },
  mascotPressed: {
    transform: [{ scale: 0.96 }],
  },
  mascotGlow: {
    width: 220,
    height: 210,
    borderRadius: 115,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(120, 229, 255, 0.07)',
    shadowColor: colors.ice,
    shadowOpacity: 0.36,
    shadowRadius: 30,
    shadowOffset: { width: 0, height: 8 },
  },
  mascot: {
    width: 196,
    height: 196,
  },
  moodRow: {
    minHeight: 78,
    paddingHorizontal: 18,
    paddingVertical: 14,
    borderTopWidth: 1,
    borderTopColor: 'rgba(131, 232, 255, 0.18)',
    backgroundColor: 'rgba(4, 18, 29, 0.42)',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  mood: {
    color: colors.text,
    fontSize: 22,
    fontWeight: '800',
  },
  moodHint: {
    color: colors.muted,
    fontSize: 12,
    lineHeight: 18,
    maxWidth: 270,
  },
  snowflake: {
    color: colors.ice,
    fontSize: 28,
  },
  vitalsCard: {
    gap: 18,
  },
  meters: {
    gap: 15,
  },
  actions: {
    flexDirection: 'row',
    gap: 9,
  },
  actionButton: {
    flex: 1,
    minWidth: 0,
    paddingHorizontal: 7,
  },
});
