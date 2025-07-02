// Crossword solution
const solution = {
    '0-0': 'B', '0-1': 'A', '0-2': 'N', '0-3': 'D',
    '1-0': 'E', '1-3': 'R',
    '2-0': 'A', '2-1': 'L', '2-2': 'B', '2-3': 'U', '2-4': 'M',
    '3-0': 'T', '3-3': 'M',
    '4-3': 'S'
};

// Track current direction (across or down)
let currentDirection = 'across';
let currentClue = null;

// Get all input cells
const cells = document.querySelectorAll('.grid-cell input');

// Add event listeners to each cell
cells.forEach(cell => {
    cell.addEventListener('input', handleInput);
    cell.addEventListener('keydown', handleKeydown);
    cell.addEventListener('focus', handleFocus);
});

function handleInput(e) {
    const input = e.target;
    input.value = input.value.toUpperCase();

    if (input.value) {
        // Move to next cell in current direction
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
            // Tab changes direction between across and down
            e.preventDefault();
            currentDirection = currentDirection === 'across' ? 'down' : 'across';
            highlightCurrentWord(input);
            break;
    }
}

function handleFocus(e) {
    const input = e.target;

    // Determine the best direction based on available cells
    if (input.dataset.across && input.dataset.down) {
        // Cell is part of both across and down
        // Keep current direction
    } else if (input.dataset.across) {
        currentDirection = 'across';
    } else if (input.dataset.down) {
        currentDirection = 'down';
    }

    currentClue = currentDirection === 'across' ? input.dataset.across : input.dataset.down;
    highlightCurrentWord(input);
}

function highlightCurrentWord(currentInput) {
    // Remove all previous highlights
    cells.forEach(cell => {
        cell.style.backgroundColor = '';
    });

    // Highlight cells in current word
    const clueNumber = currentDirection === 'across' 
        ? currentInput.dataset.across 
        : currentInput.dataset.down;

    if (clueNumber) {
        cells.forEach(cell => {
            if (cell.dataset[currentDirection] === clueNumber) {
                cell.style.backgroundColor = '#ffd700';
            }
        });
        currentInput.style.backgroundColor = '#ffeb3b';
    }
}

function moveToNextCell(currentInput) {
    const row = parseInt(currentInput.dataset.row);
    const col = parseInt(currentInput.dataset.col);

    if (currentDirection === 'across') {
        moveInDirection(currentInput, 0, 1);
    } else {
        moveInDirection(currentInput, 1, 0);
    }
}

function moveToPreviousCell(currentInput) {
    const row = parseInt(currentInput.dataset.row);
    const col = parseInt(currentInput.dataset.col);

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

    // Find the target cell
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
        if (!cell || cell.value !== value) {
            isComplete = false;
            break;
        }
    }

    if (isComplete && !document.querySelector('.success-message')) {
        const message = document.getElementById('message');
        message.innerHTML = '🎉 Congratulations! You solved the puzzle!';
        message.classList.add('success-message');

        // Celebrate with animation
        cells.forEach((cell, index) => {
            setTimeout(() => {
                cell.style.backgroundColor = '#4CAF50';
                cell.style.transition = 'background-color 0.3s';
            }, index * 50);
        });
    }
}