# UI Workbench Phase 1 (itr_extract_fe) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the itr_extract_fe UI as the approved "Workbench" design (3 panes: queue · work area · verify checklist) with zero backend changes.

**Architecture:** Pure-frontend restructure of the existing React app. All data comes from the existing `GET/POST /api/jobs` API and `analysis_data`/`email_html` fields. New pure libs (figure parser, review state, duration estimate) carry the logic and get unit tests; components stay thin. Existing hooks (`useJobs`, `useJobPolling`, `useAccessToken`), `apiClient`, `graphApi`, MSAL setup are **not modified**.

**Tech Stack:** React 19 + TypeScript + Vite (existing). New dev-dependency: `vitest` (unit tests for pure libs only). **No new runtime dependencies.**

**Spec:** `itr_extract/docs/superpowers/specs/2026-07-14-ui-workbench-phase1-design.md`
**Visual reference:** `itr_extract/docs/ui-proposals/option-c-workbench.html` (v2 — canonical for colors/spacing/copy)

## Global Constraints

- Working directory for ALL commands: `/home/tplong/WorkSpace/itr_extract_fe` (sibling repo). Create a feature branch first — do not commit to `main`.
- Backend repo `itr_extract` must remain untouched.
- No new runtime deps. Only new devDependency: `vitest`. Do not add pdf.js, no UI libraries, no CSS frameworks.
- Do NOT modify: `src/lib/apiClient.ts`, `src/lib/graphApi.ts`, `src/lib/msalConfig.ts`, `src/hooks/useAccessToken.ts`, `src/hooks/useJobs.ts`, `src/hooks/useJobPolling.ts`, `src/lib/toast.tsx`, `src/lib/types.ts`, `src/main.tsx`.
- App UI copy stays **English**. Use existing constants from `src/lib/constants.ts` (e.g. `MAX_SESSIONS_PER_USER = 10`) — never hardcode limits.
- Send button is **never disabled** by verification state (Mức 2 decision). No % progress invented anywhere — processing progress is elapsed-vs-typical only.
- Every money/date string rendered in the checklist must keep a fallback to the raw sentence (`sourceSentence`) when parsing fails.
- Numbers use `font-variant-numeric: tabular-nums` (class `num`).
- All interactive elements need a visible `:focus-visible` state; animations wrapped in `@media (prefers-reduced-motion: no-preference)`.
- Verify after each task: `npm run lint && npm run build` must pass (plus `npm test` once vitest exists).

---

### Task 0: Branch + vitest infrastructure

**Files:**
- Modify: `package.json` (add script + devDependency)

**Interfaces:**
- Produces: `npm test` runs vitest; branch `feat/ui-workbench-phase1`.

- [ ] **Step 1: Create branch**

```bash
cd /home/tplong/WorkSpace/itr_extract_fe
git checkout -b feat/ui-workbench-phase1
```

- [ ] **Step 2: Install vitest**

```bash
npm install -D vitest
```

- [ ] **Step 3: Add test script** — in `package.json` `"scripts"` add:

```json
"test": "vitest run"
```

- [ ] **Step 4: Verify vitest runs (no tests yet)**

Run: `npm test`
Expected: exits reporting "No test files found" (non-zero is fine at this point).

- [ ] **Step 5: Commit**

```bash
git add package.json package-lock.json
git commit -m "chore: add vitest for pure-lib unit tests"
```

---

### Task 1: Figure parser lib (`buildVerifyItems`) — TDD

**Files:**
- Create: `src/lib/verifyItems.ts`
- Test: `src/lib/verifyItems.test.ts`

**Interfaces:**
- Consumes: `analysis_data: Record<string, unknown> | null` (shape produced by backend Task 2 + Task 1, see spec §5).
- Produces:

```ts
export interface VerifyItem {
  id: string;                       // stable: `${kind}:${index}`
  label: string;
  sublabel: string;
  amount: number | null;
  amountRaw: string | null;         // e.g. "$12,450" — used for email cross-highlight
  direction: 'due' | 'refund' | 'info';
  date: string | null;              // normalized MM/DD/YYYY
  sourceSentence: string;           // raw sentence, always present for fallback
}
export function buildVerifyItems(analysis: Record<string, unknown> | null): VerifyItem[];
```

- [ ] **Step 1: Write the failing tests**

