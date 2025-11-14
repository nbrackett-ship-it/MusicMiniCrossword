document.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const puzzleSlug = urlParams.get('puzzle'); // Gets "punks-not-dead-2025-11-14" from the URL

    if (puzzleSlug) {
        // Assumes all puzzles are in a 'puzzles/' directory
        const puzzleFile = `puzzles/${puzzleSlug}.json`; 
        init(puzzleFile); // Calls init with the correct file path
    } else {
        // Fallback if no ?puzzle= parameter is found
        console.error("No puzzle slug found in URL.");
        const gridContainer = document.getElementById('grid-container');
        if (gridContainer) {
            gridContainer.innerHTML = '<p style="color: red;">Error: No puzzle selected.</p>';
        }
    }
});

let solution = {};
let cells = [];
let currentDirection = 'across';

function init(puzzleFile) {
    fetch(puzzleFile)
        .then(response => {
            if (!response.ok) {
                throw new Error(`Puzzle file not found: ${puzzleFile}`);
            }
            return response.json();
        })
        .then(puzzleData => {
            loadPuzzle(puzzleData);
        })
        .catch(error => {
            console.error(error);
            const gridContainer = document.getElementById('grid-container');
            if (gridContainer) {
                gridContainer.innerHTML = '<p style="text-align: center; color: #555;">Puzzle Not Found</p>';
            }
        });
}

function loadPuzzle(puzzleData) {
    console.log("Loading puzzle:", puzzleData.title);
    const gridContainer = document.getElementById('grid-container');
    const acrossClues = document.getElementById('across-clues');
    const downClues = document.getElementById('down-clues');

    // Clear previous grid and clues
    gridContainer.innerHTML = '';
    if (acrossClues) acrossClues.innerHTML = '';
    if (downClues) downClues.innerHTML = '';

    // Dynamically set the grid size
    const { rows, cols } = puzzleData.gridSize;
    gridContainer.style.setProperty('--grid-rows', rows);
    gridContainer.style.setProperty('--grid-cols', cols);

    // Build the grid cells
    puzzleData.grid.forEach((row, rowIndex) => {
        row.forEach((cellData, colIndex) => {
            if (cellData === "") {
                const blackCell = document.createElement('div');
                blackCell.className = 'black-cell';
                gridContainer.appendChild(blackCell);
            } else {
                const cellWrapper = document.createElement('div');
                cellWrapper.className = 'grid-cell';

                const input = document.createElement('input');
                input.type = 'text';
                input.maxLength = 1;
                input.dataset.row = rowIndex;
                input.dataset.col = colIndex;

                // Add data attributes for clues
                if (cellData.across) input.dataset.across = cellData.across;
                if (cellData.down) input.dataset.down = cellData.down;

                const clueNumber = puzzleData.numbers.find(n => n.row === rowIndex && n.col === colIndex);
                if (clueNumber) {
                    const numberElement = document.createElement('div');
                    numberElement.className = 'clue-number';
                    numberElement.textContent = clueNumber.number;
                    cellWrapper.appendChild(numberElement);
                }

                cellWrapper.appendChild(input);
                gridContainer.appendChild(cellWrapper);
            }
        });
    });

    // Populate the clue lists
    if (acrossClues && puzzleData.clues.across) {
        puzzleData.clues.across.forEach(clue => {
            const li = document.createElement('li');
            li.textContent = `${clue.number}. ${clue.text}`;
            acrossClues.appendChild(li);
        });
    }

    if (downClues && puzzleData.clues.down) {
        puzzleData.clues.down.forEach(clue => {
            const li = document.createElement('li');
            li.textContent = `${clue.number}. ${clue.text}`;
            downClues.appendChild(li);
        });
    }

    // Update solution and attach listeners
    solution = puzzleData.answers;
    cells = document.querySelectorAll('.grid-cell input');
    cells.forEach(cell => {
        cell.addEventListener('input', handleInput);
        cell.addEventListener('keydown', handleKeydown);
        cell.addEventListener('focus', handleFocus);
    });
}


