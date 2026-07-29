import type { PropsWithChildren, ReactNode } from 'react';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type PressableProps,
  type ScrollViewProps,
} from 'react-native';
import { Image } from 'expo-image';

export const colors = {
  background: '#061522',
  backgroundRaised: '#0A2031',
  card: '#0D2A40',
  cardLight: '#123852',
  border: '#235572',
  ice: '#83E8FF',
  iceStrong: '#35CFF4',
  text: '#F3FBFF',
  muted: '#A9C5D3',
  danger: '#FF8D9A',
  warning: '#FFD283',
  success: '#7BE0B3',
  shadow: '#020912',
};

export function Screen({
  children,
  contentContainerStyle,
  ...props
}: PropsWithChildren<ScrollViewProps>) {
  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[styles.screenContent, contentContainerStyle]}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
      {...props}
    >
      {children}
    </ScrollView>
  );
}

export function Card({
  children,
  style,
}: PropsWithChildren<{ style?: object }>) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function SectionTitle({
  title,
  subtitle,
  trailing,
}: {
  title: string;
  subtitle?: string;
  trailing?: ReactNode;
}) {
  return (
    <View style={styles.sectionHeader}>
      <View style={styles.sectionText}>
        <Text style={styles.sectionTitle}>{title}</Text>
        {subtitle ? <Text style={styles.sectionSubtitle}>{subtitle}</Text> : null}
      </View>
      {trailing}
    </View>
  );
}

type ButtonProps = PressableProps & {
  label: string;
  icon?: string;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  busy?: boolean;
  compact?: boolean;
};

export function Button({
  label,
  icon,
  variant = 'primary',
  busy = false,
  compact = false,
  disabled,
  style,
  ...props
}: ButtonProps) {
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled || busy}
      style={({ pressed }) => [
        styles.button,
        styles[`button_${variant}`],
        compact && styles.buttonCompact,
        (disabled || busy) && styles.buttonDisabled,
        pressed && styles.buttonPressed,
        typeof style === 'function' ? style({ pressed }) : style,
      ]}
      {...props}
    >
      {busy ? (
        <ActivityIndicator
          size="small"
          color={variant === 'primary' ? colors.background : colors.ice}
        />
      ) : (
        <>
          {icon ? <Text style={styles.buttonIcon}>{icon}</Text> : null}
          <Text
            style={[
              styles.buttonText,
              variant === 'primary' && styles.buttonTextPrimary,
              variant === 'danger' && styles.buttonTextDanger,
            ]}
          >
            {label}
          </Text>
        </>
      )}
    </Pressable>
  );
}

export function StatusPill({
  label,
  tone = 'success',
}: {
  label: string;
  tone?: 'success' | 'warning' | 'danger' | 'neutral';
}) {
  const toneColor = {
    success: colors.success,
    warning: colors.warning,
    danger: colors.danger,
    neutral: colors.muted,
  }[tone];
  return (
    <View style={[styles.pill, { borderColor: toneColor }]}>
      <View style={[styles.pillDot, { backgroundColor: toneColor }]} />
      <Text style={[styles.pillText, { color: toneColor }]}>{label}</Text>
    </View>
  );
}

export function Meter({
  label,
  value,
  invert = false,
}: {
  label: string;
  value: number;
  invert?: boolean;
}) {
  const normalized = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  const positive = invert ? 100 - normalized : normalized;
  return (
    <View style={styles.meter}>
      <View style={styles.meterHeader}>
        <Text style={styles.meterLabel}>{label}</Text>
        <Text style={styles.meterValue}>{Math.round(normalized)}</Text>
      </View>
      <View style={styles.meterTrack}>
        <View style={[styles.meterFill, { width: `${positive}%` }]} />
      </View>
    </View>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <View style={styles.errorBanner}>
      <Text style={styles.errorIcon}>!</Text>
      <Text style={styles.errorText}>{message}</Text>
    </View>
  );
}

export function EmptyState({
  icon,
  title,
  detail,
}: {
  icon: string;
  title: string;
  detail: string;
}) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyIcon}>{icon}</Text>
      <Text style={styles.emptyTitle}>{title}</Text>
      <Text style={styles.emptyDetail}>{detail}</Text>
    </View>
  );
}

export function ScreenshotModal({
  visible,
  source,
  title = 'Monitor principal',
  hint = 'La captura se solicita de forma privada a través de Tailscale.',
  onClose,
}: {
  visible: boolean;
  source: { uri: string; headers: Record<string, string> } | null;
  title?: string;
  hint?: string;
  onClose: () => void;
}) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.modalBackdrop}>
        <View style={styles.modalCard}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle} numberOfLines={1}>
              {title}
            </Text>
            <Button label="Cerrar" variant="ghost" compact onPress={onClose} />
          </View>
          {source ? (
            <Image
              source={source}
              style={styles.screenshot}
              contentFit="contain"
              cachePolicy="none"
              transition={150}
            />
          ) : null}
          <Text style={styles.modalHint}>{hint}</Text>
        </View>
      </View>
    </Modal>
  );
}