```ts
// src/lib/verifyItems.test.ts
import { describe, it, expect } from 'vitest';
import { buildVerifyItems } from './verifyItems';

const analysis = {
  return_type: 'S-Corporation (1120S)',
  tax_year: '2025',
  next_year: '2026',
  tax_summary: {
    federal_sentence:
      'You have a **balance due of $12,450**, which will be automatically withdrawn on **September 15, 2026**.',
    state_sentences: [
      {
        state_name: 'California', state_abbreviation: 'CA', display_label: 'California',
        sentence: 'You will receive a **refund of $3,280** via direct deposit.',
      },
    ],
  },
  estimated_payments: [
    { date: '09/15/2026', federal: 3100, state: 920, state_name: 'California' },
    { date: '01/15/2027', federal: 3100, state: 920, state_name: 'California' },
  ],
  pte_payments: [
    { sentence: 'The 2026 **1st PTE tax payment of $8,500** is due by June 15, 2026.' },
  ],
};

describe('buildVerifyItems', () => {
  it('returns [] for null analysis', () => {
    expect(buildVerifyItems(null)).toEqual([]);
  });

  it('emits info items for return type and tax year first', () => {
    const items = buildVerifyItems(analysis);
    expect(items[0]).toMatchObject({ id: 'info:0', label: 'Return type', sublabel: 'S-Corporation (1120S)', direction: 'info' });
    expect(items[1]).toMatchObject({ id: 'info:1', label: 'Tax year', sublabel: '2025 · next year 2026' });
  });

  it('parses federal balance due with amount and date from bold segments', () => {
    const fed = buildVerifyItems(analysis).find(i => i.id === 'federal:0')!;
    expect(fed.direction).toBe('due');
    expect(fed.amount).toBe(12450);
    expect(fed.amountRaw).toBe('$12,450');
    expect(fed.date).toBe('09/15/2026');
  });

  it('parses state refund', () => {
    const st = buildVerifyItems(analysis).find(i => i.id === 'state:0')!;
    expect(st.direction).toBe('refund');
    expect(st.amount).toBe(3280);
    expect(st.label).toBe('California');
  });

  it('maps each estimated payment to one item with combined amount', () => {
    const items = buildVerifyItems(analysis);
    const est = items.filter(i => i.id.startsWith('est:'));
    expect(est).toHaveLength(2);
    expect(est[0]).toMatchObject({ amount: 4020, date: '09/15/2026', direction: 'due' });
    expect(est[0].sublabel).toContain('Fed $3,100');
    expect(est[0].sublabel).toContain('California $920');
  });

  it('parses PTE sentence with month-name date', () => {
    const pte = buildVerifyItems(analysis).find(i => i.id === 'pte:0')!;
    expect(pte.amount).toBe(8500);
    expect(pte.date).toBe('06/15/2026');
    expect(pte.direction).toBe('due');
  });

  it('falls back gracefully when a sentence has no parseable amount', () => {
    const broken = { ...analysis, tax_summary: { federal_sentence: 'No payment is required.', state_sentences: [] } };
    const fed = buildVerifyItems(broken).find(i => i.id === 'federal:0')!;
    expect(fed.amount).toBeNull();
    expect(fed.amountRaw).toBeNull();
    expect(fed.direction).toBe('info');
    expect(fed.sourceSentence).toBe('No payment is required.');
  });

  it('is ambiguous-safe: two amounts outside bold → amount null, sentence kept', () => {
    const tricky = {
      ...analysis,
      tax_summary: { federal_sentence: 'Pay $100 or $200 depending on election.', state_sentences: [] },
    };
    const fed = buildVerifyItems(tricky).find(i => i.id === 'federal:0')!;
    expect(fed.amount).toBeNull();
    expect(fed.sourceSentence).toContain('$100 or $200');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/lib/verifyItems.test.ts`
Expected: FAIL — `Cannot find module './verifyItems'` (or equivalent).

- [ ] **Step 3: Implement the parser**

```ts
// src/lib/verifyItems.ts
export interface VerifyItem {
  id: string;
  label: string;
  sublabel: string;
  amount: number | null;
  amountRaw: string | null;
  direction: 'due' | 'refund' | 'info';
  date: string | null;
  sourceSentence: string;
}

const AMOUNT_RE = /\$\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)/g;
const NUMERIC_DATE_RE = /\b(\d{1,2})\/(\d{1,2})\/(\d{4})\b/;
const MONTHS = ['january','february','march','april','may','june','july','august','september','october','november','december'];
const MONTH_DATE_RE = new RegExp(`\\b(${MONTHS.join('|')})\\s+(\\d{1,2}),\\s+(\\d{4})\\b`, 'i');

function fmt(n: number): string {
  return '$' + n.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

function pad(n: number): string { return String(n).padStart(2, '0'); }

function parseDate(text: string): string | null {
  const num = NUMERIC_DATE_RE.exec(text);
  if (num) return `${pad(+num[1])}/${pad(+num[2])}/${num[3]}`;
  const mon = MONTH_DATE_RE.exec(text);
  if (mon) return `${pad(MONTHS.indexOf(mon[1].toLowerCase()) + 1)}/${pad(+mon[2])}/${mon[3]}`;
  return null;
}

/** Amounts inside **bold** first; if none, fall back to whole sentence. Ambiguous (≠1) → null. */
function parseAmount(sentence: string): { amount: number | null; amountRaw: string | null } {
  const boldText = (sentence.match(/\*\*(.+?)\*\*/g) ?? []).join(' ');
  for (const scope of [boldText, sentence]) {
    const matches = [...scope.matchAll(AMOUNT_RE)];
    if (matches.length === 1) {
      const raw = matches[0][0].replace(/\s/, '');
      return { amount: Number(matches[0][1].replace(/,/g, '')), amountRaw: raw };
    }
    if (matches.length > 1) return { amount: null, amountRaw: null };
  }
  return { amount: null, amountRaw: null };
}

function direction(sentence: string): VerifyItem['direction'] {
  const s = sentence.toLowerCase();
  if (/refund|overpayment|applied to/.test(s)) return 'refund';
  if (/balance due|due by|owe|payment of|withdrawn/.test(s)) return 'due';
  return 'info';
}

function sentenceItem(id: string, label: string, sublabel: string, sentence: string): VerifyItem {
  const { amount, amountRaw } = parseAmount(sentence);
  return {
    id, label, sublabel,
    amount, amountRaw,
    direction: amount === null ? 'info' : direction(sentence),
    date: parseDate(sentence),
    sourceSentence: sentence,
  };
}

export function buildVerifyItems(analysis: Record<string, unknown> | null): VerifyItem[] {
  if (!analysis) return [];
  const items: VerifyItem[] = [];
  const a = analysis as Record<string, any>;

  const returnType = typeof a.return_type === 'string' ? a.return_type : '—';
  items.push({
    id: 'info:0', label: 'Return type', sublabel: returnType,
    amount: null, amountRaw: null, direction: 'info', date: null, sourceSentence: returnType,
  });
  const taxYear = a.tax_year ?? '—';
  const nextYear = a.next_year ? ` · next year ${a.next_year}` : '';
  items.push({
    id: 'info:1', label: 'Tax year', sublabel: `${taxYear}${nextYear}`,
    amount: null, amountRaw: null, direction: 'info', date: null, sourceSentence: String(taxYear),
  });

  const summary = (a.tax_summary ?? {}) as Record<string, any>;
  if (typeof summary.federal_sentence === 'string' && summary.federal_sentence) {
    items.push(sentenceItem('federal:0', 'Federal income tax', 'Federal', summary.federal_sentence));
  }
  (Array.isArray(summary.state_sentences) ? summary.state_sentences : []).forEach((st: any, i: number) => {
    if (typeof st?.sentence !== 'string' || !st.sentence) return;
    const label = st.display_label || st.state_name || `State ${i + 1}`;
    items.push(sentenceItem(`state:${i}`, label, 'State income tax', st.sentence));
  });

  (Array.isArray(a.estimated_payments) ? a.estimated_payments : []).forEach((ep: any, i: number) => {
    const fed = Number(ep?.federal) || 0;
    const st = Number(ep?.state) || 0;
    const parts: string[] = [];
    if (fed > 0) parts.push(`Fed ${fmt(fed)}`);
    if (st > 0) parts.push(`${ep?.state_name || 'State'} ${fmt(st)}`);
    const date = typeof ep?.date === 'string' ? parseDate(ep.date) ?? ep.date : null;
    items.push({
      id: `est:${i}`, label: `Estimated payment ${i + 1}`,
      sublabel: parts.join(' + ') || '—',
      amount: fed + st > 0 ? fed + st : null,
      amountRaw: fed + st > 0 ? fmt(fed + st) : null,
      direction: 'due', date, sourceSentence: JSON.stringify(ep),
    });
  });

  (Array.isArray(a.pte_payments) ? a.pte_payments : []).forEach((p: any, i: number) => {
    if (typeof p?.sentence !== 'string' || !p.sentence) return;
    items.push(sentenceItem(`pte:${i}`, `PTE elective tax ${i + 1}`, 'Pass-through entity', p.sentence));
  });

  return items;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/lib/verifyItems.test.ts`
