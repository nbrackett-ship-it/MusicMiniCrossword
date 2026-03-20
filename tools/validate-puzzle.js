#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

function usage() {
  console.log(`Usage:
  node tools/validate-puzzle.js                # validate all puzzles/*.json
  node tools/validate-puzzle.js puzzles/foo.json
  node tools/validate-puzzle.js puzzles/foo.json puzzles/bar.json`);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function isPositiveInt(value) {
  return Number.isInteger(value) && value > 0;
}

function keyFor(r, c) {
  return `${r},${c}`;
}

function validatePuzzle(puzzle, filePath) {
  const errors = [];
  const warnings = [];

  if (!puzzle || typeof puzzle !== 'object') {
    return { errors: ['Puzzle JSON must be an object'], warnings };
  }

  const rows = puzzle?.gridSize?.rows;
  const cols = puzzle?.gridSize?.cols;

  if (!isPositiveInt(rows) || !isPositiveInt(cols)) {
    errors.push('gridSize.rows and gridSize.cols must be positive integers');
    return { errors, warnings };
  }

  if (!Array.isArray(puzzle.words) || puzzle.words.length === 0) {
    errors.push('words must be a non-empty array');
  }

  if (!puzzle.clues || typeof puzzle.clues !== 'object') {
    errors.push('clues must be an object with across and down arrays');
  }

  const acrossClues = Array.isArray(puzzle?.clues?.across) ? puzzle.clues.across : [];
  const downClues = Array.isArray(puzzle?.clues?.down) ? puzzle.clues.down : [];

  const clueMap = {
    across: new Map(),
    down: new Map(),
  };

  for (const dir of ['across', 'down']) {
    const clueArr = dir === 'across' ? acrossClues : downClues;
    for (const clue of clueArr) {
      if (!Number.isInteger(clue?.number)) {
        errors.push(`${dir} clue is missing an integer number`);
        continue;
      }
      if (typeof clue?.text !== 'string' || !clue.text.trim()) {
        errors.push(`${dir} clue ${clue.number} is missing text`);
      }
      if (clueMap[dir].has(clue.number)) {
        errors.push(`Duplicate ${dir} clue number: ${clue.number}`);
      } else {
        clueMap[dir].set(clue.number, clue.text);
      }
    }
  }

  const placedNumbers = {
    across: new Map(),
    down: new Map(),
  };

  const cells = new Map();

  for (const wordEntry of puzzle.words || []) {
    const label = `${wordEntry?.direction || 'unknown'} ${wordEntry?.number ?? '?'} (${wordEntry?.word || 'missing word'})`;

    if (!Number.isInteger(wordEntry?.number)) {
      errors.push(`Word entry ${label} is missing an integer number`);
      continue;
    }
    if (!Number.isInteger(wordEntry?.row) || !Number.isInteger(wordEntry?.col)) {
      errors.push(`Word entry ${label} must have integer row and col`);
      continue;
    }
    if (!['across', 'down'].includes(wordEntry?.direction)) {
      errors.push(`Word entry ${label} has invalid direction: ${wordEntry?.direction}`);
      continue;
    }
    if (typeof wordEntry?.word !== 'string' || !wordEntry.word.trim()) {
      errors.push(`Word entry ${label} is missing a word string`);
      continue;
    }
    if (!/^[A-Z]+$/i.test(wordEntry.word)) {
      warnings.push(`Word entry ${label} contains non A-Z characters`);
    }

    const word = wordEntry.word.toUpperCase();
    const dir = wordEntry.direction;
    const startKey = keyFor(wordEntry.row, wordEntry.col);
    const placedKey = `${dir}:${wordEntry.number}`;

    if (placedNumbers[dir].has(wordEntry.number)) {
      errors.push(`Duplicate ${dir} word number: ${wordEntry.number}`);
    } else {
      placedNumbers[dir].set(wordEntry.number, startKey);
    }

    for (let i = 0; i < word.length; i++) {
      const r = dir === 'down' ? wordEntry.row + i : wordEntry.row;
      const c = dir === 'across' ? wordEntry.col + i : wordEntry.col;

      if (r < 0 || r >= rows || c < 0 || c >= cols) {
        errors.push(`Out of bounds: ${label} hits row ${r}, col ${c} in a ${rows}x${cols} grid`);
        continue;
      }

      const k = keyFor(r, c);
      const existing = cells.get(k);
      const ch = word[i];

      if (!existing) {
        cells.set(k, {
          answer: ch,
          across: dir === 'across' ? wordEntry.number : null,
          down: dir === 'down' ? wordEntry.number : null,
          starts: new Set(i === 0 ? [placedKey] : []),
        });
      } else {
        if (existing.answer !== ch) {
          errors.push(`Overlap mismatch at row ${r}, col ${c}: saw ${existing.answer} and ${ch}`);
        }
        if (dir === 'across') {
          if (existing.across && existing.across !== wordEntry.number) {
            errors.push(`Two across answers overlap at row ${r}, col ${c}`);
          }
          existing.across = wordEntry.number;
        }
        if (dir === 'down') {
          if (existing.down && existing.down !== wordEntry.number) {
            errors.push(`Two down answers overlap at row ${r}, col ${c}`);
          }
          existing.down = wordEntry.number;
        }
        if (i === 0) existing.starts.add(placedKey);
      }
    }
  }

  for (const dir of ['across', 'down']) {
    const placed = placedNumbers[dir];
    const clues = clueMap[dir];

    for (const num of placed.keys()) {
      if (!clues.has(num)) {
        errors.push(`Missing ${dir} clue for word number ${num}`);
      }
    }
    for (const num of clues.keys()) {
      if (!placed.has(num)) {
        errors.push(`Clue ${dir} ${num} has no matching word entry`);
      }
    }
  }

  for (const [coord, cell] of cells.entries()) {
    if (!cell.across && !cell.down) {
      errors.push(`Filled cell ${coord} is not part of any across or down answer`);
    }
  }

  if (typeof puzzle.info === 'string') {
    const m = puzzle.info.match(/(\d+)×(\d+)/);
    if (m) {
      const infoRows = Number(m[1]);
      const infoCols = Number(m[2]);
      if (infoRows !== rows || infoCols !== cols) {
        warnings.push(`info says ${infoRows}×${infoCols}, but gridSize is ${rows}×${cols}`);
      }
    }
  }

  return { errors, warnings };
}

function collectFiles(args) {
  if (args.length) {
    return args.map(p => path.resolve(process.cwd(), p));
  }

  const puzzleDir = path.resolve(process.cwd(), 'puzzles');
  if (!fs.existsSync(puzzleDir)) {
    console.error('No puzzles directory found.');
    process.exit(1);
  }

  return fs.readdirSync(puzzleDir)
    .filter(name => name.endsWith('.json'))
    .map(name => path.join(puzzleDir, name))
    .sort();
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes('--help') || args.includes('-h')) {
    usage();
    process.exit(0);
  }

  const files = collectFiles(args);
  if (!files.length) {
    console.error('No puzzle JSON files found.');
    process.exit(1);
  }

  let totalErrors = 0;
  let totalWarnings = 0;

  for (const filePath of files) {
    try {
      const puzzle = readJson(filePath);
      const { errors, warnings } = validatePuzzle(puzzle, filePath);
      const rel = path.relative(process.cwd(), filePath);

      if (!errors.length && !warnings.length) {
        console.log(`OK      ${rel}`);
        continue;
      }

      if (errors.length) {
        console.log(`ERROR   ${rel}`);
        for (const err of errors) console.log(`  - ${err}`);
      } else {
        console.log(`OK      ${rel}`);
      }

      if (warnings.length) {
        console.log(`WARN    ${rel}`);
        for (const warn of warnings) console.log(`  - ${warn}`);
      }

      totalErrors += errors.length;
      totalWarnings += warnings.length;
    } catch (err) {
      totalErrors += 1;
      console.log(`ERROR   ${path.relative(process.cwd(), filePath)}`);
      console.log(`  - Failed to parse JSON: ${err.message}`);
    }
  }

  if (totalWarnings) {
    console.log(`\nWarnings: ${totalWarnings}`);
  }

  if (totalErrors) {
    console.log(`Errors: ${totalErrors}`);
    process.exit(1);
  }

  console.log('\nAll puzzles passed validation.');
}

main();
