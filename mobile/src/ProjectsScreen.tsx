import { useCallback, useEffect, useState } from 'react';
import { AppState, StyleSheet, Text, View } from 'react-native';
import { ApiError, type ArfoxiaApi } from './api';
import { ProjectViewer } from './ProjectViewer';
import { validatedPreviews } from './projectPreviews';
import type { ProjectPreview } from './types';
import { Button, Card, ErrorBanner, Screen, SectionTitle, colors } from './ui';

export function ProjectsScreen({api, onUnauthorized}: {api: ArfoxiaApi; onUnauthorized: () => void}) {
  const [projects, setProjects] = useState<ProjectPreview[]>([]);
  const [selected, setSelected] = useState<ProjectPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    setBusy(true);
    try {const response = await api.projects(); setProjects(validatedPreviews(response.projects)); setError('');}
    catch (reason) {if (reason instanceof ApiError && reason.status === 401) onUnauthorized();
      setError(reason instanceof Error ? reason.message : 'No se pudo cargar la lista.');}
    finally {setBusy(false);}
  }, [api, onUnauthorized]);
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => {void refresh();}, 15000);
    const listener = AppState.addEventListener('change', state => {if (state === 'active') void refresh();});
    return () => {clearInterval(timer); listener.remove();};
  }, [refresh]);
  return <View style={styles.fill}>
    <Screen>
      <SectionTitle title="Visualizador" subtitle="Resultados guardados en la carpeta Arfoxia del PC"
        trailing={<Button label="Actualizar" compact variant="ghost" busy={busy} onPress={() => void refresh()} />} />
      {error ? <ErrorBanner message={error} /> : null}
      {!projects.length && !busy ? <Card><Text style={styles.text}>Los proyectos aparecerán aquí cuando Arfoxia guarde sus archivos. HTML y escenas 3D son interactivos; imágenes, PDF y código tienen vista de lectura.</Text></Card> : null}
      {projects.map(project => <Card key={project.id}>
        <Text style={styles.title}>{project.title}</Text>
        <Text style={styles.text}>{project.entry} · {project.kind.toUpperCase()}</Text>
        <Button label="Ver resultado" icon="▧" onPress={() => setSelected(project)} />
        {(project.entries?.length ?? 0) > 1 ? <View style={styles.files}>
          {project.entries?.filter(entry => entry.id !== project.id).slice(0, 24).map(entry =>
            <Button key={entry.id} label={entry.entry.split('/').pop() || entry.entry} compact variant="ghost"
              onPress={() => setSelected(entry)} />)}
        </View> : null}
      </Card>)}
      <Text style={styles.text}>Vista privada de solo lectura. Los programas de PC no se ejecutan en el iPhone. Las bibliotecas 3D de CDN necesitan Internet.</Text>
    </Screen>
    <ProjectViewer project={selected} api={api} onClose={() => setSelected(null)} onUnauthorized={onUnauthorized} />
  </View>;
}

const styles = StyleSheet.create({fill: {flex: 1}, title: {color: colors.text, fontSize: 18, fontWeight: '800'},
  text: {color: colors.muted, fontSize: 13, lineHeight: 19}, files: {gap: 5}});