Expected: 8 passed.

- [ ] **Step 5: Lint + commit**

```bash
npm run lint && git add src/lib/verifyItems.ts src/lib/verifyItems.test.ts
git commit -m "feat: figure parser building verify checklist items from analysis_data"
```

---

### Task 2: Review state lib (verify ticks + sent flag) — TDD

**Files:**
- Create: `src/lib/reviewState.ts`
- Test: `src/lib/reviewState.test.ts`

**Interfaces:**
- Produces:

```ts
export interface KVStore { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem(k: string): void; }
export function getVerifySet(jobId: string, store?: KVStore): Set<string>;
export function toggleVerify(jobId: string, itemId: string, store?: KVStore): Set<string>;
export function isSent(jobId: string, store?: KVStore): boolean;
export function markSent(jobId: string, store?: KVStore): void;
```

Keys: `itr.verify.{jobId}` (JSON array of itemIds), `itr.sent.{jobId}` (`"1"`). `store` defaults to `window.localStorage`; tests pass an in-memory stub (vitest runs in node — never touch `window` at module top level).

- [ ] **Step 1: Write the failing tests**

```ts
// src/lib/reviewState.test.ts
import { describe, it, expect } from 'vitest';
import { getVerifySet, toggleVerify, isSent, markSent, type KVStore } from './reviewState';

function memStore(): KVStore {
  const m = new Map<string, string>();
  return {
    getItem: k => m.get(k) ?? null,
    setItem: (k, v) => { m.set(k, v); },
    removeItem: k => { m.delete(k); },
  };
}

describe('reviewState', () => {
  it('starts empty and persists toggles per job', () => {
    const s = memStore();
    expect(getVerifySet('job1', s).size).toBe(0);
    toggleVerify('job1', 'federal:0', s);
    toggleVerify('job1', 'pte:0', s);
    expect([...getVerifySet('job1', s)].sort()).toEqual(['federal:0', 'pte:0']);
    expect(getVerifySet('job2', s).size).toBe(0);
  });

  it('toggle twice removes the tick', () => {
    const s = memStore();
    toggleVerify('job1', 'federal:0', s);
    toggleVerify('job1', 'federal:0', s);
    expect(getVerifySet('job1', s).size).toBe(0);
  });

  it('survives corrupted JSON', () => {
    const s = memStore();
    s.setItem('itr.verify.job1', '{not-json');
    expect(getVerifySet('job1', s).size).toBe(0);
  });

  it('sent flag round-trips', () => {
    const s = memStore();
    expect(isSent('job1', s)).toBe(false);
    markSent('job1', s);
    expect(isSent('job1', s)).toBe(true);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/lib/reviewState.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```ts
// src/lib/reviewState.ts
export interface KVStore {
  getItem(k: string): string | null;
  setItem(k: string, v: string): void;
  removeItem(k: string): void;
}

