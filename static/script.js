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

// Common API handling utilities
const api = {
    async fetch(url, options = {}) {
        try {
            const response = await fetch(url, {
                ...options,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                }
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'API request failed');
            return data;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    },

    async uploadFile(url, formData) {
        try {
            const response = await fetch(url, {
                method: 'POST',
                body: formData
            });
            return await response.json();
        } catch (error) {
            console.error('Upload Error:', error);
            throw error;
        }
    }
};

// Common UI utilities
const ui = {
    showLoading(show = true) {
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) overlay.style.display = show ? 'flex' : 'none';
    },

    showError(message) {
        alert(message || 'An error occurred. Please try again.');
    },

    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
};

// Common quiz functionality
const quiz = {
    async checkStatus(quizId) {
        return await api.fetch(`/quiz_status/${quizId}`);
    },

    async submitAnswer(quizId, questionId, answer) {
        return await api.fetch(`/submit_answer/${quizId}`, {
            method: 'POST',
            body: JSON.stringify({ question_id: questionId, answer })
        });
    },

    async adjustScore(quizId, playerId, points, reason) {
        return await api.fetch(`/adjust_score/${quizId}/${playerId}`, {
            method: 'POST',
            body: JSON.stringify({ points, reason })
        });
    },

    async archiveQuiz(quizId) {
        return await api.fetch(`/archive_quiz/${quizId}`, {
            method: 'POST'
        });
    }
};

// Page visibility handling
const pageVisibility = {
    callbacks: [],
    
    onChange(callback) {
        this.callbacks.push(callback);
    },
    
    init() {
        document.addEventListener('visibilitychange', () => {
            const isVisible = !document.hidden;
            this.callbacks.forEach(cb => cb(isVisible));
        });
    }
};

pageVisibility.init();