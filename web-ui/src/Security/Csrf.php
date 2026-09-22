<?php
namespace Gallery\Security;

final class Csrf
{
    private const KEY = 'csrf_token';

    public static function token(): string
    {
        if (empty($_SESSION[self::KEY]) || !is_string($_SESSION[self::KEY])) {
            $_SESSION[self::KEY] = bin2hex(random_bytes(32));
        }
        return $_SESSION[self::KEY];
    }

    public static function validate($token): bool
    {
        return isset($_SESSION[self::KEY])
            && is_string($_SESSION[self::KEY])
            && is_string($token)
            && hash_equals($_SESSION[self::KEY], $token);
    }

    public static function field(): string
    {
        return '<input type="hidden" name="csrf_token" value="'
            . htmlspecialchars(self::token(), ENT_QUOTES, 'UTF-8') . '">';
    }
}