const defaultStore = (): KVStore => window.localStorage;
const verifyKey = (jobId: string) => `itr.verify.${jobId}`;
const sentKey = (jobId: string) => `itr.sent.${jobId}`;

export function getVerifySet(jobId: string, store: KVStore = defaultStore()): Set<string> {
  try {
    const raw = store.getItem(verifyKey(jobId));
    const arr = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(arr) ? arr.filter(x => typeof x === 'string') : []);
  } catch {
    return new Set();
  }
}

export function toggleVerify(jobId: string, itemId: string, store: KVStore = defaultStore()): Set<string> {
  const set = getVerifySet(jobId, store);
  if (set.has(itemId)) set.delete(itemId); else set.add(itemId);
  store.setItem(verifyKey(jobId), JSON.stringify([...set]));
  return set;
}

export function isSent(jobId: string, store: KVStore = defaultStore()): boolean {
  return store.getItem(sentKey(jobId)) === '1';
}

export function markSent(jobId: string, store: KVStore = defaultStore()): void {
  store.setItem(sentKey(jobId), '1');
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/lib/reviewState.test.ts`
Expected: 4 passed.

- [ ] **Step 5: Lint + commit**

```bash
npm run lint && git add src/lib/reviewState.ts src/lib/reviewState.test.ts
git commit -m "feat: localStorage-backed verify ticks and sent flag"
```

---

### Task 3: Duration estimate lib — TDD

**Files:**
- Create: `src/lib/duration.ts`
- Test: `src/lib/duration.test.ts`

**Interfaces:**
- Produces:

```ts
export const DEFAULT_TYPICAL_MS = 60_000;
export function medianDurationMs(jobs: Array<{ status: string; started_at?: string | null; finished_at: string | null; created_at: string }>): number;
export function formatElapsed(ms: number): string; // 83_000 → "1:23"
```

`medianDurationMs` uses only SUCCESS jobs having both timestamps; empty → `DEFAULT_TYPICAL_MS`.

- [ ] **Step 1: Write the failing tests**

```ts
// src/lib/duration.test.ts
import { describe, it, expect } from 'vitest';
import { medianDurationMs, formatElapsed, DEFAULT_TYPICAL_MS } from './duration';

const job = (status: string, startedSec: number | null, finishedSec: number | null) => ({
  status,
  created_at: '2026-07-14T00:00:00Z',
  started_at: startedSec === null ? null : new Date(startedSec * 1000).toISOString(),
  finished_at: finishedSec === null ? null : new Date(finishedSec * 1000).toISOString(),
});

describe('duration', () => {
  it('defaults to 60s with no usable jobs', () => {
    expect(medianDurationMs([])).toBe(DEFAULT_TYPICAL_MS);
    expect(medianDurationMs([job('failed', 0, 100), job('success', null, 100)])).toBe(DEFAULT_TYPICAL_MS);
  });

  it('takes the median of success durations', () => {
    const jobs = [job('success', 0, 40), job('success', 0, 60), job('success', 0, 300)];
    expect(medianDurationMs(jobs)).toBe(60_000);
  });

  it('formats elapsed mm:ss', () => {
    expect(formatElapsed(0)).toBe('0:00');
    expect(formatElapsed(83_000)).toBe('1:23');
  });
});
```

- [ ] **Step 2: Run to verify FAIL** — `npx vitest run src/lib/duration.test.ts` → module not found.

- [ ] **Step 3: Implement**

```ts
// src/lib/duration.ts
export const DEFAULT_TYPICAL_MS = 60_000;

export function medianDurationMs(
  jobs: Array<{ status: string; started_at?: string | null; finished_at: string | null; created_at: string }>,
): number {
  const durations = jobs
    .filter(j => j.status === 'success' && j.started_at && j.finished_at)
    .map(j => new Date(j.finished_at!).getTime() - new Date(j.started_at!).getTime())
    .filter(ms => ms > 0)
    .sort((a, b) => a - b);
  if (durations.length === 0) return DEFAULT_TYPICAL_MS;
  return durations[Math.floor(durations.length / 2)];
}

export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}
```

- [ ] **Step 4: Run to verify PASS** — `npx vitest run src/lib/duration.test.ts` → 3 passed.

- [ ] **Step 5: Lint + commit**

```bash
npm run lint && git add src/lib/duration.ts src/lib/duration.test.ts
git commit -m "feat: typical-duration estimate and elapsed formatter"
```

---

### Task 4: Design tokens + theme hook

**Files:**
- Modify: `src/index.css` (full rewrite)
- Create: `src/hooks/useTheme.ts`

**Interfaces:**
- Produces: CSS custom properties (`--bg, --panel, --ink, --ink-2, --ink-3, --line, --line-soft, --blue, --blue-wash, --green, --green-wash, --amber, --amber-wash, --red, --red-wash`), utility classes `.num`, `.btn`, `.btn-primary`, `.pill`, `.pill--ok/--run/--err/--muted`; hook `useTheme(): { theme: 'light'|'dark'|'system'; setTheme(t): void }` that stamps `data-theme` on `<html>` and persists to `localStorage['itr.theme']`.

- [ ] **Step 1: Rewrite `src/index.css` token base** — replace the existing `:root` block and keep/adapt the rest in later tasks. New base (exact values from mockup v2):

```css
*, *::before, *::after { box-sizing: border-box; }

