import { readFile } from 'node:fs/promises';

const dashboard = await readFile('dashboard.js', 'utf8');
const generator = await readFile('scripts/generate_dashboard_data.py', 'utf8');
const required = [
  ['stale review helper', 'function staleReviewWarning(reviewDate)'],
  ['snapshot staleness helper', 'function snapshotAgeHours(generatedAt)'],
  ['18-hour snapshot freshness threshold', 'ageHours > 18'],
  ['visible stale snapshot warning', 'Market snapshot may be stale'],
  ['stale snapshot verification guidance', 'Refresh delayed; verify live quotes and exchange filings.'],
  ['missing quote warning', 'Market quotes unavailable'],
  ['partial quote warning', 'Partial market data'],
  ['available quote count', 'const quoteCount = stocks.filter(stock => {'],
  ['30-day review threshold', 'ageDays > 30'],
  ['filing verification warning', 'Re-check the latest NSE/company filings before relying on this thesis.'],
  ['missing review-date warning', 'Manual research review date unavailable'],
  ['visible warning render', '${reviewWarning}'],
];
const missing = required.filter(([, marker]) => !dashboard.includes(marker));

const generatorRequired = [
  ['quote coverage classifier', 'def classify_market_data_status(stocks: list[dict])'],
  ['partial snapshot status', '"partial-refresh"'],
  ['unavailable snapshot status', '"unavailable"'],
  ['available quote count in output', '"available_quote_count": available_quotes'],
  ['watchlist size in output', '"watchlist_size": len(stocks)'],
]
const missingGenerator = generatorRequired.filter(([, marker]) => !generator.includes(marker))
if (missingGenerator.length) {
  throw new Error('Dashboard generator safety checks failed: ' + missingGenerator.map(([name]) => name).join(', '))
}
if (missing.length) {
  throw new Error(`Dashboard safety checks failed: ${missing.map(([name]) => name).join(', ')}`);
}
console.log('Dashboard research-freshness safeguards verified.');
