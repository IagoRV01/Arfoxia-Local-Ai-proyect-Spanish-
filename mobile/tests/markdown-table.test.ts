import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MARKDOWN_TABLE_COLUMN_WIDTH,
  MARKDOWN_TABLE_MIN_WIDTH,
  containsMarkdownTable,
  markdownTableCellWidth,
  markdownTableColumnCount,
  markdownTableContentWidth,
  type MarkdownAstNode,
} from '../src/markdownTableLayout';

function row(type: 'th' | 'td', columns: number): MarkdownAstNode {
  return {
    type: 'tr',
    children: Array.from({ length: columns }, () => ({
      type,
      children: [{ type: 'text' }],
    })),
  };
}

function table(headerColumns: number, bodyColumns = headerColumns): MarkdownAstNode {
  return {
    type: 'table',
    children: [
      { type: 'thead', children: [row('th', headerColumns)] },
      { type: 'tbody', children: [row('td', bodyColumns)] },
    ],
  };
}

test('gives wide mobile tables a readable horizontally scrollable width', () => {
  const node = table(6);

  assert.equal(markdownTableColumnCount(node), 6);
  assert.equal(
    markdownTableContentWidth(node),
    6 * MARKDOWN_TABLE_COLUMN_WIDTH,
  );
  assert.ok(markdownTableContentWidth(node) > 320);
  assert.ok(MARKDOWN_TABLE_COLUMN_WIDTH >= 112);
  assert.equal(
    markdownTableCellWidth([{ type: 'tr' }, node]),
    MARKDOWN_TABLE_COLUMN_WIDTH,
  );
});

test('keeps a two-column table within the normal mobile viewport', () => {
  const node = table(2);

  assert.equal(markdownTableColumnCount(node), 2);
  assert.equal(markdownTableContentWidth(node), MARKDOWN_TABLE_MIN_WIDTH);
  assert.equal(
    markdownTableCellWidth([{ type: 'tr' }, node]),
    MARKDOWN_TABLE_MIN_WIDTH / 2,
  );
});

test('uses the widest irregular row and tolerates malformed tables', () => {
  assert.equal(markdownTableColumnCount(table(3, 7)), 7);
  assert.equal(markdownTableColumnCount({ type: 'table' }), 0);
  assert.equal(
    markdownTableContentWidth({ type: 'table' }),
    MARKDOWN_TABLE_MIN_WIDTH,
  );
});

test('detects Markdown tables but ignores lookalikes inside code fences', () => {
  assert.equal(
    containsMarkdownTable('| Modelo | VRAM |\n| --- | ---: |\n| RTX | 12 GB |'),
    true,
  );
  assert.equal(
    containsMarkdownTable('Modelo | VRAM\n--- | ---:\nRTX | 12 GB'),
    true,
  );
  assert.equal(
    containsMarkdownTable(
      '```md\n| Modelo | VRAM |\n| --- | --- |\n| RTX | 12 GB |\n```',
    ),
    false,
  );
  assert.equal(containsMarkdownTable('Texto normal | con una barra'), false);
});

test('a shorter or nonempty fence cannot close a literal code block', () => {
  const tableSource = '| Modelo | VRAM |\n| --- | --- |\n| RTX | 12 GB |';
  assert.equal(containsMarkdownTable(`\`\`\`\`md\n\`\`\`\n${tableSource}\n\`\`\`\``), false);
  assert.equal(containsMarkdownTable(`~~~md\n~~~still code\n${tableSource}\n~~~`), false);
  assert.equal(containsMarkdownTable(`\`\`\`\`md\n\`\`\`\`\n${tableSource}`), true);
});
