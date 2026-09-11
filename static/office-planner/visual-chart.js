/** Pure flowchart layout helpers for the local visual planner whiteboard. */

export const BOX_W = 240;
export const LINE_H = 15;
export const TITLE_CHARS = 28;
export const COL_GAP = 64;
export const ROW_GAP = 28;

export function wrapTitleLines(text, maxChars = TITLE_CHARS) {
  const words = String(text || '').split(/\s+/).filter(Boolean);
  const lines = [];
  let line = '';
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (next.length > maxChars && line) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines.length ? lines : [''];
}

export function layoutFlowchart(plan) {
  const byId = Object.fromEntries(plan.tasks.map((t) => [t.id, t]));
  const depth = new Map();
  const level = (id, stack = new Set()) => {
    if (depth.has(id)) return depth.get(id);
    if (stack.has(id)) return 0;
    stack.add(id);
    const deps = (byId[id]?.depends || []).filter((d) => byId[d]);
    const value = deps.length ? Math.max(...deps.map((d) => level(d, stack))) + 1 : 0;
    stack.delete(id);
    depth.set(id, value);
    return value;
  };
  for (const task of plan.tasks) level(task.id);
  const columns = new Map();
  for (const task of plan.tasks) {
    const col = depth.get(task.id) || 0;
    if (!columns.has(col)) columns.set(col, []);
    columns.get(col).push(task);
  }
  const positions = new Map();
  let maxX = 0;
  let maxY = 0;
  let x = 36;
  for (const col of [...columns.keys()].sort((a, b) => a - b)) {
    let y = 36;
    for (const task of columns.get(col)) {
      const lines = wrapTitleLines(task.title);
      const h = Math.max(44, 22 + lines.length * LINE_H);
      positions.set(task.id, { x, y, w: BOX_W, h, lines, task });
      y += h + ROW_GAP;
      maxY = Math.max(maxY, y);
    }
    maxX = Math.max(maxX, x + BOX_W);
    x += BOX_W + COL_GAP;
  }
  return { positions, width: Math.max(720, maxX + 36), height: Math.max(280, maxY + 24), depth };
}

export function pickLatestPlan(plans, reviewId = '') {
  const scoped = (plans || []).filter((p) => !reviewId || p.review_project_id === reviewId);
  if (!scoped.length) return null;
  const preferred = scoped.filter((p) =>
    String(p.title || '').includes('Smedley Cursor — Local-First Control'));
  const pool = preferred.length ? preferred : scoped;
  return pool.slice().sort((a, b) => {
    const va = Number(a.version) || 0;
    const vb = Number(b.version) || 0;
    if (vb !== va) return vb - va;
    return String(b.saved_at || '').localeCompare(String(a.saved_at || ''));
  })[0];
}
