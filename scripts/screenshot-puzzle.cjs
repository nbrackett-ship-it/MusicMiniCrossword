const { chromium } = require('playwright');
const { isDeepStrictEqual } = require('node:util');
const fs = require('node:fs/promises');
const path = require('node:path');

async function capturePuzzle({ puzzle, baseUrl = 'https://crossword.stems.media/', outputPath,
  timeoutMs = 300000, retryMs = 5000 }) {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE_PATH });
  try {
    const page = await browser.newPage({ viewport: { width: 800, height: 800 } });
    // Publishing previews must not create player analytics records.
    await page.route('**/analytics.js', route => route.fulfill({ contentType: 'application/javascript', body: '' }));
    const deadline = Date.now() + timeoutMs;
    let lastError;
    while (Date.now() < deadline) {
      const attemptMs = Math.min(15000, deadline - Date.now());
      const target = new URL(baseUrl);
      target.searchParams.set('puzzle', puzzle.id);
      target.searchParams.set('v', String(Date.now()));
      try {
        const responsePromise = page.waitForResponse(response =>
          new URL(response.url()).pathname === `/puzzles/${puzzle.id}.json`, { timeout: attemptMs });
        const [navigation, response] = await Promise.allSettled([
          page.goto(target.href, { waitUntil: 'domcontentloaded', timeout: attemptMs }), responsePromise
        ]);
        if (navigation.status === 'rejected') throw navigation.reason;
        if (response.status === 'rejected') throw response.reason;
        if (!response.value.ok()) throw new Error(`Puzzle JSON HTTP ${response.value.status()}`);
        if (!isDeepStrictEqual(await response.value.json(), puzzle)) throw new Error('Deployed puzzle JSON differs from submitted puzzle');
        await page.waitForFunction(expected => {
          const grid = document.getElementById('crosswordGrid');
          const title = document.getElementById('puzzleTitle');
          return title?.textContent === expected.title && grid?.children.length === expected.gridSize.rows * expected.gridSize.cols &&
            grid.querySelectorAll('.cell').length > 0 && grid.getBoundingClientRect().width > 0 &&
            grid.getBoundingClientRect().height > 0 &&
            [...grid.querySelectorAll('.glyph')].every(el => el.textContent === '');
        }, puzzle, { timeout: Math.max(1, Math.min(15000, deadline - Date.now())) });
        await page.addStyleTag({ content: '#sticky-clue-bar { display: none !important; }' });
        await fs.mkdir(path.dirname(outputPath), { recursive: true });
        await page.screenshot({ path: outputPath, animations: 'disabled', timeout: 15000 });
        console.log(`Verified puzzle and rendered grid; screenshot saved: ${outputPath}`);
        return;
      } catch (error) {
        lastError = error;
        console.log(`Waiting for ${puzzle.id}: ${error.message.split('\n')[0]}`);
        const remaining = deadline - Date.now();
        if (remaining > 0) await new Promise(resolve => setTimeout(resolve, Math.min(retryMs, remaining)));
      }
    }
    throw new Error(`Puzzle ${puzzle.id} not ready after ${timeoutMs}ms: ${lastError?.message}`);
  } finally { await browser.close(); }
}
module.exports = { capturePuzzle };

if (require.main === module) {
  (async () => {
    const slug = process.env.SLUG;
    if (!slug || !/^[a-z0-9-]+-\d{4}-\d{2}-\d{2}$/.test(slug)) throw new Error('Invalid SLUG');
    const puzzle = JSON.parse(await fs.readFile(`puzzles/${slug}.json`, 'utf8'));
    if (puzzle.id !== slug) throw new Error('Puzzle id does not match SLUG');
    const imageName = `${slug}-${process.env.GITHUB_RUN_ID || 'refresh'}-${process.env.GITHUB_RUN_ATTEMPT || '1'}.png`;
    await capturePuzzle({ puzzle, outputPath: `images/${imageName}` });
    if (process.env.GITHUB_OUTPUT) await fs.appendFile(process.env.GITHUB_OUTPUT, `image_name=${imageName}\n`);
  })().catch(error => { console.error(error.message); process.exitCode = 1; });
}
