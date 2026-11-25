// Inverted lists put index zero at the bottom, without estimating row heights.
// Keep the canonical conversation chronological; reverse only its display copy.
export function newestFirst<T>(entries: readonly T[]): T[] {
  return [...entries].reverse();
}

export function isNearLatest(offset: number): boolean {
  return Number.isFinite(offset) && offset <= 64;
}
