import type { ChatResponse } from './types';

export interface WorkTask {
  id: string;
  conversation_id: string;
  status: string;
  rounds: number;
  calls: number;
  last_action: string;
  message?: string;
  result?: ChatResponse;
}

export const taskActive = (task: WorkTask) =>
  ['queued', 'running', 'cancelling'].includes(task.status);

export async function waitForWorkTask(
  initial: WorkTask,
  get: (id: string) => Promise<WorkTask>,
  progress?: (task: WorkTask) => void,
  delay: () => Promise<void> = () => new Promise(resolve => setTimeout(resolve, 2000)),
): Promise<ChatResponse> {
  let task = initial;
  for (;;) {
    progress?.(task);
    if (!taskActive(task)) {
      if (task.result) return task.result;
      // A very fast job can finish before POST returns; GET resolves its saved chat result.
      task = await get(task.id);
      if (task.result) return task.result;
      throw new Error(task.message ?? 'La tarea se ha detenido. Revisa el historial antes de continuar.');
    }
    await delay();
    task = await get(task.id); // Never submit/replay the original POST on a lost connection.
  }
}
