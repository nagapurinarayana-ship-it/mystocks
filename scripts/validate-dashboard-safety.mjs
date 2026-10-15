import { readFile } from 'node:fs/promises';

const dashboard = await readFile('dashboard.js', 'utf8');
const required = [
  ['stale review helper', 'function staleReviewWarning(reviewDate)'],
  ['30-day review threshold', 'ageDays > 30'],
  ['filing verification warning', 'Re-check the latest NSE/company filings before relying on this thesis.'],
  ['missing review-date warning', 'Manual research review date unavailable'],
  ['visible warning render', '${reviewWarning}'],
];
const missing = required.filter(([, marker]) => !dashboard.includes(marker));
if (missing.length) {
  throw new Error(`Dashboard safety checks failed: ${missing.map(([name]) => name).join(', ')}`);
}
console.log('Dashboard research-freshness safeguards verified.');
