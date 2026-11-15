// 前端冒烟测试（8.2）：把 2026-10 修复轮次中的人工验证固化为可重复执行。
// 运行前提（一次性）：
//   cd web && npm install && npx playwright install chromium
//   服务已启动：  .venv/Scripts/python.exe app.py   （默认 127.0.0.1:8000）
//   npm run test:e2e
// 无模型配置也可运行：等待节点卡片通过注入 mock 状态渲染（与后端契约测试互为补充）。
import { chromium } from 'playwright';

const BASE = process.env.BASE_URL || 'http://127.0.0.1:8000';
const results = [];
const check = (name, ok, detail = '') =>
  results.push({ name, ok, detail }) && console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);

const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto(`${BASE}/#/chat`);
  await page.waitForLoadState('load');

  // 1) 页面加载无 JS 错误
  check('页面无 JS 错误', errors.length === 0, errors.join(' | '));

  // 2) ARIA 语义（5.1/5.5/5.6）
  check('对话流不是 live region', (await page.getAttribute('#chat-log', 'aria-live')) === null);
  check('专用播报区存在', (await page.getAttribute('#live-status', 'role')) === 'status');
  check('输入框 combobox 语义', (await page.getAttribute('#question', 'role')) === 'combobox');
  check('补全浮层 listbox 语义', (await page.getAttribute('#composer-suggest', 'role')) === 'listbox');
  check('分隔条 separator 语义', (await page.getAttribute('#result-divider', 'role')) === 'separator');

  // 3) 补全：@ 展开 → aria-expanded 同步；无命中不出现空浮层（9.1）
  await page.fill('#question', '@');
  check('输入 @ 展开 listbox', (await page.getAttribute('#question', 'aria-expanded')) === 'true');
  await page.fill('#question', '@zzz');
  check('无命中时空浮层隐藏', await page.isHidden('#composer-suggest'));

  // 4) 进度卡原地更新（7.1）：节点保持、文本切换
  const progress = await page.evaluate(() => {
    openResultSplit();
    renderProgressCard('planning');
    const el = document.querySelector('[data-progress-phase]');
    const same = (() => { renderProgressCard('writing'); return document.querySelector('[data-progress-phase]') === el; })();
    return { same, text: el.textContent };
  });
  check('进度卡只更新文本', progress.same === true && progress.text === '整理研究报告', JSON.stringify(progress));

  // 5) 澄清卡：渲染后焦点移入标题 + 播报（5.3）
  const clarify = await page.evaluate(() => new Promise((resolve) => {
    renderClarifyCard({ clarify_questions: [{ field: 'topic', question: '测试问题' }], clarifications: [] });
    setTimeout(() => resolve({
      focused: document.activeElement === document.querySelector('#result-view h1'),
      live: document.querySelector('#live-status').textContent,
    }), 120);
  }));
  check('澄清卡焦点移入', clarify.focused === true);
  check('澄清卡读屏播报', clarify.live.includes('补充研究问题'), clarify.live);

  // 6) 大纲卡：确认按钮走真实 POST，错误反馈内联展示
  await page.evaluate(() => {
    deepJobUrl = '/api/agent/report/smoke-nonexistent';
    renderOutlineCard({ regenerates: 0, outline: { outline: [{ order: 1, question: '各议题负向占比排序', aspect: null, requires_evidence: false }] } });
  });
  await page.click('[data-outline-confirm]');
  await page.waitForTimeout(800);
  const outlineError = await page.textContent('.deep-action-error').catch(() => '');
  check('大纲确认错误内联反馈', Boolean(outlineError && outlineError.trim().length > 0), outlineError || '');

  // 7) 失败视图给出针对性指导（P1-3）
  const failure = await page.evaluate(() => {
    deepFailureView({ error: { error: 'GraphRecursionError: 执行超时（>20s）' } }, null);
    return document.querySelector('#result-view .warning')?.textContent || '';
  });
  check('失败视图按类型给建议', failure.includes('聚焦'), failure);

  // 8) 划词笔记 dialog：焦点移入（5.4）
  const dialog = await page.evaluate(() => {
    openQuotesPanel();
    const moved = document.activeElement?.id === 'quotes-close';
    closeQuotesPanel();
    return moved;
  });
  check('dialog 焦点移入', dialog === true);

  if (results.some((r) => !r.ok)) process.exitCode = 1;
  console.log(`\n${results.filter((r) => r.ok).length}/${results.length} 通过`);
} finally {
  await browser.close();
}
