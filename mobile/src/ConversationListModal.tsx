import { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Modal,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import type { Conversation, ConversationStorage } from './types';
import { Button, EmptyState, ErrorBanner, colors } from './ui';

type Props = {
  visible: boolean;
  conversations: Conversation[];
  storage?: ConversationStorage;
  selectedId: string | null;
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  refreshing: boolean;
  error: string;
  onClose: () => void;
  onRefresh: () => void;
  onLoadMore: () => void;
  onSelect: (conversation: Conversation) => void;
  onCreate: () => Promise<void>;
  onRename: (conversation: Conversation, title: string) => Promise<void>;
  onDelete: (conversation: Conversation) => Promise<void>;
};

function friendlyDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  return date.toLocaleDateString('es-ES', {
    day: '2-digit',
    month: 'short',
    year: date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
  });
}

function storageLabel(storage?: ConversationStorage): string {
  const rawUsed = storage?.used_bytes ?? storage?.stored_bytes;
  const rawQuota = storage?.quota_bytes;
  const used = typeof rawUsed === 'number' ? rawUsed : 0;
  const quota = typeof rawQuota === 'number' ? rawQuota : 0;
  if (!quota) {
    return '';
  }
  return `${(used / 1024 ** 3).toFixed(2)} GB de ${(quota / 1024 ** 3).toFixed(0)} GB usados en el PC`;
}

