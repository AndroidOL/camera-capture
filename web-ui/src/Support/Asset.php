<?php
namespace Gallery\Support;

final class Asset
{
    public static function url(string $path): string
    {
        $full = GALLERY_ROOT . '/' . ltrim($path, '/');
        $version = is_file($full) ? (string) filemtime($full) : '0';
        return $path . '?v=' . $version;
    }
}
