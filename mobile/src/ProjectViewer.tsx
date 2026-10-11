import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { WebView } from 'react-native-webview';
import { ApiError, type ArfoxiaApi } from './api';
import { previewNavigationAllowed, previewUrl } from './projectPreviews';
import type { ProjectPreview } from './types';
import { Button, ErrorBanner, colors } from './ui';
import { SafeModal } from './SafeModal';

export function ProjectViewer({
  project,
  api,
  onClose,
  onUnauthorized,
}: {
  project: ProjectPreview | null;
  api: ArfoxiaApi;
  onClose: () => void;
  onUnauthorized: () => void;
}) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let disposed = false;
    setUrl('');
    setError('');
    if (!project) return;
    setLoading(true);
    void api
      .openProjectPreview(project.id)
      .then((session) => {
        if (!disposed) setUrl(previewUrl(api.credentials, session));
      })
      .catch((reason) => {
        if (disposed) return;
        if (reason instanceof ApiError && reason.status === 401)
          onUnauthorized();
        setLoading(false);
        setError(
          reason instanceof Error
            ? reason.message
            : 'No se pudo abrir el resultado.',
        );
      });
    return () => {
      disposed = true;
    };
  }, [project, api, revision, onUnauthorized]);
  return (
    <SafeModal
      visible={Boolean(project)}
      animationType="slide"
      onRequestClose={onClose}
      safeAreaStyle={styles.screen}
    >
      <View style={styles.header}>
        <Text style={styles.title} numberOfLines={1} accessibilityRole="header">
          {project?.title || 'Resultado'}
        </Text>
        <View style={styles.actions}>
          <Button
            label="Recargar"
            compact
            variant="ghost"
            onPress={() => setRevision((n) => n + 1)}
          />
          <Button label="Cerrar" compact variant="ghost" onPress={onClose} />
        </View>
      </View>
      <Text style={styles.hint}>
        Arrastra para interactuar · Pellizca para acercar en escenas compatibles
      </Text>
      {error ? (
        <View style={styles.banner}>
          <ErrorBanner message={error} />
        </View>
      ) : null}
      {loading ? (
        <ActivityIndicator color={colors.ice} style={styles.loading} />
      ) : null}
      {url ? (
        <WebView
          key={url}
          style={styles.webview}
          source={{ uri: url }}
          contentInsetAdjustmentBehavior="never"
          automaticallyAdjustContentInsets={false}
          originWhitelist={['https://*']}
          javaScriptEnabled
          domStorageEnabled={false}
          incognito
          sharedCookiesEnabled={false}
          thirdPartyCookiesEnabled={false}
          allowFileAccess={false}
          allowFileAccessFromFileURLs={false}
          allowUniversalAccessFromFileURLs={false}
          mixedContentMode="never"
          javaScriptCanOpenWindowsAutomatically={false}
          setSupportMultipleWindows={false}
          allowsInlineMediaPlayback
          allowsBackForwardNavigationGestures={false}
          onShouldStartLoadWithRequest={(request) =>
            previewNavigationAllowed(request.url, url)
          }
          onLoadEnd={() => setLoading(false)}
          onError={(event) => {
            setLoading(false);
            setError(
              event.nativeEvent.description || 'No se pudo cargar la vista.',
            );
          }}
          onHttpError={() => {
            setLoading(false);
            setError('Vista caducada o archivo no disponible. Pulsa Recargar.');
          }}
        />
      ) : (
        <View style={styles.webview} />
      )}
    </SafeModal>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  header: { gap: 8, paddingHorizontal: 12, paddingVertical: 10 },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'flex-end',
    gap: 8,
  },
  title: { minWidth: 0, color: colors.text, fontWeight: '800', fontSize: 16 },
  hint: {
    color: colors.muted,
    fontSize: 12,
    paddingHorizontal: 12,
    paddingBottom: 8,
  },
  banner: { padding: 12 },
  loading: { padding: 12 },
  webview: { flex: 1, backgroundColor: colors.background },
});
