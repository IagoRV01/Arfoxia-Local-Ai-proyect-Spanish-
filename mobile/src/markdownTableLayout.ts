export type MarkdownAstNode = {
  type: string;
  children?: readonly MarkdownAstNode[];
};

export const MARKDOWN_TABLE_MIN_WIDTH = 280;
export const MARKDOWN_TABLE_COLUMN_WIDTH = 116;

const tableCellTypes = new Set(['th', 'td']);
const tableDividerCell = /^:?-{3,}:?$/;
const columnCountCache = new WeakMap<object, number>();

function tableCells(line: string): string[] {
  let value = line.trim();
  if (value.startsWith('|')) {
    value = value.slice(1);
  }
  if (value.endsWith('|')) {
    value = value.slice(0, -1);
  }
  return value.split('|').map((cell) => cell.trim());
}

export function containsMarkdownTable(source: string): boolean {
  const lines = source.split(/\r?\n/);
  let fenceMarker: '`' | '~' | null = null;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const fence = line.match(/^\s*(`{3,}|~{3,})/);
    if (fence) {
      const marker = fence[1][0] as '`' | '~';
      fenceMarker = fenceMarker === marker ? null : fenceMarker ?? marker;
      continue;
    }
    if (fenceMarker || index === 0 || !line.includes('|')) {
      continue;
    }

    const divider = tableCells(line);
    const header = tableCells(lines[index - 1]);
    if (
      divider.length >= 2 &&
      header.length >= 2 &&
      divider.every((cell) => tableDividerCell.test(cell))
    ) {
      return true;
    }
  }
  return false;
}

export function markdownTableColumnCount(node: MarkdownAstNode): number {
  const cached = columnCountCache.get(node);
  if (cached !== undefined) {
    return cached;
  }
  let maximum = 0;

  const visit = (current: MarkdownAstNode) => {
    if (current.type === 'tr') {
      const count = (current.children ?? []).filter((child) =>
        tableCellTypes.has(child.type),
      ).length;
      maximum = Math.max(maximum, count);
      return;
    }
    for (const child of current.children ?? []) {
      visit(child);
    }
  };

  visit(node);
  columnCountCache.set(node, maximum);
  return maximum;
}

export function markdownTableContentWidth(node: MarkdownAstNode): number {
  return Math.max(
    MARKDOWN_TABLE_MIN_WIDTH,
    markdownTableColumnCount(node) * MARKDOWN_TABLE_COLUMN_WIDTH,
  );
}

export function markdownTableCellWidth(
  parentNodes: readonly MarkdownAstNode[],
): number {
  const table = parentNodes.find((parent) => parent.type === 'table');
  if (!table) {
    return MARKDOWN_TABLE_MIN_WIDTH;
  }
  const columns = Math.max(1, markdownTableColumnCount(table));
  return markdownTableContentWidth(table) / columns;
}
