<?php
use Gallery\Security\Auth;
use Gallery\Security\Csrf;
use Gallery\Security\Headers;

require __DIR__ . '/src/bootstrap.php';

Headers::apply('page');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    header('Allow: POST');
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Method Not Allowed';
    exit;
}

if (!Csrf::validate(isset($_POST['csrf_token']) ? $_POST['csrf_token'] : null)) {
    http_response_code(403);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Invalid CSRF token';
    exit;
}

Auth::logout();

header('Location: login.php?logged_out=1', true, 303);
exit;
