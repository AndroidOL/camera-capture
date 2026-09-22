<?php
use Gallery\Config;
use Gallery\PhotoLibrary;
use Gallery\Security\Auth;
use Gallery\Security\Headers;
use Gallery\Thumbnailer;

require __DIR__ . '/src/bootstrap.php';

Headers::apply('image');

if (!Auth::isAuthenticated()) {
    http_response_code(401);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Unauthorized';
    exit;
}

Auth::releaseSessionLock();

$library = new PhotoLibrary();
$relative = isset($_GET['p']) ? (string) $_GET['p'] : '';
$path = $library->resolve($relative);

if ($path === null) {
    http_response_code(404);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Not Found';
    exit;
}

$wantsThumb = isset($_GET['thumb']) && $_GET['thumb'] !== '' && $_GET['thumb'] !== '0';
$wantsDownload = isset($_GET['download']) && $_GET['download'] !== '' && $_GET['download'] !== '0'
    && Config::getBool('download_enabled', true);

if (function_exists('finfo_open')) {
    $finfo = finfo_open(FILEINFO_MIME_TYPE);
    if ($finfo !== false) {
        $mime = finfo_file($finfo, $path);
        finfo_close($finfo);
        if ($mime === false || strncmp((string) $mime, 'image/jpeg', 10) !== 0) {
            http_response_code(415);
            header('Content-Type: text/plain; charset=utf-8');
            echo 'Unsupported Media Type';
            exit;
        }
    }
}

$servePath = $path;
if ($wantsThumb) {
    $thumbnail = Thumbnailer::forFile($path);
    if ($thumbnail !== null) {
        $servePath = $thumbnail;
    }
}

$mtime = @filemtime($servePath) ?: 0;
$size = @filesize($servePath) ?: 0;
$etag = '"' . hash('sha256', $servePath . '|' . $mtime . '|' . $size) . '"';

header('Content-Type: image/jpeg');
header('Cache-Control: private, max-age=86400');
header('ETag: ' . $etag);
header('Last-Modified: ' . gmdate('D, d M Y H:i:s', $mtime) . ' GMT');

if (!$wantsDownload && isset($_SERVER['HTTP_IF_NONE_MATCH'])) {
    if (trim((string) $_SERVER['HTTP_IF_NONE_MATCH']) === $etag) {
        http_response_code(304);
        exit;
    }
}

if ($wantsDownload) {
    header('Content-Disposition: attachment; filename="' . basename($path) . '"');
} else {
    header('Content-Disposition: inline');
}
header('Content-Length: ' . $size);

while (ob_get_level() > 0) {
    ob_end_clean();
}

readfile($servePath);
