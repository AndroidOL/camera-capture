import { initTheme, toggleTheme } from './theme.js';

initTheme();

const themeToggle = document.getElementById('themeToggle');
const password = document.getElementById('password');
const togglePassword = document.getElementById('togglePassword');
const capsHint = document.getElementById('capsHint');

if (themeToggle) {
    themeToggle.addEventListener('click', () => {
        const mode = toggleTheme();
        const label = document.getElementById('themeLabel');
        if (label) {
            label.textContent = mode === 'light' ? '深色' : '浅色';
        }
    });
}

if (togglePassword && password) {
    togglePassword.addEventListener('click', () => {
        const isPassword = password.getAttribute('type') === 'password';
        password.setAttribute('type', isPassword ? 'text' : 'password');
        togglePassword.textContent = isPassword ? '隐藏' : '显示';
    });
}

if (capsHint && password) {
    const update = (event) => {
        const locked = event.getModifierState && event.getModifierState('CapsLock');
        capsHint.hidden = !locked;
    };
    password.addEventListener('keydown', update);
    password.addEventListener('keyup', update);
    password.addEventListener('focus', update);
    password.addEventListener('blur', () => {
        capsHint.hidden = true;
    });
}