:root {
  --bg: #F5F6F8; --panel: #FFFFFF;
  --ink: #1A2333; --ink-2: #64748B; --ink-3: #94A3B8;
  --line: #E3E7EE; --line-soft: #EEF1F5;
  --blue: #1E56D6; --blue-wash: #EBF0FC;
  --green: #15803D; --green-wash: #EAF6EE;
  --amber: #B45309; --amber-wash: #FDF3E7;
  --red: #B91C1C; --red-wash: #FBEDEC;
  --radius-sm: 5px; --radius-md: 8px; --radius-lg: 10px;
  --font: "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif;
  --font-num: "Cascadia Mono", Consolas, ui-monospace, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0F141C; --panel: #171E29;
    --ink: #E7EBF2; --ink-2: #93A0B4; --ink-3: #64718A;
    --line: #27303F; --line-soft: #1F2836;
    --blue: #5F8CF0; --blue-wash: #1C2A47;
    --green: #57C282; --green-wash: #17301F;
    --amber: #DCAD52; --amber-wash: #362B14;
    --red: #EF8B84; --red-wash: #3A211F;
  }
}
:root[data-theme="light"] { /* repeat light values verbatim */ }
:root[data-theme="dark"]  { /* repeat dark values verbatim */ }

body { margin: 0; font-family: var(--font); font-size: 12.5px; color: var(--ink); background: var(--bg); }
#root { min-height: 100vh; }
.num { font-family: var(--font-num); font-variant-numeric: tabular-nums; }
:is(button, a, input, [tabindex]):focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; border-radius: 3px; }

.btn { padding: 0.55rem 1rem; border-radius: var(--radius-md); font: 600 12.5px var(--font); cursor: pointer;
  border: 1px solid var(--line); background: var(--panel); color: var(--ink); }
.btn-primary { background: var(--blue); border-color: var(--blue); color: #fff; }
.btn:disabled { opacity: 0.45; cursor: not-allowed; }

.pill { font-size: 9.5px; font-weight: 700; letter-spacing: 0.04em; padding: 1.5px 7px; border-radius: 999px; }
.pill--ok { color: var(--green); background: var(--green-wash); }
.pill--run { color: var(--amber); background: var(--amber-wash); }
.pill--err { color: var(--red); background: var(--red-wash); }
.pill--muted { color: var(--ink-2); background: var(--line-soft); }
```

(The `[data-theme]` blocks must copy the same custom-property lists — data-theme wins over the media query in both directions.) Keep `.login-gate`/`.login-card` styles (re-tokenized: replace hardcoded grays with the vars) so login still renders before later tasks.

- [ ] **Step 2: Create `src/hooks/useTheme.ts`**

```ts
import { useEffect, useState } from 'react';

export type ThemePref = 'light' | 'dark' | 'system';
const KEY = 'itr.theme';

export function useTheme() {
  const [theme, setThemeState] = useState<ThemePref>(() => {
    const saved = localStorage.getItem(KEY);
    return saved === 'light' || saved === 'dark' ? saved : 'system';
  });

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);
    localStorage.setItem(KEY, theme);
  }, [theme]);

  return { theme, setTheme: setThemeState };
}
```

- [ ] **Step 3: Verify** — `npm run lint && npm run build` → PASS; `npm run dev`, open app: login screen renders with new tokens in both OS themes.

- [ ] **Step 4: Commit**

```bash
git add src/index.css src/hooks/useTheme.ts
git commit -m "feat: workbench design tokens with light/dark themes"
```

---

### Task 5: App shell — TopBar + Stepper + 3-pane grid

**Files:**
- Create: `src/components/TopBar.tsx`
- Modify: `src/App.tsx` (restructure `AuthenticatedApp` + `LoginGate` logo)
- Modify: `src/index.css` (append shell styles)

**Interfaces:**
- Consumes: `useJobs()` (unchanged), `isSent(jobId)` from Task 2.
- Produces:

```tsx
// TopBar.tsx
export type StepStage = 'upload' | 'extract' | 'review' | 'send';
export function TopBar(props: {
  userName: string;
  stage: StepStage | null;          // null = no job selected
  extractSeconds: number | null;    // finished job: (finished_at - started_at)/1000
  counts: { today: number; queue: number; review: number };
  onSignOut: () => void;
  theme: 'light' | 'dark' | 'system';
  onToggleTheme: () => void;        // cycles light → dark → system
}): JSX.Element;
```

- App layout becomes: `<div class="shell"><TopBar/><div class="cols"> {queue} {work} {verify} </div></div>`; CSS grid `.cols { display:grid; grid-template-columns: 252px 1fr 336px; }` with `@media (max-width:1100px){ grid-template-columns: 220px 1fr; }` (VerifyPane hidden behind a toggle button — Task 8).
- Stage derivation (in `App.tsx`): job `pending|processing` → `'extract'`; `success` and `!isSent(id)` → `'review'`; `success` and sent → `'send'`; no selection → `null` (stepper shows step 1 active).
- `counts`: `today` = jobs with `created_at` on the local calendar day; `queue` = status pending/processing; `review` = success && !isSent.
- Brand block: inline SVG glyph (24×24 rounded square, "T" knockout — copy shape from mockup `.c-brand .glyph`), name "ITR Extract". **Also in this task:** replace the wikimedia `<img>` in `LoginGate` with a 16×16 inline SVG of the Microsoft logo (four 7×7 rects: `#F25022 #7FBA00 #00A4EF #FFB900`).

