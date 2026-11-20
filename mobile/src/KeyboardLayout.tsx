import { useEffect, useState, type ReactNode } from 'react';
import { Keyboard, KeyboardAvoidingView, Platform, StyleSheet } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

/** One keyboard owner for the main window; native modals own their own layout. */
export function MainKeyboardLayout({
  children,
  footer,
}: {
  children: ReactNode;
  footer: (keyboardVisible: boolean) => ReactNode;
}) {
  const insets = useSafeAreaInsets();
  const [keyboardVisible, setKeyboardVisible] = useState(() => Keyboard.isVisible());

  useEffect(() => {
    const show = Keyboard.addListener(
      Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow',
      () => setKeyboardVisible(true),
    );
    const hide = Keyboard.addListener(
      Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide',
      () => setKeyboardVisible(false),
    );
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);

  return (
    <KeyboardAvoidingView
      style={styles.layout}
      behavior="padding"
      keyboardVerticalOffset={insets.top}
    >
      {children}
      {footer(keyboardVisible)}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  layout: { flex: 1, minHeight: 0 },
});
