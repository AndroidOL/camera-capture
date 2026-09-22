export function prefersReducedMotion() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

export function stagger(container, selector, stepMs, cap) {
    if (!container) {
        return;
    }
    const step = stepMs === undefined ? 26 : stepMs;
    const limit = cap === undefined ? 24 : cap;
    const nodes = container.querySelectorAll(selector || '.tile');
    for (let i = 0; i < nodes.length; i++) {
        nodes[i].style.setProperty('--i', String(Math.min(i, limit)));
    }
}

export function restartAnimation(node) {
    if (!node) {
        return;
    }
    node.style.animation = 'none';
    void node.offsetWidth;
    node.style.animation = '';
}

export function countUp(element, target, options) {
    if (!element) {
        return;
    }
    const settings = options || {};
    const to = Number(target);
    const format = settings.format || ((value) => value.toFixed(settings.decimals || 0));

    if (!isFinite(to)) {
        element.textContent = '—';
        return;
    }

    const duration = prefersReducedMotion() ? 0 : settings.duration === undefined ? 900 : settings.duration;
    if (duration <= 0) {
        element.textContent = format(to);
        return;
    }

    const start = performance.now();
    const step = (now) => {
        const progress = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - progress, 3);
        element.textContent = format(to * eased);
        if (progress < 1) {
            requestAnimationFrame(step);
        }
    };
    requestAnimationFrame(step);
}

export function animateWidth(element, percent) {
    if (!element) {
        return;
    }
    const value = Math.max(0, Math.min(100, Number(percent) || 0));
    requestAnimationFrame(() => {
        element.style.width = value + '%';
    });
}

export function animateScaleY(element, fraction) {
    if (!element) {
        return;
    }
    const value = Math.max(0, Math.min(1, Number(fraction) || 0));
    requestAnimationFrame(() => {
        element.style.transform = 'scaleY(' + value + ')';
    });
}

export function observeReveal(root) {
    const scope = root || document;
    const nodes = scope.querySelectorAll('.reveal');
    if (!nodes.length) {
        return;
    }

    if (prefersReducedMotion() || typeof IntersectionObserver === 'undefined') {
        for (let i = 0; i < nodes.length; i++) {
            nodes[i].classList.add('in');
        }
        return;
    }

    const observer = new IntersectionObserver(
        (entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('in');
                    observer.unobserve(entry.target);
                }
            });
        },
        { rootMargin: '0px 0px -6% 0px', threshold: 0.05 }
    );

    for (let i = 0; i < nodes.length; i++) {
        observer.observe(nodes[i]);
    }
}
