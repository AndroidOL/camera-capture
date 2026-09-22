<?php
namespace Gallery;

final class Config
{
    private const DEFAULTS = [
        'password_hash' => '',
        'password_hash_file' => null,
        // 已停用：保留键位只为让运维面板能提示"你配置了明文密码，但登录不再采纳它"。
        'password' => '',
        'session_name' => 'PhotoGallerySession',
        'session_idle_timeout' => 1800,
        'session_absolute_timeout' => 43200,
        'bind_session_to_ip' => false,
        'captures_dir' => null,
        'web_path' => '/captures',
        'image_mode' => 'proxy',
        'cache_dir' => null,
        'cache_ttl' => 3600,
        'thumb_max_dimension' => 420,
        'thumb_quality' => 78,
        'api_rate_limit' => 240,
        'api_rate_window' => 60,
        'login_max_attempts' => 5,
        'login_lockout_seconds' => 300,
        'health_file' => null,
        'health_stale_seconds' => 900,
        'disk_warn_percent' => 85,
        'stats_cache_ttl' => 3600,
        'stats_recent_days' => 31,
        'trust_proxy' => false,
        'ops_refresh_rate_limit' => 6,
        'default_view' => 'gallery',
        'slideshow_speed' => 1,
        'download_enabled' => true,
        'theme_mode' => 'dark',
        'theme_accent' => 'blue',
        'monitor_initial_interval' => 1500,
        'monitor_min_interval' => 1000,
        'monitor_max_interval' => 8000,
        'timezone' => null,
    ];

    private static $values = null;

    public static function load(string $file): void
    {
        $values = self::DEFAULTS;

        if (is_file($file)) {
            $user = @include $file;
            if (is_array($user)) {
                foreach ($user as $key => $value) {
                    if (array_key_exists($key, $values) && $value !== null) {
                        $values[$key] = $value;
                    }
                }
            }
        }

        foreach ($values as $key => $current) {
            $env = getenv('GALLERY_' . strtoupper($key));
            if ($env !== false && $env !== '') {
                $values[$key] = self::cast($current, $env);
            }
        }

        self::$values = $values;
    }

    private static function cast($prototype, string $raw)
    {
        if (is_bool($prototype)) {
            return in_array(strtolower($raw), ['1', 'true', 'yes', 'on'], true);
        }
        if (is_int($prototype)) {
            return (int) $raw;
        }
        return $raw;
    }

    public static function get(string $key, $default = null)
    {
        if (self::$values === null) {
            throw new \RuntimeException('Configuration has not been loaded.');
        }
        return array_key_exists($key, self::$values) ? self::$values[$key] : $default;
    }

    public static function getInt(string $key, int $default = 0): int
    {
        $value = self::get($key, $default);
        return is_numeric($value) ? (int) $value : $default;
    }

    public static function getBool(string $key, bool $default = false): bool
    {
        $value = self::get($key, $default);
        return is_bool($value) ? $value : (bool) $value;
    }

    public static function capturesDir(): string
    {
        $dir = self::get('captures_dir');
        if (!is_string($dir) || $dir === '') {
            $dir = GALLERY_ROOT . '/captures';
        }
        return rtrim($dir, '/');
    }

    public static function cacheDir(): string
    {
        $dir = self::get('cache_dir');
        if (!is_string($dir) || $dir === '') {
            $dir = rtrim(sys_get_temp_dir(), '/') . '/photo_gallery_cache';
        }
        return rtrim($dir, '/');
    }

    public static function healthFile(): string
    {
        $file = self::get('health_file');
        if (!is_string($file) || $file === '') {
            $file = '/opt/camera/logs/health.json';
        }
        return $file;
    }

    public static function isHttps(): bool
    {
        if (!empty($_SERVER['HTTPS']) && strtolower((string) $_SERVER['HTTPS']) !== 'off') {
            return true;
        }
        if (self::getBool('trust_proxy')
            && isset($_SERVER['HTTP_X_FORWARDED_PROTO'])
            && strtolower((string) $_SERVER['HTTP_X_FORWARDED_PROTO']) === 'https') {
            return true;
        }
        return isset($_SERVER['SERVER_PORT']) && (int) $_SERVER['SERVER_PORT'] === 443;
    }

    /**
     * 密码哈希的权威来源。
     *
     * 优先读 password_hash_file（Docker secrets 场景：容器里直接挂一个文件，
     * 内容就是纯哈希）——**不经过任何 shell / compose 变量插值**。
     * 这一点很关键：bcrypt 哈希里的 `$` 在 .env / compose 插值中会被吞掉，
     * 写进 .env 会静默变成残缺值，导致"密码明明对却登不进去"。
     */
    public static function passwordHash(): string
    {
        $file = self::get('password_hash_file');
        if (is_string($file) && $file !== '' && is_readable($file)) {
            $value = trim((string) @file_get_contents($file));
            if ($value !== '') {
                return $value;
            }
        }

        return (string) self::get('password_hash');
    }

    public static function hasPassword(): bool
    {
        return self::passwordHash() !== '';
    }
}