// --- All of your existing helper functions ---

function handleInput(e) {
    const input = e.target;
    input.value = input.value.toUpperCase();

    if (input.value) {
        moveToNextCell(input);
    }

    checkPuzzleCompletion();
}

function handleKeydown(e) {
    const input = e.target;

    switch(e.key) {
        case 'Backspace':
            if (!input.value && !e.repeat) {
                e.preventDefault();
                moveToPreviousCell(input);
            }
            break;
        case 'ArrowLeft':
            e.preventDefault();
            moveInDirection(input, 0, -1);
            break;
        case 'ArrowRight':
            e.preventDefault();
            moveInDirection(input, 0, 1);
            break;
        case 'ArrowUp':
            e.preventDefault();
            moveInDirection(input, -1, 0);
            break;
        case 'ArrowDown':
            e.preventDefault();
            moveInDirection(input, 1, 0);
            break;
        case 'Tab':
            e.preventDefault();
            currentDirection = currentDirection === 'across' ? 'down' : 'across';
            highlightCurrentWord(input);
            break;
    }
}

function handleFocus(e) {
    const input = e.target;

    if (input.dataset.across && input.dataset.down) {
        // Keep current direction if the cell is part of both
    } else if (input.dataset.across) {
        currentDirection = 'across';
    } else if (input.dataset.down) {
        currentDirection = 'down';
    }
    highlightCurrentWord(input);
}

function highlightCurrentWord(currentInput) {
    cells.forEach(cell => {
        cell.style.backgroundColor = '';
        cell.parentElement.style.backgroundColor = 'white';
    });

    const clueNumber = currentDirection === 'across' 
        ? currentInput.dataset.across 
        : currentInput.dataset.down;

    if (clueNumber) {
        cells.forEach(cell => {
            if (cell.dataset[currentDirection] === clueNumber) {
                cell.parentElement.style.backgroundColor = '#ffd700'; // Highlight the wrapper div
            }
        });
        currentInput.parentElement.style.backgroundColor = '#ffeb3b'; // Brighter highlight for current cell
    }
}

function moveToNextCell(currentInput) {
    if (currentDirection === 'across') {
        moveInDirection(currentInput, 0, 1);
    } else {
        moveInDirection(currentInput, 1, 0);
    }
}

function moveToPreviousCell(currentInput) {
    if (currentDirection === 'across') {
        moveInDirection(currentInput, 0, -1);
    } else {
        moveInDirection(currentInput, -1, 0);
    }
}

function moveInDirection(currentInput, rowDelta, colDelta) {
    const row = parseInt(currentInput.dataset.row);
    const col = parseInt(currentInput.dataset.col);
    const newRow = row + rowDelta;
    const newCol = col + colDelta;

    const targetCell = document.querySelector(`[data-row="${newRow}"][data-col="${newCol}"]`);
    if (targetCell) {
        targetCell.focus();
    }
}

function checkPuzzleCompletion() {
    let isComplete = true;

    for (const [key, value] of Object.entries(solution)) {
        const [row, col] = key.split('-');
        const cell = document.querySelector(`[data-row="${row}"][data-col="${col}"]`);
        if (!cell || cell.value.toUpperCase() !== value) {
            isComplete = false;
            break;
        }
    }

    if (isComplete && !document.body.querySelector('.success-message')) {
        const message = document.getElementById('message');
        if(message) {
            message.innerHTML = '🎉 Congratulations! You solved the puzzle!';
            message.classList.add('success-message');
        }

        cells.forEach((cell, index) => {
            setTimeout(() => {
                cell.parentElement.style.backgroundColor = '#4CAF50';
                cell.parentElement.style.transition = 'background-color 0.3s';
            }, index * 50);
        });
    }
}