export function ConversationListModal({
  visible,
  conversations,
  storage,
  selectedId,
  loading,
  loadingMore,
  hasMore,
  refreshing,
  error,
  onClose,
  onRefresh,
  onLoadMore,
  onSelect,
  onCreate,
  onRename,
  onDelete,
}: Props) {
  const [renaming, setRenaming] = useState<Conversation | null>(null);
  const [title, setTitle] = useState('');
  const [operation, setOperation] = useState('');

  const create = useCallback(async () => {
    if (operation) {
      return;
    }
    setOperation('create');
    try {
      await onCreate();
      onClose();
    } catch {
      // The parent keeps the server error visible in this modal.
    } finally {
      setOperation('');
    }
  }, [onClose, onCreate, operation]);

  const openActions = useCallback(
    (conversation: Conversation) => {
      Alert.alert(conversation.title, undefined, [
        {
          text: 'Renombrar',
          onPress: () => {
            setTitle(conversation.title);
            setRenaming(conversation);
          },
        },
        {
          text: 'Eliminar',
          style: 'destructive',
          onPress: () => {
            Alert.alert(
              'Eliminar conversación',
              'Se eliminará este chat y su historial guardado en el PC.',
              [
                { text: 'Cancelar', style: 'cancel' },
                {
                  text: 'Eliminar',
                  style: 'destructive',
                  onPress: () => {
                    setOperation(`delete:${conversation.id}`);
                    void onDelete(conversation)
                      .catch(() => {})
                      .finally(() => setOperation(''));
                  },
                },
              ],
            );
          },
        },
        { text: 'Cancelar', style: 'cancel' },
      ]);
    },
    [onDelete],
  );

  const saveRename = useCallback(async () => {
    const conversation = renaming;
    const nextTitle = title.trim();
    if (!conversation || !nextTitle || operation) {
      return;
    }
    setOperation(`rename:${conversation.id}`);
    try {
      await onRename(conversation, nextTitle);
      setRenaming(null);
      setTitle('');
    } catch {
      // The parent keeps the server error visible for correction/retry.
    } finally {
      setOperation('');
    }
  }, [onRename, operation, renaming, title]);

  return (
    <>
      <Modal
        visible={visible}
        animationType="slide"
        presentationStyle="fullScreen"
        onRequestClose={onClose}
      >
        <SafeAreaView style={styles.safeArea} edges={['top', 'bottom']}>
          <View style={styles.header}>
            <View style={styles.headerText}>
              <Text style={styles.eyebrow}>Historial compartido</Text>
              <Text style={styles.title}>Conversaciones</Text>
            </View>
            <Button label="Cerrar" variant="ghost" compact onPress={onClose} />
          </View>

          <View style={styles.createWrap}>
            <Button
              label="Nueva conversación"
              icon="+"
              busy={operation === 'create'}
              disabled={Boolean(operation)}
              onPress={() => void create()}
            />
            {storageLabel(storage) ? (
              <Text style={styles.storage}>{storageLabel(storage)}</Text>
            ) : null}
          </View>

          {error ? (
            <View style={styles.banner}>
              <ErrorBanner message={error} />
            </View>
          ) : null}

          {loading && !conversations.length ? (
            <View style={styles.loading}>
              <ActivityIndicator color={colors.ice} />
              <Text style={styles.loadingText}>Cargando tus chats…</Text>
            </View>
          ) : (
            <FlatList
              data={conversations}
              keyExtractor={(item) => item.id}
              refreshControl={
                <RefreshControl
                  refreshing={refreshing}
                  onRefresh={onRefresh}
                  tintColor={colors.ice}
                />
              }
              contentContainerStyle={[
                styles.list,
                !conversations.length && styles.emptyList,
              ]}
              ListEmptyComponent={
                <EmptyState
                  icon="✦"
                  title="Todavía no hay conversaciones"
                  detail="Crea una para empezar a hablar con Arfoxia."
                />
              }
              ItemSeparatorComponent={() => <View style={styles.separator} />}
              onEndReachedThreshold={0.35}
              onEndReached={() => {
                if (hasMore && !loadingMore) {
                  onLoadMore();
                }
              }}
              ListFooterComponent={
                loadingMore ? (
                  <View style={styles.listFooter}>
                    <ActivityIndicator size="small" color={colors.ice} />
                    <Text style={styles.loadingText}>Cargando más chats…</Text>
                  </View>
                ) : null
              }
              renderItem={({ item }) => {
                const selected = item.id === selectedId;
                const busy = operation.endsWith(item.id);
                return (
                  <Pressable
                    accessibilityRole="button"
                    accessibilityState={{ selected }}
                    disabled={busy}
                    onPress={() => {
                      onSelect(item);
                      onClose();
                    }}
                    style={({ pressed }) => [
                      styles.row,
                      selected && styles.rowSelected,
                      pressed && styles.rowPressed,
                    ]}
                  >
                    <View style={styles.rowText}>
                      <Text style={styles.rowTitle} numberOfLines={1}>
                        {item.title}
                      </Text>
                      <Text style={styles.preview} numberOfLines={2}>
                        {item.preview || 'Conversación vacía'}
                      </Text>
                      <Text style={styles.meta}>
                        {item.message_count} mensajes
                        {friendlyDate(item.updated_at)
                          ? ` · ${friendlyDate(item.updated_at)}`
                          : ''}
                      </Text>
                    </View>
                    {busy ? (
                      <ActivityIndicator size="small" color={colors.ice} />
                    ) : (
                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel={`Opciones de ${item.title}`}
                        hitSlop={10}
                        onPress={(event) => {
                          event.stopPropagation();
                          openActions(item);
                        }}
                        style={styles.more}
                      >
                        <Text style={styles.moreText}>•••</Text>
                      </Pressable>
                    )}
                  </Pressable>
                );
              }}
            />
          )}
        </SafeAreaView>
      </Modal>

      <Modal
        visible={Boolean(renaming)}
        transparent
        animationType="fade"
        onRequestClose={() => setRenaming(null)}
      >
        <View style={styles.renameBackdrop}>
          <View style={styles.renameCard}>
            <Text style={styles.renameTitle}>Renombrar conversación</Text>
            <TextInput
              autoFocus
              value={title}
              onChangeText={setTitle}
              maxLength={80}
              placeholder="Nombre del chat"
              placeholderTextColor={colors.muted}
              selectTextOnFocus
              style={styles.renameInput}
            />
            <View style={styles.renameActions}>
              <Button
                label="Cancelar"
                variant="ghost"
                disabled={Boolean(operation)}
                onPress={() => setRenaming(null)}
              />
              <Button
                label="Guardar"
                busy={operation.startsWith('rename:')}
                disabled={!title.trim()}
                onPress={() => void saveRename()}
              />
            </View>
          </View>
        </View>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    minHeight: 76,
    paddingHorizontal: 18,
    paddingVertical: 13,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerText: {
    flex: 1,
  },
  eyebrow: {
    color: colors.ice,
    fontSize: 10,
    fontWeight: '900',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  title: {
    color: colors.text,
    fontSize: 25,
    fontWeight: '800',
  },
  createWrap: {
    paddingHorizontal: 18,
    paddingTop: 13,
    gap: 7,
  },
  storage: {
    color: colors.muted,
    fontSize: 10,
    lineHeight: 14,
    textAlign: 'center',
  },
  banner: {
    paddingHorizontal: 18,
    paddingTop: 10,
  },
  loading: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
  },
  loadingText: {
    color: colors.muted,
    fontSize: 13,
  },
  list: {
    padding: 16,
    paddingBottom: 28,
  },
  emptyList: {
    flexGrow: 1,
    justifyContent: 'center',
  },
  separator: {
    height: 9,
  },
  listFooter: {
    minHeight: 62,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 9,
  },
  row: {
    minHeight: 91,
    padding: 13,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  rowSelected: {
    borderColor: colors.iceStrong,
    backgroundColor: colors.cardLight,
  },
  rowPressed: {
    opacity: 0.75,
  },
  rowText: {
    flex: 1,
    gap: 3,
  },
  rowTitle: {
    color: colors.text,
    fontSize: 15,
    lineHeight: 19,
    fontWeight: '800',
  },
  preview: {
    color: colors.muted,
    fontSize: 12,
    lineHeight: 17,
  },
  meta: {
    color: '#7197AA',
    fontSize: 10,
    lineHeight: 14,
  },
  more: {
    width: 38,
    height: 38,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 12,
    backgroundColor: '#081D2C',
  },
  moreText: {
    color: colors.ice,
    fontSize: 15,
    letterSpacing: 1,
  },
  renameBackdrop: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 22,
    backgroundColor: 'rgba(1, 8, 14, 0.78)',
  },
  renameCard: {
    width: '100%',
    maxWidth: 430,
    padding: 18,
    gap: 14,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.backgroundRaised,
  },
  renameTitle: {
    color: colors.text,
    fontSize: 19,
    fontWeight: '800',
  },
  renameInput: {
    minHeight: 48,
    paddingHorizontal: 13,
    borderRadius: 13,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background,
    color: colors.text,
    fontSize: 15,
  },
  renameActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 8,
  },
});