- [ ] **Step 1: Write `TopBar.tsx`** — stepper markup: four `.step` spans with classes `done/cur` per stage order; stats right-aligned `.stat` blocks (`.k` label, `.v num` value); theme button showing `☾/☀/⟳` per pref; sign-out uses existing handler.
- [ ] **Step 2: Restructure `App.tsx`** — keep all existing handlers (`handleLogout`, polling effect, create/reprocess/delete); replace the old `app-shell/sidebar/main/header` JSX with the new shell; pass placeholder panes for now (`<div className="pane-queue">…old JobHistory…</div>` etc. is acceptable within this task only if the app still runs; final swap happens in Tasks 6–8).
- [ ] **Step 3: Append shell CSS** to `src/index.css` — `.shell { min-height:100vh; display:flex; flex-direction:column; }`, `.topbar { height:52px; display:flex; align-items:center; gap:18px; padding:0 18px; background:var(--panel); border-bottom:1px solid var(--line); }`, stepper/step styles from mockup (`.step .n` circle, `.done/.cur` variants), `.cols { flex:1; display:grid; grid-template-columns:252px 1fr 336px; min-height:0; }`.
- [ ] **Step 4: Verify** — `npm run lint && npm run build`; `npm run dev`: login → app shows top bar with stepper + stats and 3 columns (old components inside temporarily).
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: workbench shell with top bar, stepper and 3-pane grid"`

---

### Task 6: QueuePane (groups/search/filter/footer) + multi-file UploadStrip

**Files:**
- Create: `src/components/QueuePane.tsx`
- Modify: `src/App.tsx` (mount QueuePane; multi-upload handler)
- Modify: `src/index.css` (append queue styles)
- Delete usage of: `src/components/JobHistory.tsx`, `src/components/UploadCard.tsx` (files removed in Task 10)

**Interfaces:**
- Consumes: `JobSummary[]`, `isSent` (Task 2), `JobStatusBadge` replaced by `.pill` classes.
- Produces:

```tsx
export function QueuePane(props: {
  jobs: JobSummary[];
  selectedJobId: string | null;
  onSelect: (id: string) => void;
  onReprocess: (id: string) => Promise<void> | void;
  onDelete: (id: string) => Promise<void> | void;
  onUploadFiles: (files: File[]) => Promise<void>;   // validates + sequential POST in App
}): JSX.Element;
```

- UploadStrip at top: dashed drop area, `<input type="file" accept="application/pdf" multiple hidden>`; on drop/select call `onUploadFiles([...files].slice(0, 5))`; copy "Drop PDFs here · up to 5 files · 50 MB each" (use `MAX_FILE_SIZE_BYTES`).
- `onUploadFiles` in `App.tsx`: validate each file (same rules as old UploadCard: `.pdf`, size ≤ max — reuse the messages verbatim), then `for (const f of valid) { const r = await createJob(f); setSelected(r.job_id); }` sequential; per-file failures → `toast.show(...)`, continue with next file.
- Filters: chips `All / Review / Sent / Failed` (counts derived; Review = success && !sent; Sent = success && sent); search input filters `original_filename` case-insensitive.
- Grouping: `Today / Yesterday / <dd MMM>` by `created_at` local date.
- Row: filename (ellipsis, `title` attr), pill (`DONE/SENT/RUN/QUEUED/FAILED` — RUN shows `· {elapsed}` using `formatElapsed(now - started_at)` ticking via 1s interval only while any job is active), time `HH:mm`, hover-independent kebab: keep simple — delete `×` button always visible at 40% opacity (1.0 on hover/focus), reprocess link on failed rows (existing behavior).
- Footer: `History {jobs.length} / {MAX_SESSIONS_PER_USER}` + 7 mini bars (jobs-per-day counts for last 7 days from list, bar height 4–30px scaled to max; accent `var(--blue)`).
- Delete confirm: keep `window.confirm` (spec YAGNI decision).

- [ ] **Step 1: Implement `QueuePane.tsx`** per interface above (pure presentational + local `search`/`filter` state; grouping helper inside file).
- [ ] **Step 2: Wire in `App.tsx`**, remove `<UploadCard>` and `<JobHistory>` imports/JSX.
- [ ] **Step 3: Append queue CSS** — port `.c-drop/.c-qfilters/.c-group/.c-job/.c-pill/.c-qfoot/.c-bars` blocks from the mockup into token-based equivalents (`.q-*` prefix, values unchanged).
- [ ] **Step 4: Verify** — dev server: upload 2–3 PDFs at once → sequential jobs appear; search + filters + groups work; delete/reprocess still work.
- [ ] **Step 5: Commit** — `git commit -am "feat: queue pane with grouping, search, filters and multi-file upload"`

---

### Task 7: WorkPane — client header, tabs, e-consent cards, email editor

**Files:**
- Create: `src/components/WorkPane.tsx`
- Modify: `src/App.tsx` (mount; lift `highlightAmount` state)
- Modify: `src/index.css` (append work styles)
- Delete usage of: `src/components/JobDetailView.tsx` (file removed in Task 10)

**Interfaces:**
- Consumes: `JobDetail`, existing `apiFetch`, `sanitizeEmailHtml` logic (move verbatim from JobDetailView), `extractPagesFromBuffer` (move verbatim), `useToast`, `useAccessToken`.
- Produces:

```tsx
export function WorkPane(props: {
  job: JobDetail;
  highlightAmount: string | null;                 // from VerifyPane hover — wraps matching text in <mark>
  onEconsentChange: (b64: string | null) => void; // App passes b64 to VerifyPane send block
  getEmailHtml: () => string;                     // ref-backed accessor for current edited HTML
}): JSX.Element;
```

