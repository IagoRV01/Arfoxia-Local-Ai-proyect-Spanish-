import { useState } from 'react';
import { Alert, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import * as Clipboard from 'expo-clipboard';

import { colors } from './ui';

export const codeFontFamily = Platform.OS === 'ios' ? 'Menlo' : 'monospace';

/** Code remains literal: no linking, remote images or execution. */
export function MarkdownCodeBlock({ content, language }: { content: string; language?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await Clipboard.setStringAsync(content);
      setCopied(true);
    } catch {
      Alert.alert('No se ha podido copiar', 'Puedes mantener pulsado el código para seleccionarlo.');
    }
  };
  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text numberOfLines={1} style={styles.language}>{language?.trim().split(/\s+/)[0] || 'código'}</Text>
        <Pressable accessibilityRole="button" accessibilityLabel="Copiar código" onPress={() => void copy()} style={styles.copy}>
          <Text style={styles.label}>{copied ? 'Copiado' : 'Copiar'}</Text>
        </Pressable>
      </View>
      <ScrollView horizontal nestedScrollEnabled directionalLockEnabled showsHorizontalScrollIndicator
        alwaysBounceHorizontal={false} accessibilityLabel="Código desplazable horizontalmente"
        contentContainerStyle={styles.content}>
        <Text selectable style={styles.code}>{content.replace(/\n$/, '')}</Text>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { maxWidth: '100%', alignSelf: 'stretch', backgroundColor: '#071D2C', borderColor: colors.border, borderWidth: 1, borderRadius: 8, marginBottom: 8, overflow: 'hidden' },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: 1, borderBottomColor: colors.border, paddingLeft: 10 },
  language: { flexShrink: 1, fontSize: 11, color: colors.muted },
  copy: { paddingHorizontal: 12, paddingVertical: 10, minHeight: 40, justifyContent: 'center' },
  label: { color: colors.ice, fontSize: 12, fontWeight: '700' },
  content: { padding: 10 },
  code: { color: colors.text, fontFamily: codeFontFamily, fontSize: 13, lineHeight: 20, flexShrink: 0 },
});