export const sharedStyles = StyleSheet.create({
  title: {
    color: colors.text,
    fontSize: 30,
    lineHeight: 36,
    fontWeight: '800',
    letterSpacing: -0.7,
  },
  subtitle: {
    color: colors.muted,
    fontSize: 15,
    lineHeight: 22,
  },
  body: {
    color: colors.text,
    fontSize: 15,
    lineHeight: 22,
  },
  muted: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 19,
  },
  label: {
    color: colors.ice,
    fontSize: 12,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  wrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
});

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.background,
  },
  screenContent: {
    padding: 18,
    paddingBottom: 34,
    gap: 16,
  },
  card: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 22,
    padding: 17,
    shadowColor: colors.shadow,
    shadowOpacity: 0.28,
    shadowRadius: 15,
    shadowOffset: { width: 0, height: 8 },
    elevation: 4,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  sectionText: {
    flex: 1,
    gap: 3,
  },
  sectionTitle: {
    color: colors.text,
    fontSize: 19,
    lineHeight: 24,
    fontWeight: '800',
  },
  sectionSubtitle: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
  },
  button: {
    minHeight: 48,
    paddingHorizontal: 17,
    paddingVertical: 12,
    borderRadius: 15,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    borderWidth: 1,
  },
  button_primary: {
    backgroundColor: colors.ice,
    borderColor: colors.ice,
  },
  button_secondary: {
    backgroundColor: colors.cardLight,
    borderColor: colors.border,
  },
  button_ghost: {
    backgroundColor: 'transparent',
    borderColor: colors.border,
  },
  button_danger: {
    backgroundColor: 'rgba(255, 141, 154, 0.10)',
    borderColor: 'rgba(255, 141, 154, 0.55)',
  },
  buttonCompact: {
    minHeight: 38,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 12,
  },
  buttonDisabled: {
    opacity: 0.45,
  },
  buttonPressed: {
    transform: [{ scale: 0.98 }],
    opacity: 0.84,
  },
  buttonIcon: {
    color: colors.text,
    fontSize: 17,
  },
  buttonText: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '800',
  },
  buttonTextPrimary: {
    color: colors.background,
  },
  buttonTextDanger: {
    color: colors.danger,
  },
  pill: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    borderWidth: 1,
    borderRadius: 99,
    paddingHorizontal: 10,
    paddingVertical: 6,
    backgroundColor: 'rgba(5, 18, 29, 0.58)',
  },
  pillDot: {
    width: 7,
    height: 7,
    borderRadius: 99,
  },
  pillText: {
    fontSize: 12,
    lineHeight: 15,
    fontWeight: '800',
  },
  meter: {
    gap: 7,
  },
  meterHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  meterLabel: {
    color: colors.muted,
    fontSize: 13,
    fontWeight: '700',
  },
  meterValue: {
    color: colors.text,
    fontSize: 13,
    fontVariant: ['tabular-nums'],
    fontWeight: '800',
  },
  meterTrack: {
    height: 9,
    overflow: 'hidden',
    borderRadius: 99,
    backgroundColor: '#071B2B',
  },
  meterFill: {
    height: '100%',
    borderRadius: 99,
    backgroundColor: colors.iceStrong,
  },
  errorBanner: {
    borderRadius: 15,
    borderWidth: 1,
    borderColor: 'rgba(255, 141, 154, 0.50)',
    backgroundColor: 'rgba(255, 141, 154, 0.10)',
    padding: 12,
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  errorIcon: {
    color: colors.danger,
    fontSize: 15,
    lineHeight: 20,
    fontWeight: '900',
  },
  errorText: {
    flex: 1,
    color: '#FFD9DE',
    fontSize: 13,
    lineHeight: 20,
  },
  empty: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 26,
    paddingVertical: 34,
    gap: 8,
  },
  emptyIcon: {
    fontSize: 31,
  },
  emptyTitle: {
    color: colors.text,
    fontSize: 18,
    fontWeight: '800',
    textAlign: 'center',
  },
  emptyDetail: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 21,
    textAlign: 'center',
  },
  modalBackdrop: {
    flex: 1,
    padding: 15,
    paddingVertical: 52,
    justifyContent: 'center',
    backgroundColor: 'rgba(1, 7, 12, 0.90)',
  },
  modalCard: {
    flex: 1,
    backgroundColor: colors.backgroundRaised,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 14,
    gap: 12,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  modalTitle: {
    color: colors.text,
    fontSize: 18,
    fontWeight: '800',
  },
  screenshot: {
    flex: 1,
    width: '100%',
    borderRadius: 15,
    backgroundColor: '#02080D',
  },
  modalHint: {
    color: colors.muted,
    textAlign: 'center',
    fontSize: 12,
    lineHeight: 17,
  },
});
