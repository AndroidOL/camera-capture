<?php
namespace Gallery\Security;

use Gallery\Config;

final class Auth
{
    public static function startSession(): void
    {
        if (session_status() === PHP_SESSION_ACTIVE) {
            return;
        }

        ini_set('session.use_strict_mode', '1');
        ini_set('session.use_only_cookies', '1');
        ini_set('session.cookie_httponly', '1');

        $secure = Config::isHttps();
        $cookie = session_get_cookie_params();
        $base = (string) Config::get('session_name');

        session_name($secure ? '__Host-' . $base : $base);
        session_set_cookie_params([
            'lifetime' => 0,
            'path' => '/',
            'domain' => '',
            'secure' => $secure,
            'httponly' => true,
            'samesite' => 'Lax',
        ]);

        session_start();
    }

    public static function isAuthenticated(): bool
    {
        if (empty($_SESSION['auth']) || $_SESSION['auth'] !== true) {
            return false;
        }

        $now = time();
        $idle = Config::getInt('session_idle_timeout');
        $absolute = Config::getInt('session_absolute_timeout');

        if ($idle > 0 && isset($_SESSION['last_activity']) && ($now - (int) $_SESSION['last_activity']) > $idle) {
            self::logout();
            return false;
        }
        if ($absolute > 0 && isset($_SESSION['created_at']) && ($now - (int) $_SESSION['created_at']) > $absolute) {
            self::logout();
            return false;
        }
        if (Config::getBool('bind_session_to_ip')
            && isset($_SESSION['ip'])
            && $_SESSION['ip'] !== self::clientIp()) {
            self::logout();
            return false;
        }

        $_SESSION['last_activity'] = $now;
        return true;
    }

    public static function attempt(string $password): bool
    {
        $hash = Config::passwordHash();

        if ($hash === '' || !password_verify($password, $hash)) {
            return false;
        }

        self::login();
        return true;
    }

    private static function login(): void
    {
        session_regenerate_id(true);

        $_SESSION['auth'] = true;
        $_SESSION['created_at'] = time();
        $_SESSION['last_activity'] = time();
        $_SESSION['ip'] = self::clientIp();
        $_SESSION['user_agent'] = isset($_SERVER['HTTP_USER_AGENT']) ? substr((string) $_SERVER['HTTP_USER_AGENT'], 0, 255) : '';
    }

    public static function logout(): void
    {
        $_SESSION = [];

        if (session_status() === PHP_SESSION_ACTIVE && ini_get('session.use_cookies')) {
            $params = session_get_cookie_params();
            setcookie(
                session_name(),
                '',
                [
                    'expires' => time() - 42000,
                    'path' => isset($params['path']) ? $params['path'] : '/',
                    'domain' => isset($params['domain']) ? $params['domain'] : '',
                    'secure' => !empty($params['secure']),
                    'httponly' => true,
                    'samesite' => 'Lax',
                ]
            );
        }

        if (session_status() === PHP_SESSION_ACTIVE) {
            session_destroy();
        }
    }

    public static function clientIp(): string
    {
        return isset($_SERVER['REMOTE_ADDR']) ? (string) $_SERVER['REMOTE_ADDR'] : 'unknown';
    }

    public static function releaseSessionLock(): void
    {
        if (session_status() === PHP_SESSION_ACTIVE) {
            session_write_close();
        }
    }
}
