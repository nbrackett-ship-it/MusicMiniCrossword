const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { capturePuzzle } = require('../scripts/screenshot-puzzle.cjs');

const puzzle = { id: 'test-2026-10-09', title: 'Test', info: 'Test • 2×2',
  gridSize: { rows: 2, cols: 2 },
  words: [{ number: 1, row: 0, col: 0, direction: 'across', word: 'HI' }],
  clues: { across: [{ number: 1, text: 'Greeting' }], down: [] } };

async function fixture(t, response, html) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'crossword-test-'));
  let requests = 0;
  const index = html || await fs.readFile(path.join(__dirname, '../index.html'), 'utf8');
  const server = http.createServer((req, res) => {
    if (req.url.startsWith('/puzzles/')) {
      const data = response(++requests);
      res.writeHead(data ? 200 : 404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(data || { error: 'Not deployed' }));
    } else if (req.url.startsWith('/?')) {
      res.writeHead(200, { 'Content-Type': 'text/html' }); res.end(index);
    } else { res.writeHead(404); res.end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await fs.rm(dir, { recursive: true, force: true }); });
  return { baseUrl: `http://127.0.0.1:${server.address().port}/`,
    outputPath: path.join(dir, 'image.png'), requests: () => requests };
}

// Capturing on the first HTTP 200 would accept stale JSON or an error page.
test('retries a deployment 404 and stale JSON before capturing the actual grid', async t => {
  const f = await fixture(t, n => n === 1 ? null : n === 2 ? { ...puzzle, title: 'Old title' } : puzzle);
  await capturePuzzle({ ...f, puzzle, timeoutMs: 10000, retryMs: 20 });
  assert.ok(f.requests() >= 3);
  const png = await fs.readFile(f.outputPath);
  assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  assert.equal(png.readUInt32BE(16), 800);
  assert.equal(png.readUInt32BE(20), 800);
});

test('times out without writing an image when the puzzle never deploys', async t => {
  const f = await fixture(t, () => null);
  await assert.rejects(capturePuzzle({ ...f, puzzle, timeoutMs: 1200, retryMs: 20 }), /not ready/i);
  await assert.rejects(fs.access(f.outputPath), { code: 'ENOENT' });
});

test('rejects HTTP 200 JSON when the grid never renders', async t => {
  const html = `<h1 id="puzzleTitle">Test</h1><div id="crosswordGrid"></div><script>fetch('/puzzles/test-2026-10-09.json')</script>`;
  const f = await fixture(t, () => puzzle, html);
  await assert.rejects(capturePuzzle({ ...f, puzzle, timeoutMs: 1200, retryMs: 20 }), /not ready/i);
  await assert.rejects(fs.access(f.outputPath), { code: 'ENOENT' });
});
