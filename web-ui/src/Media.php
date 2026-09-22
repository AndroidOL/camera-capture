<?php
namespace Gallery;

final class Media
{
    public static function imageUrl(string $relative): string
    {
        if (self::isDirect()) {
            return self::webBase() . '/' . $relative;
        }
        return 'image.php?p=' . rawurlencode($relative);
    }

    public static function thumbUrl(string $relative): string
    {
        if (self::isDirect()) {
            return self::imageUrl($relative);
        }
        return 'image.php?p=' . rawurlencode($relative) . '&thumb=1';
    }

    public static function downloadUrl(string $relative): string
    {
        if (self::isDirect()) {
            return self::imageUrl($relative);
        }
        return 'image.php?p=' . rawurlencode($relative) . '&download=1';
    }

    public static function isDirect(): bool
    {
        return Config::get('image_mode') === 'direct';
    }

    private static function webBase(): string
    {
        $base = (string) Config::get('web_path', '/captures');
        if ($base === '') {
            $base = '/captures';
        }
        return rtrim($base, '/');
    }
}
