<?php
use Gallery\Api\GalleryController;
use Gallery\Api\Router;
use Gallery\Config;
use Gallery\PhotoLibrary;
use Gallery\Security\Auth;
use Gallery\Security\Headers;
use Gallery\Support\RateLimiter;
use Gallery\Support\Response;

require __DIR__ . '/src/bootstrap.php';

Headers::apply('api');

if (!Auth::isAuthenticated()) {
    Response::error('访问未授权或会话已超时，请重新登录。', 401);
    exit;
}

Auth::releaseSessionLock();

$limit = Config::getInt('api_rate_limit', 240);
$window = Config::getInt('api_rate_window', 60);
$throttle = RateLimiter::check('api:' . Auth::clientIp(), $limit, $window);

if (!$throttle['allowed']) {
    if (!headers_sent()) {
        header('Retry-After: ' . $throttle['retry_after']);
    }
    Response::error('请求过于频繁，请稍后再试。', 429);
    exit;
}

$router = new Router(new GalleryController(new PhotoLibrary()));

$action = isset($_GET['action']) ? (string) $_GET['action'] : '';

if ($action === 'getOpsOverview' && !empty($_GET['refresh'])) {
    $refreshLimit = Config::getInt('ops_refresh_rate_limit', 6);
    $refreshThrottle = RateLimiter::check('ops-refresh:' . Auth::clientIp(), $refreshLimit, 60);
    if (!$refreshThrottle['allowed']) {
        if (!headers_sent()) {
            header('Retry-After: ' . $refreshThrottle['retry_after']);
        }
        Response::error('统计刷新过于频繁，请稍后再试。', 429);
        exit;
    }
}

$router->dispatch($action, $_GET);
