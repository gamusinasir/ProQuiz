// Timer countdown (60s)
function startTimer() {
    let timeLeft = 60;
    const timer = setInterval(() => {
        timeLeft--;
        document.getElementById('timer').textContent = timeLeft;
        if (timeLeft <= 0) {
            clearInterval(timer);
            document.getElementById('answer-form').submit(); // Auto-submit
        }
    }, 1000);
}

// Highlight correct/incorrect answers
function showResult(isCorrect) {
    if (isCorrect) {
        document.getElementById('answers').classList.add('correct');
    } else {
        document.getElementById('answers').classList.add('incorrect');
    }
}