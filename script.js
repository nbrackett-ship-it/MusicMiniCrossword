// Get all our crossword cells
const cells = document.querySelectorAll('.grid-cell');

// Define all three words that need to be completed
const words = {
  'BPM': {
    cells: ['cell-0-0', 'cell-0-1', 'cell-0-2']
  },
  'BAT': {
    cells: ['cell-0-0', 'cell-1-0', 'cell-2-0']  
  },
  'MUS': {
    cells: ['cell-0-2', 'cell-1-2', 'cell-2-2']
  }
};

// Add event listeners to each cell with auto-navigation
cells.forEach((cell, index) => {
  cell.addEventListener('input', function() {
    this.value = this.value.toUpperCase();

    // Auto-move to next empty cell after typing
    const allCells = Array.from(cells);
    const currentIndex = allCells.indexOf(this);

    if (this.value && currentIndex < allCells.length - 1) {
      // Find next empty cell
      for (let i = currentIndex + 1; i < allCells.length; i++) {
        if (!allCells[i].value) {
          allCells[i].focus();
          break;
        }
      }
    }

    checkPuzzleCompletion();
  });

  // Handle backspace to go to previous cell
  cell.addEventListener('keydown', function(e) {
    if (e.key === 'Backspace' && !this.value) {
      const allCells = Array.from(cells);
      const currentIndex = allCells.indexOf(this);
      if (currentIndex > 0) {
        allCells[currentIndex - 1].focus();
      }
    }
  });
});

// Check if ALL words are complete
function checkPuzzleCompletion() {
  let allWordsCorrect = true;

  for (const [word, data] of Object.entries(words)) {
    const currentLetters = data.cells.map(cellId => {
      const cell = document.getElementById(cellId);
      return cell ? cell.value : '';
    }).join('');

    if (currentLetters !== word) {
      allWordsCorrect = false;
      break;
    }
  }

  // Only celebrate when ALL THREE words are complete
  if (allWordsCorrect) {
    setTimeout(() => {
      alert('🎉 Amazing! You solved the entire crossword! BPM, BAT, and MUS! 🎵');
    }, 100);
  }
}