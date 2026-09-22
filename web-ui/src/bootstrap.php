<?php
define('GALLERY_ROOT', dirname(__DIR__));

spl_autoload_register(function ($class) {
    $prefix = 'Gallery\\';
    $length = strlen($prefix);
    if (strncmp($class, $prefix, $length) !== 0) {
        return;
    }
    $relative = substr($class, $length);
    $file = GALLERY_ROOT . '/src/' . str_replace('\\', '/', $relative) . '.php';
    if (is_file($file)) {
        require $file;
    }
});

Gallery\Config::load(GALLERY_ROOT . '/config.php');

$galleryTimezone = Gallery\Config::get('timezone');
if (is_string($galleryTimezone) && $galleryTimezone !== '') {
    @date_default_timezone_set($galleryTimezone);
}

error_reporting(E_ALL);
ini_set('display_errors', '0');
ini_set('log_errors', '1');

set_error_handler(function ($severity, $message, $file, $line) {
    if (!(error_reporting() & $severity)) {
        return false;
    }
    error_log(sprintf('[gallery] PHP error: %s in %s:%d', $message, $file, $line));
    return true;
});

set_exception_handler(function ($e) {
    error_log(sprintf(
        '[gallery] Uncaught %s: %s in %s:%d',
        get_class($e),
        $e->getMessage(),
        $e->getFile(),
        $e->getLine()
    ));
    if (!headers_sent()) {
        http_response_code(500);
        header('Content-Type: application/json; charset=utf-8');
    }
    echo json_encode(['error' => '服务器内部错误，请稍后重试。'], JSON_UNESCAPED_UNICODE);
});

register_shutdown_function(function () {
    $error = error_get_last();
    if ($error && in_array($error['type'], [E_ERROR, E_PARSE, E_CORE_ERROR, E_COMPILE_ERROR], true)) {
        error_log(sprintf('[gallery] Fatal: %s in %s:%d', $error['message'], $error['file'], $error['line']));
    }
});

Gallery\Security\Auth::startSession();