Implementation notes (all logic already exists in `JobDetailView.tsx` — move, don't rewrite: form toggle → re-extract via pdf-lib, econsent fetch on mount, email localStorage draft persistence with key `itr.email_edit.{job_id}`):

- ClientHeader: `h3` client name; chips return_type / `TY {tax_year}` / jurisdictions (`Federal` if federal_sentence + each `state_name`); meta `processed in {seconds}s` from timestamps; page count chip ONLY if input buffer already cached (`inputBufferRef.current`), computed via `PDFDocument.load(...).getPageCount()`.
- Tabs (`Client email` default / `E-consent (n)` / `Extracted JSON`): local state; JSON tab renders `<pre className="json num">{JSON.stringify(job.analysis_data, null, 2)}</pre>` inside `overflow:auto` container.
- E-consent tab: cards per form (page badge `p.{first}`, form_number + title, jurisdiction, include-checkbox) — same selection logic as before; footer line `Econsent.pdf · {pages} pages` + Download button (moved from old view; disabled while re-extracting).
- Email tab: toolbar `B / I / ⟲ Undo` via `document.execCommand('bold'|'italic'|'undo')` guarded by `document.queryCommandSupported?.('bold')` (hide toolbar if unsupported); "Saved {HH:mm} · Reset" chip — Reset removes `itr.email_edit.{job_id}` and re-renders `job.email_html`; saved time updates on blur-save (existing handler).
- Cross-highlight effect: when `highlightAmount` changes, walk `emailRef.current` text nodes, wrap first case-sensitive occurrence of the string in `<mark class="hl">`; remove previous mark first; null → remove only. (Plain DOM in `useEffect`; no dependency on sanitizer since content is already sanitized.)

- [ ] **Step 1: Implement `WorkPane.tsx`** (move logic from JobDetailView; keep `DraftState` OUT — send moves to VerifyPane in Task 8).
- [ ] **Step 2: Wire in `App.tsx`**: render for `job?.status === SUCCESS`; hold `const emailHtmlRef = useRef<() => string>(() => '')` pattern or lift via callback prop; hold `econsentB64` state here (needed by VerifyPane).
- [ ] **Step 3: Append work CSS** (`.w-*` classes: header, chips, tabs, form cards, email card + toolbar, `.hl { background:#FFF3C4; box-shadow:0 0 0 1.5px #F5D66E; border-radius:2px; }` with dark-theme override `#4a3f14/#8a6d1f`).
- [ ] **Step 4: Verify** — dev: tabs switch; form toggle re-extracts; email edit persists + Reset works; JSON tab scrolls; build + lint pass.
- [ ] **Step 5: Commit** — `git commit -am "feat: work pane with tabs, e-consent cards and email editor toolbar"`

---

### Task 8: VerifyPane — checklist + send block + hotkeys

**Files:**
- Create: `src/components/VerifyPane.tsx`
- Modify: `src/App.tsx` (mount; `highlightAmount` state; `markSent` on draft success; <1100px bottom-sheet toggle)
- Modify: `src/index.css` (append verify styles + bottom-sheet media query)

**Interfaces:**
- Consumes: `buildVerifyItems` (Task 1), `getVerifySet/toggleVerify/markSent` (Task 2), `createOutlookDraft(instance, toEmail, subject, html, econsentB64, fileName)` from `src/lib/graphApi.ts` (existing signature — moved call from old JobDetailView), `useMsal`, `useToast`.
- Produces:

```tsx
export function VerifyPane(props: {
  job: JobDetail;
  econsentB64: string | null;
  econsentPageCount: number;
  getEmailHtml: () => string;
  onHighlight: (amountRaw: string | null) => void;
  onDraftCreated: () => void;      // App: markSent(job.job_id) + refresh queue pills
}): JSX.Element;
```

Behavior:

- Items = `buildVerifyItems(job.analysis_data)`; ticked = `getVerifySet(job.job_id)` in state; header `Verify extracted figures {ticked}/{total}` + progress bar (`width = ticked/total*100%`, green gradient).
- Item row: checkbox (`role="checkbox"` on a real `<button>`), label + sublabel, amount right-aligned (`.num`, due → red with parentheses `($12,450)`, refund → green, null amount → render `sourceSentence` italic small instead); date small under amount; link `letter (PDF)` → opens `GET /api/jobs/{id}/input.pdf` blob in new tab (fetch via `apiFetch`, `URL.createObjectURL`, `window.open`).
- `onMouseEnter/onFocus` row → `onHighlight(item.amountRaw)`; leave/blur → `onHighlight(null)`.
- Keyboard: `useEffect` window keydown — ignore when `(e.target as HTMLElement).closest('input,textarea,[contenteditable="true"]')`; `j/k` move `focusIndex` (scrollIntoView), `v` toggles focused item, `e` focuses the email editor (`document.querySelector<HTMLElement>('.w-emailbody')?.focus()`).
- SendBlock (bottom): `To` email input, attachment summary line `Econsent.pdf · {econsentPageCount} pages` (or `No forms selected — nothing will be attached` in amber), **always-enabled** `Create Outlook Draft` button (disabled only while `creating` or empty To — same as current app); on success: link "Open draft in Outlook" + call `onDraftCreated()`; unchecked reminder: if `ticked < total` show `"{n} figures still unchecked — sending is never blocked"` (amber, informational only).
- Subject construction stays: `` `${taxYear} Income Tax Return — ${clientName}` ``.
- Download Econsent button stays in WorkPane (Task 7); VerifyPane only sends.
- <1100px: `.cols` drops to 2 columns; VerifyPane renders as fixed bottom-sheet with a toggle button `Review ({ticked}/{total})` pinned bottom-right.

- [ ] **Step 1: Implement `VerifyPane.tsx`** per above (single file; helper `AmountCell` inside).
- [ ] **Step 2: Wire `App.tsx`** — state `highlightAmount`, `econsentB64`, `econsentPageCount`; `onDraftCreated` = `markSent(job.job_id)` + `refresh()`.
- [ ] **Step 3: Append verify CSS** (`.v-*` classes ported from mockup: header, progress, items, focus row `box-shadow: inset 3px 0 0 var(--blue)`, send block, kbd hint row `J/K next · V verify · E edit email`).
- [ ] **Step 4: Verify manually** — tick persists across reload; hover highlights amount in email; J/K/V/E work and stay dead while typing in inputs; draft creation marks job SENT in queue + stepper jumps to Send; button never blocked by ticks.
- [ ] **Step 5: Run all tests + build** — `npm test && npm run lint && npm run build` → all pass.
- [ ] **Step 6: Commit** — `git commit -am "feat: verify checklist pane with cross-highlight, hotkeys and send block"`

---

### Task 9: ProcessingCard + failed state

**Files:**
- Create: `src/components/ProcessingCard.tsx`
- Modify: `src/App.tsx` (render for active statuses; keep `timedOut` refresh logic)
- Modify: `src/index.css` (append processing styles)

**Interfaces:**
- Consumes: `medianDurationMs`, `formatElapsed`, `DEFAULT_TYPICAL_MS` (Task 3); `useJobPolling`'s `timedOut` (existing).
- Produces:

```tsx
export function ProcessingCard(props: {
  job: JobDetail;                 // status pending|processing
  jobs: JobSummary[];             // for typical estimate
  timedOut: boolean;
  onRefresh: () => void;          // existing pollingKey bump
}): JSX.Element;
```

- 1s `setInterval` tick; `elapsed = now - (started_at ?? created_at)`; `typical = medianDurationMs(jobs)`; bar `width = min(elapsed/typical, 0.95)*100%`; header `PROCESSING {filename}` + `elapsed {formatElapsed(elapsed)} · typical ~{Math.round(typical/1000)}s`; single lane copy `Task 1 + Task 2 running in parallel — e-consent detection · cover letter extraction`; skeleton block `Verification checklist will appear here…` (4 shimmer bars).
- If `elapsed > 2 * typical` or `timedOut`: amber line `Taking longer than usual — still working` + `Refresh to check` button (`onRefresh`).
- FAILED state stays in `App.tsx` as today (red message + reprocess available in queue), restyled with `.pill--err` colors.

- [ ] **Step 1: Implement `ProcessingCard.tsx`** + wire into `App.tsx` (replace the old inline pending/timedOut JSX).
- [ ] **Step 2: Append CSS** (`.p-*` classes: card, spinner, bar, skeleton shimmer under `prefers-reduced-motion` guard).
- [ ] **Step 3: Verify** — upload a real PDF: card shows ticking elapsed and honest bar; on success it swaps to Work+Verify panes; build + lint pass.
- [ ] **Step 4: Commit** — `git commit -am "feat: honest elapsed-based processing card"`

---

### Task 10: Cleanup, dead-code removal, acceptance pass

**Files:**
- Delete: `src/components/JobHistory.tsx`, `src/components/UploadCard.tsx`, `src/components/JobDetailView.tsx`, `src/components/JobStatusBadge.tsx` (fully replaced; delete only after grep shows zero imports)
- Modify: `src/App.css` (already empty placeholder — delete file + its import if any), `index.html` (page `<title>` → `ITR Extract — Workbench`)

- [ ] **Step 1: Grep for dead imports**

```bash
grep -rn "JobHistory\|UploadCard\|JobDetailView\|JobStatusBadge\|App.css" src/
```
Expected: no matches outside the files being deleted. Delete the files.

- [ ] **Step 2: Full verification suite**

```bash
npm test && npm run lint && npm run build
```
Expected: all green.

- [ ] **Step 3: Acceptance walkthrough (manual, dev server against local backend)** — check every item in spec §10:
  1. success job → checklist complete, unparseable sentences shown raw; 2. ticks survive reload, send never blocked, amber reminder shows; 3. processing bar honest + late warning; 4. 3-file upload sequential, no 429; 5. search/filter/groups/delete/reprocess OK; 6. email edit/Reset/draft OK; 7. dark/light + toggle OK, focus states visible; 8. no new runtime deps in `package.json`.

- [ ] **Step 4: Final commit**

```bash
git add -A && git commit -m "feat: workbench phase 1 — cleanup and acceptance pass"
```

---

## Self-Review Notes

- **Spec coverage:** §3 shell→T5, queue/upload→T6, work pane→T7, verify/send/hotkeys→T8, processing→T9, §5 parser→T1, verify state→T2, §6 duration→T3, §7 tokens/dark→T4, cleanup/a11y copy→T5+T10. Gaps: none found.
- **Types:** `VerifyItem`, `KVStore`, `StepStage`, pane prop contracts declared once in Interfaces blocks and reused by name in later tasks — names match.
- **No gating anywhere** (Mức 2) and **no invented %** — consistent with spec Global Constraints.
