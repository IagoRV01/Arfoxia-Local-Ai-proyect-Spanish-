import type { PropsWithChildren } from 'react';
import {
  Modal,
  StyleSheet,
  type ModalProps,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';

type SafeModalProps = PropsWithChildren<
  ModalProps & {
    safeAreaStyle?: StyleProp<ViewStyle>;
  }
>;

export function SafeModal({
  children,
  safeAreaStyle,
  transparent = false,
  presentationStyle = transparent ? 'overFullScreen' : 'fullScreen',
  ...props
}: SafeModalProps) {
  // A native Modal has a separate view hierarchy on iOS. The app's outer
  // provider is not a native ancestor here: measure this window independently.
  // Do not seed remounting modals with stale initialWindowMetrics or fixed
  // status-bar heights. Native insets also protect side notches and gestures.
  return (
    <Modal
      {...props}
      transparent={transparent}
      presentationStyle={presentationStyle}
    >
      <SafeAreaProvider>
        <SafeAreaView
          style={[styles.content, safeAreaStyle]}
          edges={['top', 'right', 'bottom', 'left']}
        >
          {children}
        </SafeAreaView>
      </SafeAreaProvider>
    </Modal>
  );
}

const styles = StyleSheet.create({ content: { flex: 1 } });
