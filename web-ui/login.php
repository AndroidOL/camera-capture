<?php
require_once 'config.php'; // 包含配置并启动会话

$error_message = '';

// 如果已登录，直接跳转到相册页面
if (check_authentication()) {
    header('Location: index.php');
    exit;
}

// 处理登录表单提交
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $password_attempt = $_POST['password'] ?? '';
    
    // !!! 在生产环境中，这里应该使用 password_verify($password_attempt, $hashed_password_from_db) !!!
    if (
        (defined('GALLERY_PASSWORD_HASH') && GALLERY_PASSWORD_HASH && password_verify($password_attempt, GALLERY_PASSWORD_HASH))
        || $password_attempt === GALLERY_PASSWORD // 兼容旧配置，建议移除
    ) {
        if (function_exists('session_regenerate_id')) session_regenerate_id(true);
        set_authenticated_session(); // 设置认证成功的会话
        header('Location: index.php');
        exit;
    } else {
        $error_message = '密码错误，请重试。';
    }
}

// 处理URL中的错误提示（例如会话超时）
if (isset($_GET['error'])) {
    if ($_GET['error'] === 'session_timeout') {
        $error_message = '会话已超时，请重新登录。';
    } elseif ($_GET['error'] === 'unauthorized') {
        $error_message = '您需要登录才能访问。';
    }
}
?>
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>登录 - 照片查看器</title>
    <style>
        :root {
            --bg1: #0ea5e9;
            --bg2: #3b82f6;
            --card-bg: #ffffff;
            --text: #0f172a;
            --muted: #64748b;
            --primary: #2563eb;
            --primary-hover: #1d4ed8;
            --border: #e2e8f0;
            --danger-bg: #fee2e2;
            --danger-border: #fecaca;
            --danger-text: #991b1b;
        }
        body.dark-theme {
            --card-bg: #1f2937;
            --text: #e5e7eb;
            --muted: #9ca3af;
            --border: #374151;
            --primary: #3b82f6;
            --primary-hover: #2563eb;
        }
        html, body { min-height: 100vh; }
        body { display: flex; justify-content: center; align-items: center; margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: var(--text); background: radial-gradient(1200px 800px at 20% -10%, rgba(14,165,233,.25), transparent), radial-gradient(1000px 700px at 120% 20%, rgba(59,130,246,.25), transparent), linear-gradient(180deg, #eef2ff 0%, #f8fafc 100%); }
        body.dark-theme { background: radial-gradient(1200px 800px at 20% -10%, rgba(59,130,246,.25), transparent), radial-gradient(1000px 700px at 120% 20%, rgba(14,165,233,.2), transparent), linear-gradient(180deg, #0b1220 0%, #111827 100%); }
        .login-container { background: var(--card-bg); padding: 34px 36px; border-radius: 14px; box-shadow: 0 10px 30px rgba(2,6,23,.08), inset 0 1px 0 rgba(255,255,255,.4); text-align: left; width: 100%; max-width: 420px; border: 1px solid var(--border); }
        .header { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
        .brand { display: flex; align-items: center; gap: 10px; }
        .brand .logo { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; color: #fff; background: linear-gradient(135deg, var(--bg1), var(--bg2)); box-shadow: 0 8px 16px rgba(37,99,235,.3); }
        .brand h2 { margin: 0; font-size: 1.45rem; font-weight: 700; letter-spacing: .2px; }
        .subtitle { margin: 4px 0 22px 0; color: var(--muted); font-size: .95rem; }
        .theme-btn { background: #64748b; color: #fff; border: none; border-radius: 8px; padding: 8px 12px; cursor: pointer; font-size: .9rem; transition: filter .15s ease; }
        body.dark-theme .theme-btn { background: #9ca3af; color: #111827; }
        .theme-btn:hover { filter: brightness(1.05); }
        label { display: block; margin: 10px 0 8px 0; font-weight: 600; font-size: .95rem; }
        .input-row { position: relative; width: 100%; }
        .input-row input { display: block; width: 100%; max-width: 100%; padding: 12px 42px 12px 12px; border: 1px solid var(--border); border-radius: 10px; font-size: 1rem; outline: none; transition: box-shadow .15s ease, border-color .15s ease; background: transparent; color: var(--text); box-sizing: border-box; }
        .input-row input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(37,99,235,.12); }
        .toggle-visibility { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); width: 32px; height: 32px; border: none; border-radius: 8px; background: transparent; color: var(--muted); cursor: pointer; display: grid; place-items: center; }
        .toggle-visibility:hover { color: var(--text); background: rgba(148,163,184,.12); }
        .caps-tip { margin-top: 8px; color: var(--muted); font-size: .85rem; display: none; }
        .submit-btn { width: 100%; background-color: var(--primary); color: white; padding: 12px 0; border: none; border-radius: 10px; cursor: pointer; font-size: 1.05rem; font-weight: 600; transition: background-color 0.15s, transform .04s; margin-top: 16px; }
        .submit-btn:hover { background-color: var(--primary-hover); }
        .submit-btn:active { transform: translateY(1px); }
        .error-message { color: var(--danger-text); margin-top: 14px; font-size: .9rem; padding: 10px 12px; background-color: var(--danger-bg); border: 1px solid var(--danger-border); border-radius: 8px; }
        .footer { margin-top: 18px; color: var(--muted); font-size: .82rem; text-align: center; }
        @media (max-width: 420px) {
            .login-container { padding: 26px 22px; }
            .input-row input { padding-right: 38px; }
            .toggle-visibility { width: 28px; height: 28px; right: 6px; }
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="header">
            <div class="brand">
                <div class="logo" aria-hidden="true">📷</div>
                <h2>照片查看器登录</h2>
            </div>
            <button id="themeToggleBtn" class="theme-btn" title="切换主题">☀️</button>
        </div>
        <p class="subtitle">请输入访问密码</p>
        <form method="POST" action="login.php" novalidate autocomplete="off">
            <label for="password">密码</label>
            <div class="input-row">
                <input type="password" name="password" id="password" required autocomplete="current-password" autofocus aria-describedby="caps-hint">
                <button type="button" class="toggle-visibility" id="togglePwdBtn" aria-label="显示/隐藏密码" title="显示/隐藏密码">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><path id="eyePath" d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5C21.27 7.61 17 4.5 12 4.5m0 12.5a5 5 0 1 1 0-10 5 5 0 0 1 0 10Z"/></svg>
                </button>
            </div>
            <div class="caps-tip" id="caps-hint">注意：大写锁定已开启</div>
            <button class="submit-btn" type="submit">登 录</button>
        </form>
        <?php if ($error_message): ?>
            <p class="error-message"><?php echo htmlspecialchars($error_message); ?></p>
        <?php endif; ?>
        <div class="footer">© <?php echo date('Y'); ?> 相机系统</div>
    </div>
    <script>
        (function(){
            // 主题切换与持久化
            function applyTheme(theme) {
                const btn = document.getElementById('themeToggleBtn');
                if (theme === 'dark') {
                    document.body.classList.add('dark-theme');
                    if (btn) { btn.textContent = '浅色主题'; btn.title = '切换到日间模式'; }
                } else {
                    document.body.classList.remove('dark-theme');
                    if (btn) { btn.textContent = '深色主题'; btn.title = '切换到夜间模式'; }
                }
            }
            const storedTheme = localStorage.getItem('galleryTheme') || 'light';
            applyTheme(storedTheme);
            const themeBtn = document.getElementById('themeToggleBtn');
            if (themeBtn) {
                themeBtn.addEventListener('click', () => {
                    const currentTheme = document.body.classList.contains('dark-theme') ? 'dark' : 'light';
                    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
                    localStorage.setItem('galleryTheme', newTheme);
                    applyTheme(newTheme);
                });
            }

            const pwd = document.getElementById('password');
            const btn = document.getElementById('togglePwdBtn');
            const capsHint = document.getElementById('caps-hint');
            if (btn && pwd) {
                btn.addEventListener('click', () => {
                    const isPwd = pwd.getAttribute('type') === 'password';
                    pwd.setAttribute('type', isPwd ? 'text' : 'password');
                    btn.title = isPwd ? '隐藏密码' : '显示密码';
                });
            }
            if (pwd && capsHint) {
                function handle(e){
                    const caps = e.getModifierState && e.getModifierState('CapsLock');
                    capsHint.style.display = caps ? 'block' : 'none';
                }
                pwd.addEventListener('keydown', handle);
                pwd.addEventListener('keyup', handle);
                pwd.addEventListener('focus', handle);
                pwd.addEventListener('blur', () => { capsHint.style.display = 'none'; });
            }
        })();
    </script>
</body>
</html>
