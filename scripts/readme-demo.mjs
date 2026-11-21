#!/usr/bin/env node
/** Read-only synthetic API + built SPA for documentation screenshots. Not an app runtime. */
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve, extname, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../frontend/build/client');
const port = Number(process.env.DEMO_PORT || 18000);
const company = { id: 1, name: 'Musterwerk GmbH (Demo)', folder: 'Musterwerk-GmbH', recipients: ['kanzlei@example.test'] };
const accounts = [{ id: 1, kind: 'bank', name: 'Geschäftskonto (Demo)', identifier: 'DEMO-KONTO' }, { id: 2, kind: 'depot', name: 'Geschäftsdepot (Demo)', identifier: 'DEMO-DEPOT' }];
const categories = [{ id: 1, name: 'Büro' }, { id: 2, name: 'Dienstleistung' }];
// All names, amounts, document bytes and states are invented. No scanner is called.
const rows = [
  ['incoming_invoice', 'Nordlicht Bürobedarf (Demo)', 'Büromaterial', 'ER-1042', '240.00', 'ready', 'ER'],
  ['outgoing_invoice', 'Musterwerk GmbH (Demo)', 'Beratung', 'AR-2026-018', '2400.00', 'ready', 'AR'],
  ['bank_pdf', 'Musterbank (Demo)', 'Kontoauszug', 'KA-10', null, 'ready', 'Bankkonto'],
  ['bank_camt', 'Musterbank (Demo)', 'Kontoumsätze', 'CAMT-10', null, 'ready', 'Bankkonto'],
  ['security_pdf', 'Musterdepot (Demo)', 'Depotauszug', 'DEP-10', null, 'ready', 'Wertpapiere'],
  ['incoming_credit', 'Nordlicht Bürobedarf (Demo)', 'Gutschrift', 'GS-108', '60.00', 'ready', 'ER'],
  ['incoming_invoice', 'Wolkenpost IT (Demo)', 'Software', 'WP-2087', '120.00', 'review', 'ER'],
  ['receipt', 'Papierladen (Demo)', 'Scanbeleg', 'SCAN-15', '36.00', 'review', 'ER'],
];
const documents = rows.map(([kind, issuer, label, number, gross, status, folder], i) => {
  const extension = kind === 'bank_camt' ? 'xml' : kind === 'receipt' ? 'png' : 'pdf';
  const name = `2026-10-15 ${label} ${number}.${extension}`;
  return {
    id: `demo-${i + 1}`, company_id: 1, original_name: `${number}.${extension}`,
    effective_name: name, proposed_name: name, handover_name: '', name_source: 'generated', name_warning: '', name_conflict: false,
    sha256: 'a'.repeat(64), size: 24576 + i * 1024, media_type: extension === 'xml' ? 'application/xml' : extension === 'png' ? 'image/png' : 'application/pdf',
    kind, period: '2026-10', account_id: kind === 'security_pdf' ? 2 : kind.startsWith('bank') ? 1 : null,
    category_id: status === 'ready' ? 1 : null,
    metadata: { issuer, recipient: kind === 'outgoing_invoice' ? 'Beispielkunde (Demo)' : company.name, number, date: '2026-10-15', currency: 'EUR',
      open_points: status === 'review' ? ['Kategorie noch prüfen'] : [],
      ...(gross ? { gross, net: (Number(gross) / 1.2).toFixed(2), tax: (Number(gross) / 6).toFixed(2) } : { period_start: '2026-10-01', period_end: '2026-10-31' }) },
    issues: status === 'review' ? ['Kategorie noch prüfen'] : [], status, version: status === 'ready' ? 2 : 1,
    filed_path: `Musterwerk-GmbH/2026/10/${folder}/${name}`, archive_path: `Musterwerk-GmbH/2026/10/${folder}/${name}`,
    security_status: 'clean', security_error: '', duplicate_of: null, created_at: '2026-10-16T08:30:00Z', updated_at: '2026-10-16T09:00:00Z',
  };
});
const ready = documents.filter(d => d.status === 'ready');
const preview = {
  company, periods: ['2026-10'], parent_id: null, count: ready.length, bytes: ready.reduce((n, d) => n + d.size, 0),
  recipients: company.recipients, documents: ready,
  excluded: documents.filter(d => d.status !== 'ready').map(document => ({ document, reason: 'Kategorie noch prüfen' })),
  unassigned_inbox: [], unchanged: [], intentional_exclusions: [], excluded_inbox: [], exclusion_changes: [], blocked_imports: [], allow_open_issues: false,
};
function pageSvg(doc) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123"><rect width="794" height="1123" fill="white"/><g font-family="sans-serif" fill="#213c34"><text x="60" y="70" font-size="16">DEMO · SYNTHETISCHER BELEG · NICHT BUCHEN</text><text x="60" y="160" font-size="26">${doc.metadata.issuer}</text><text x="60" y="240" font-size="30">Rechnung ${doc.metadata.number}</text><text x="60" y="290" font-size="18">15.10.2026</text><text x="60" y="365" font-size="20">An: ${company.name}</text><path d="M60 420H734" stroke="#ccd9d4"/><text x="60" y="470" font-size="20">Software-Abonnement · Oktober 2026</text><text x="60" y="560" font-size="20">Netto</text><text x="600" y="560" font-size="20">${doc.metadata.net} EUR</text><text x="60" y="600" font-size="20">Umsatzsteuer 20 %</text><text x="600" y="600" font-size="20">${doc.metadata.tax} EUR</text><path d="M60 635H734" stroke="#ccd9d4"/><text x="60" y="685" font-size="24">Gesamtbetrag</text><text x="580" y="685" font-size="24">${doc.metadata.gross} EUR</text><text x="60" y="920" font-size="16">Alle Angaben sind frei erfunden.</text></g></svg>`;
}
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' };
const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${port}`);
  const path = url.pathname;
  const json = (data, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(data)); };
  if (path.startsWith('/api/')) {
    // Preview is read-only. All real writes, uploads, downloads and sends are intentionally unsupported.
    if (req.method === 'POST' && path === '/api/packages/preview/') return json(preview);
    if (req.method !== 'GET') return json({ error: 'Read-only screenshot demo: writes and sends disabled.' }, 405);
    if (path === '/api/auth/session/') return json({ username: 'Demo · fiktive Daten' });
    if (path === '/api/auth/csrf/') return json({ csrfToken: 'demo-no-authentication' });
    if (path === '/api/companies/') return json([company]);
    if (path === '/api/companies/1/') return json({ company, accounts, categories, permissions: { process: true } });
    if (path === '/api/documents/') {
      let results = documents.filter(d => (!url.searchParams.get('status') || (url.searchParams.get('status') === 'open' ? d.status !== 'ready' : d.status === url.searchParams.get('status'))) && (!url.searchParams.get('kind') || d.kind === url.searchParams.get('kind')) && (!url.searchParams.get('search') || JSON.stringify(d).toLowerCase().includes(url.searchParams.get('search').toLowerCase())));
      if (url.searchParams.get('exclusion') === 'excluded' || url.searchParams.get('company_id') === 'inbox' || (url.searchParams.get('period') && url.searchParams.get('period') !== '2026-10')) results = [];
      return json({ results: results.slice(0, Number(url.searchParams.get('limit') || 100)), total: results.length, next_cursor: null });
    }
    if (path === '/api/folders/1/') {
      const all = url.searchParams.get('period') === '2026-10' ? documents : [];
      const counts = list => ({ total: list.length, ready: list.filter(d => d.status === 'ready').length, open: list.filter(d => d.status !== 'ready').length });
      return json({ folders: ['ER', 'AR', 'Bankkonto', 'Wertpapiere'].map(name => {
        const list = all.filter(d => d.filed_path.includes(`/${name}/`));
        return { name, path: `Musterwerk-GmbH/2026/10/${name}/`, ...counts(list), files: list.filter(d => url.searchParams.get('status') !== 'open' || d.status !== 'ready') };
      }), unfiled: { files: [], total: 0, ready: 0, open: 0 }, summary: counts(all), total: all.length, next_cursor: null });
    }
    const match = path.match(/^\/api\/documents\/(demo-\d+)\/(.*)$/);
    if (match) {
      const doc = documents.find(d => d.id === match[1]);
      if (!doc) return json({ error: 'Unknown demo document' }, 404);
      if (!match[2]) return json(doc);
      if (match[2] === 'page/') { res.writeHead(200, { 'Content-Type': 'image/svg+xml' }); return res.end(pageSvg(doc)); }
      if (match[2] === 'text/') return json({ text: 'Synthetischer Demobeleg', pages: 1 });
      if (match[2] === 'duplicates/') return json([]);
    }
    if (path.endsWith('/status/')) return json({ status: 'unpaid', allocations: [], paid: '0.00', remaining: '120.00' });
    if (path.endsWith('/transactions/')) return json({ items: [], next_cursor: null });
    if (['/api/packages/', '/api/jobs/', '/api/dispatches/'].includes(path)) return json([]);
    return json({ error: `No demo fixture: ${path}` }, 404);
  }
  if (req.method !== 'GET') return json({ error: 'Read-only demo' }, 405);
  try {
    const file = resolve(root, `.${decodeURIComponent(path)}`);
    if (file !== root && !file.startsWith(root + '/')) return json({ error: 'Not found' }, 404);
    const target = extname(file) ? file : resolve(root, 'index.html');
    const body = await readFile(target);
    res.writeHead(200, { 'Content-Type': mime[extname(target)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
    res.end(body);
  } catch { json({ error: 'Build frontend first: cd frontend && npm ci && npm run build' }, 404); }
});
server.listen(port, '127.0.0.1', () => console.log(`Read-only synthetic screenshot demo: http://127.0.0.1:${port} (no real backend, scan or mail)`));
