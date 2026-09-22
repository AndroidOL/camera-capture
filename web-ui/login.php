<?php
use Gallery\Config;
use Gallery\Security\Auth;
use Gallery\Security\Csrf;
use Gallery\Security\Headers;
use Gallery\Support\Asset;
use Gallery\Support\RateLimiter;
use Gallery\Support\Theme;

require __DIR__ . '/src/bootstrap.php';

Headers::apply('page');

if (Auth::isAuthenticated()) {
    header('Location: index.php');
    exit;
}

$error = '';

if (isset($_GET['error'])) {
    if ($_GET['error'] === 'unauthorized') {
        $error = '您需要登录才能访问。';
    } elseif ($_GET['error'] === 'session_timeout') {
        $error = '会话已超时，请重新登录。';
    }
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $ip = Auth::clientIp();
    $throttle = RateLimiter::check(
        'login:' . $ip,
        Config::getInt('login_max_attempts', 5),
        Config::getInt('login_lockout_seconds', 300)
    );

    if (!$throttle['allowed']) {
        $minutes = max(1, (int) ceil($throttle['retry_after'] / 60));
        $error = '尝试次数过多，请约 ' . $minutes . ' 分钟后再试。';
    } elseif (!Csrf::validate(isset($_POST['csrf_token']) ? $_POST['csrf_token'] : null)) {
        $error = '会话已失效，请刷新页面后重试。';
    } elseif (!Config::hasPassword()) {
        $error = '尚未配置访问密码，请先编辑 config.php 或设置 GALLERY_PASSWORD_HASH。';
    } else {
        $password = isset($_POST['password']) ? (string) $_POST['password'] : '';
        if (Auth::attempt($password)) {
            RateLimiter::reset('login:' . $ip);
            header('Location: index.php');
            exit;
        }
        $error = '密码错误，请重试。';
        if ($throttle['remaining'] <= 2) {
            $error .= ' 剩余尝试次数：' . $throttle['remaining'] . '。';
        }
    }
}
$theme = Theme::mode();
$accent = Theme::accent();
$themeLabel = $theme === 'light' ? '深色' : '浅色';
?>
<!DOCTYPE html>
<html lang="zh-CN" data-theme="<?= $theme ?>" data-accent="<?= htmlspecialchars($accent, ENT_QUOTES, 'UTF-8') ?>">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex, nofollow">
    <meta name="color-scheme" content="<?= $theme === 'light' ? 'light' : 'dark' ?>">
    <meta name="theme-color" content="<?= $theme === 'light' ? '#f5f6f9' : '#07080b' ?>">
    <title>登录 · 照片查看器</title>
    <link rel="stylesheet" href="<?= Asset::url('assets/css/base.css') ?>">
    <link rel="stylesheet" href="<?= Asset::url('assets/css/login.css') ?>">
</head>
<body class="login-page">
    <main class="login-card">
        <div class="login-header">
            <div class="login-brand">
                <span class="login-mark" aria-hidden="true">
                    <svg viewBox="0 0 24 24"><path d="M9 2 7.2 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-3.2L15 2H9Zm3 15a5 5 0 1 1 0-10 5 5 0 0 1 0 10Z"/></svg>
                </span>
                <h1>照片查看器</h1>
            </div>
            <span class="spacer"></span>
            <button type="button" id="themeToggle" class="btn btn-ghost theme-toggle" aria-label="切换主题" title="切换主题">
                <svg class="icon-sun" viewBox="0 0 24 24" aria-hidden="true">
                    <circle cx="12" cy="12" r="4.6"/>
                    <g>
                        <rect x="11.1" y="1.4" width="1.8" height="4.2" rx="0.9"/>
                        <rect x="11.1" y="18.4" width="1.8" height="4.2" rx="0.9"/>
                        <rect x="1.4" y="11.1" width="4.2" height="1.8" rx="0.9"/>
                        <rect x="18.4" y="11.1" width="4.2" height="1.8" rx="0.9"/>
                        <rect x="11.1" y="1.4" width="1.8" height="4.2" rx="0.9" transform="rotate(45 12 12)"/>
                        <rect x="11.1" y="18.4" width="1.8" height="4.2" rx="0.9" transform="rotate(45 12 12)"/>
                        <rect x="1.4" y="11.1" width="4.2" height="1.8" rx="0.9" transform="rotate(45 12 12)"/>
                        <rect x="18.4" y="11.1" width="4.2" height="1.8" rx="0.9" transform="rotate(45 12 12)"/>
                    </g>
                </svg>
                <svg class="icon-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>
                <span class="theme-label" id="themeLabel"><?= $themeLabel ?></span>
            </button>
        </div>

        <p class="login-subtitle">请输入访问密码</p>

        <form method="post" action="login.php" autocomplete="off" novalidate>
            <?= Csrf::field() ?>
            <label class="field-label" for="password">密码</label>
            <div class="password-field">
                <input type="password" id="password" name="password" required autocomplete="current-password" autofocus>
                <button type="button" id="togglePassword" class="password-toggle" aria-label="显示或隐藏密码">显示</button>
            </div>
            <p id="capsHint" class="caps-hint" hidden>注意：大写锁定已开启</p>
            <button type="submit" class="btn btn-accent btn-block">登 录</button>
        </form>

        <?php if ($error !== ''): ?>
            <p class="login-error" role="alert"><?= htmlspecialchars($error, ENT_QUOTES, 'UTF-8') ?></p>
        <?php endif; ?>

        <footer class="login-footer">© <?= date('Y') ?> 相机系统</footer>
    </main>

    <script type="module" src="<?= Asset::url('assets/js/login.js') ?>"></script>
</body>
</html>
