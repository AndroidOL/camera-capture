<?php
namespace Gallery\Support;

use Gallery\Config;

final class FileCache
{
    private static function dir(string $namespace): string
    {
        $dir = Config::cacheDir() . '/' . $namespace;
        if (!is_dir($dir)) {
            @mkdir($dir, 0755, true);
        }
        return $dir;
    }

    public static function get(string $key, string $namespace = 'data')
    {
        $file = self::dir($namespace) . '/' . hash('sha256', $key) . '.json';
        if (!is_file($file)) {
            return null;
        }
        $raw = @file_get_contents($file);
        if ($raw === false || $raw === '') {
            return null;
        }
        $payload = json_decode($raw, true);
        if (!is_array($payload) || !array_key_exists('value', $payload)) {
            return null;
        }
        $expires = isset($payload['expires']) ? $payload['expires'] : null;
        if ($expires !== null && $expires < time()) {
            @unlink($file);
            return null;
        }
        return $payload['value'];
    }

    public static function set(string $key, $value, int $ttl = 0, string $namespace = 'data'): void
    {
        $file = self::dir($namespace) . '/' . hash('sha256', $key) . '.json';
        if ($ttl <= 0) {
            $ttl = Config::getInt('cache_ttl', 3600);
        }
        $payload = [
            'expires' => $ttl > 0 ? time() + $ttl : null,
            'value' => $value,
        ];
        @file_put_contents($file, json_encode($payload, JSON_UNESCAPED_UNICODE), LOCK_EX);
    }

    public static function remember(string $key, int $ttl, callable $producer, string $namespace = 'data')
    {
        $cached = self::get($key, $namespace);
        if ($cached !== null) {
            return $cached;
        }
        $value = $producer();
        self::set($key, $value, $ttl, $namespace);
        return $value;
    }
}
