const fs = require('fs');
const D = '/tmp/claude-1000/-home-bigfish6-workspace-pgxnl/6a171c4f-7f6f-472c-b0b1-22ebca19ba81/scratchpad';
const src = fs.readFileSync(D + '/ui.js', 'utf8');
globalThis.esc = t => String(t);

for (const name of ['RULE_TYPE_HINT', 'CANON_KIND_LABEL', 'AG_KIND_LABEL']) {
  const m = src.match(new RegExp('const ' + name + '=[\\s\\S]*?\\n};'));
  if (!m) { console.error('못 찾음:', name); process.exit(1); }
  eval(m[0].replace('const ', 'globalThis.'));
}
const bg = src.match(/const BUILTIN_GUARDS=\[[\s\S]*?\n\];/);
if (!bg) { console.error('못 찾음: BUILTIN_GUARDS'); process.exit(1); }
eval(bg[0].replace('const ', 'globalThis.'));

for (const name of ['_fewShotSummary','_advisoryGuardSummary','_canonSummary','_rewriteSummary','_builtinGuardRows']) {
  const m = src.match(new RegExp('function ' + name + '\\([^)]*\\)\\{[\\s\\S]*?\\n\\}'));
  if (!m) { console.error('못 찾음:', name); process.exit(1); }
  eval('globalThis.' + name + ' = ' + m[0]);
}
const bodyMatch = src.match(/  \/\/ 파이프라인 순서로 묶는다[\s\S]*?\$\('ruleBody'\)\.innerHTML=html;/);
if (!bodyMatch) { console.error('못 찾음: 렌더 본문'); process.exit(1); }
const body = bodyMatch[0].replace("$('ruleBody').innerHTML=html;", 'return html;');

const rules = JSON.parse(fs.readFileSync(D + '/rules.json', 'utf8')).rules;
const html = new Function('rules', body)(rules);
console.log(html
  .replace(/<tr[^>]*>/g, '\n')
  .replace(/<\/td>\s*<td[^>]*>/g, '  |  ')
  .replace(/<[^>]+>/g, '')
  .replace(/\n{2,}/g, '\n')
  .split('\n').map(l => l.trim()).filter(Boolean).join('\n'));
