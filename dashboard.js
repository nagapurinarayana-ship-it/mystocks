const money = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(Number(value));
};

const number = (value, digits = 2) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toLocaleString('en-IN', { maximumFractionDigits: digits });
};

const crore = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return `₹${(Number(value) / 10000000).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`;
};

const pct = (value, fraction = false) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  const n = Number(value) * (fraction ? 100 : 1);
  return `${n.toFixed(2)}%`;
};

const esc = (value) => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

function sparkline(values) {
  const clean = (values || []).map(Number).filter(Number.isFinite);
  if (clean.length < 2) return '<div class="spark-wrap"></div>';
  const width = 600, height = 80, pad = 7;
  const min = Math.min(...clean), max = Math.max(...clean);
  const span = max - min || 1;
  const pts = clean.map((v, i) => {
    const x = pad + (i / (clean.length - 1)) * (width - pad * 2);
    const y = height - pad - ((v - min) / span) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const positive = clean.at(-1) >= clean[0];
  const stroke = positive ? '#51d88a' : '#ff7a86';
  return `<div class="spark-wrap"><svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="Recent price trend"><polyline fill="none" stroke="${stroke}" stroke-width="3" vector-effect="non-scaling-stroke" points="${pts}"/></svg></div>`;
}

function list(items) {
  return `<ul>${(items || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
}

function renderDailyPick(data) {
  const regime = data.market_regime || {};
  const generated = data.generated_at
    ? new Date(data.generated_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })
    : 'unknown';

  if (data.status !== 'PICK' || !data.pick) {
    return `
      <div class="no-trade-card">
        <div class="pick-status-row">
          <span class="pick-status no-trade">NO TRADE</span>
          <span class="pick-date">For ${esc(data.for_date || '')}</span>
        </div>
        <h3>No stock is being forced today.</h3>
        <p>${esc(data.reason || 'No setup passed the research filters.')}</p>
        <div class="pick-meta">Nifty regime: <strong>${esc(regime.label || 'Unavailable')}</strong> · Generated ${esc(generated)} IST</div>
      </div>`;
  }

  const p = data.pick;
  return `
    <div class="pick-card">
      <div class="pick-status-row">
        <span class="pick-status active">TODAY'S PICK</span>
        <span class="pick-date">For ${esc(data.for_date || '')}</span>
      </div>
      <div class="pick-head">
        <div>
          <div class="pick-symbol">${esc(p.display_symbol)}</div>
          <div class="pick-sub">Nifty regime: ${esc(regime.label || 'Unavailable')} · up to ${esc(data.max_hold_days)} sessions</div>
        </div>
        <div class="pick-reference"><span>Reference close</span><strong>${money(p.reference_close)}</strong></div>
      </div>

      <div class="pick-levels">
        <div><span>Acceptable open</span><strong>${money(p.acceptable_open_low)} – ${money(p.acceptable_open_high)}</strong></div>
        <div><span>Reference target</span><strong>${money(p.reference_target)}</strong><small>+${number(Number(data.target_pct) * 100)}%</small></div>
        <div><span>Reference stop</span><strong>${money(p.reference_stop)}</strong><small>-${number(Number(data.stop_pct) * 100)}%</small></div>
        <div><span>Historical win rate</span><strong>${number(p.historical_win_rate, 1)}%</strong><small>95% lower bound ${number(p.lower95_win_rate, 1)}%</small></div>
        <div><span>Samples</span><strong>${number(p.samples, 0)}</strong><small>resolved historical setups</small></div>
        <div><span>Expected value</span><strong>${number(p.expected_value_pct)}%</strong><small>after configured costs</small></div>
      </div>

      <div class="pick-rule"><strong>Execution rule:</strong> ${esc(p.execution_rule)}</div>
      <div class="pick-rule"><strong>After entry:</strong> ${esc(p.target_rule)} · ${esc(p.stop_rule)}</div>

      <div class="pick-reasons">
        <h4>Why the model selected it</h4>
        ${list(p.reasons)}
      </div>

      <div class="pick-stats">RSI ${number(p.rsi14, 1)} · Volume ${number(p.volume_ratio)}× 20D avg · 5D ${number(p.return_5d_pct)}% · 20D ${number(p.return_20d_pct)}%${p.breakout20 ? ' · 20-session breakout' : ''}</div>
      <div class="pick-meta">Generated ${esc(generated)} IST · ${esc(data.disclaimer || '')}</div>
    </div>`;
}

async function loadDailyPick() {
  const target = document.getElementById('daily-pick');
  if (!target) return;
  try {
    const res = await fetch(`daily-pick.json?v=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    target.innerHTML = renderDailyPick(data);
  } catch (err) {
    target.innerHTML = '<div class="no-trade-card"><span class="pick-status pending">AWAITING FIRST RUN</span><h3>Pre-market pick is not generated yet.</h3><p>The scheduled workflow will populate this section before the next NSE trading session.</p></div>';
  }
}

function renderSummary(stock) {
  const m = stock.market || {};
  const change = Number(m.change_pct);
  const cls = Number.isFinite(change) ? (change > 0 ? 'up' : change < 0 ? 'down' : 'flat') : 'flat';
  const changeText = Number.isFinite(change) ? `${change > 0 ? '+' : ''}${change.toFixed(2)}%` : 'awaiting refresh';
  return `
    <article class="summary-card">
      <div class="summary-top">
        <div><div class="rank">#${esc(stock.research_rank)} · ${esc(stock.exchange)}</div><h3>${esc(stock.name)}</h3></div>
        <span class="score-pill">${esc(stock.research_score)}/10</span>
      </div>
      <div class="price">${money(m.price)}</div>
      <div class="change ${cls}">${esc(changeText)}</div>
    </article>`;
}

function renderStock(stock) {
  const m = stock.market || {};
  const links = (stock.official_links || []).map(([label, url]) => `<a class="link-chip" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`).join('');
  const flags = (stock.live_flags || []).length
    ? `<div class="flags">${stock.live_flags.map(f => `<div class="flag">⚠ ${esc(f)}</div>`).join('')}</div>`
    : '<div class="no-flags">✓ No mechanical live-feed warning triggered. Filing-based checks still apply.</div>';
  const quality = m.data_quality_warning
    ? `<div class="flag">⚠ ${esc(m.data_quality_warning)}</div>`
    : '';
  const news = (stock.news || []).length
    ? stock.news.map(item => `<div class="news-item"><a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a><div class="news-meta">${esc(item.source || '')}${item.published ? ` · ${esc(item.published)}` : ''}</div></div>`).join('')
    : '<div class="stock-sub">No secondary-feed headlines available in this snapshot.</div>';

  return `
    <article class="stock-card">
      <div class="stock-head">
        <div>
          <div class="eyebrow">#${esc(stock.research_rank)} · ${esc(stock.exchange_symbol)}</div>
          <h2>${esc(stock.name)}</h2>
          <div class="stock-sub">Manual review ${esc(stock.review_as_of)} · research score ${esc(stock.research_score)}/10</div>
        </div>
        <span class="badge">${esc(stock.exchange)}</span>
      </div>

      <div class="metrics">
        <div class="metric"><span>Price</span><strong>${money(m.price)}</strong></div>
        <div class="metric"><span>Market cap</span><strong>${crore(m.market_cap)}</strong></div>
        <div class="metric"><span>P/E</span><strong>${number(m.trailing_pe)}</strong></div>
        <div class="metric"><span>P/B</span><strong>${number(m.price_to_book)}</strong></div>
        <div class="metric"><span>ROE</span><strong>${pct(m.return_on_equity, true)}</strong></div>
        <div class="metric"><span>Debt / equity</span><strong>${pct(m.debt_to_equity_pct)}</strong></div>
      </div>

      ${sparkline(stock.price_history)}

      <div class="detail-grid">
        <div class="detail-box"><h4>Why it is here</h4>${list(stock.thesis)}</div>
        <div class="detail-box risk"><h4>What can go wrong</h4>${list(stock.risks)}</div>
        <div class="detail-box kill"><h4>Thesis breakers</h4>${list(stock.kill_switches)}</div>
      </div>

      ${quality}
      ${flags}
      <div class="link-row">${links}</div>

      <div class="news">
        <div class="news-title">Latest secondary-feed headlines — verify material claims in filings</div>
        <div class="news-list">${news}</div>
      </div>
    </article>`;
}

async function boot() {
  loadDailyPick();

  const dot = document.getElementById('data-status');
  const label = document.getElementById('updated-label');
  const time = document.getElementById('updated-time');
  const summary = document.getElementById('summary-cards');
  const watchlist = document.getElementById('watchlist');

  try {
    const res = await fetch(`dashboard-data.json?v=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const stocks = Array.isArray(data.stocks) ? data.stocks : [];
    if (!stocks.length) throw new Error('No watchlist data');

    summary.innerHTML = stocks.map(renderSummary).join('');
    watchlist.innerHTML = stocks.map(renderStock).join('');
    dot.classList.add('ok');
    label.textContent = data.market_data_status === 'live-refresh' ? 'Research snapshot loaded' : 'Dashboard loaded';
    time.textContent = data.generated_at ? `Updated ${new Date(data.generated_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })} IST` : 'Refresh timestamp unavailable';
  } catch (err) {
    dot.classList.add('error');
    label.textContent = 'Dashboard data unavailable';
    time.textContent = String(err.message || err);
    summary.innerHTML = '';
    watchlist.innerHTML = '<div class="error-box">The site shell is working, but the research snapshot could not be loaded. Check the latest GitHub Actions dashboard-refresh run.</div>';
  }
}

document.addEventListener('DOMContentLoaded', boot);
