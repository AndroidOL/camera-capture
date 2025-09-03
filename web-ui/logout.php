<?php
require_once 'config.php'; // 包含配置并启动会话

// 仅允许 POST 请求以防 CSRF（在无CSRF token前提下也能拦截GET触发）
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    if (!headers_sent()) {
        header('HTTP/1.1 405 Method Not Allowed');
        header('Allow: POST');
        header('Cache-Control: no-store');
        header('Content-Type: text/plain; charset=UTF-8');
    }
    echo 'Method Not Allowed';
    exit;
}

// CSRF 校验
$token = $_POST['csrf_token'] ?? '';
if (!function_exists('validate_csrf_token')) {
    if (!headers_sent()) {
        header('HTTP/1.1 500 Internal Server Error');
        header('Cache-Control: no-store');
        header('Content-Type: text/plain; charset=UTF-8');
    }
    echo 'Server CSRF validator missing';
    exit;
}
if (!validate_csrf_token($token)) {
    if (!headers_sent()) {
        header('HTTP/1.1 403 Forbidden');
        header('Cache-Control: no-store');
        header('Content-Type: text/plain; charset=UTF-8');
    }
    echo 'Invalid CSRF token';
    exit;
}

destroy_authentication_session(); // 调用销毁会话的函数

// 303 重定向至登录页
header('Cache-Control: no-store');
header('Location: login.php?logged_out=true', true, 303);
exit;
?>
