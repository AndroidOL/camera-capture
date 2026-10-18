<?php
use Gallery\Config;
use Gallery\Security\Auth;
use Gallery\Security\Csrf;
use Gallery\Security\Headers;
use Gallery\Support\RateLimiter;
use Gallery\Support\Response;

require __DIR__ . '/src/bootstrap.php';

Headers::apply('page');

$accept = isset($_SERVER['HTTP_ACCEPT']) ? (string) $_SERVER['HTTP_ACCEPT'] : '';
$requestedWith = isset($_SERVER['HTTP_X_REQUESTED_WITH']) ? strtolower((string) $_SERVER['HTTP_X_REQUESTED_WITH']) : '';
$isAjax = strpos($accept, 'application/json') !== false || $requestedWith === 'xmlhttprequest';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    if ($isAjax) {
        Response::error('仅支持 POST 请求。', 405);
        exit;
    }
    http_response_code(405);
    header('Allow: POST');
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Method Not Allowed';
    exit;
}

if (!Csrf::validate(isset($_POST['csrf_token']) ? $_POST['csrf_token'] : null)) {
    if ($isAjax) {
        Response::error('会话已失效，请刷新页面后重试。', 403);
        exit;
    }
    http_response_code(403);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Invalid CSRF token';
    exit;
}

$throttle = RateLimiter::check(
    'auth-logout:' . Auth::clientIp(),
    Config::getInt('auth_logout_rate_limit', 30),
    60
);

if (!$throttle['allowed']) {
    if (!headers_sent()) {
        header('Retry-After: ' . $throttle['retry_after']);
    }
    if ($isAjax) {
        Response::json(
            ['error' => '登出请求过于频繁，请稍后再试。', 'retry_after' => $throttle['retry_after']],
            429
        );
        exit;
    }
    http_response_code(429);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Too Many Requests';
    exit;
}

if ($isAjax) {
    /* 软登出：保留会话并轮换 ID，返回新的 CSRF token 供页内登录浮层立即使用 */
    Auth::logout(false);
    Response::json(['ok' => true, 'csrf_token' => Csrf::token()]);
    exit;
}

Auth::logout();

header('Location: login.php?logged_out=1', true, 303);
exit;
