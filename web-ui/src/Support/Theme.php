<?php

declare(strict_types=1);

namespace Gallery\Support;

use Gallery\Config;

/**
 * Resolves the appearance (mode + accent) on the server so the very first paint
 * is already correct — no flash of the wrong theme.
 *
 * Source of truth is the browser cookie (written by theme.js); config provides
 * the default for first-time visitors.
 */
final class Theme
{
    public const COOKIE_MODE = 'gallery_theme';
    public const COOKIE_ACCENT = 'gallery_accent';

    private const MODES = ['dark', 'light'];

    private const ACCENTS = [
        'blue' => '蓝',
        'teal' => '青',
        'violet' => '紫',
        'amber' => '琥珀',
        'rose' => '玫红',
        'green' => '绿',
    ];

    public static function mode(): string
    {
        $cookie = isset($_COOKIE[self::COOKIE_MODE]) ? (string) $_COOKIE[self::COOKIE_MODE] : '';
        if (in_array($cookie, self::MODES, true)) {
            return $cookie;
        }

        $configured = (string) Config::get('theme_mode', 'dark');

        return in_array($configured, self::MODES, true) ? $configured : 'dark';
    }

    public static function accent(): string
    {
        $cookie = isset($_COOKIE[self::COOKIE_ACCENT]) ? (string) $_COOKIE[self::COOKIE_ACCENT] : '';
        if (array_key_exists($cookie, self::ACCENTS)) {
            return $cookie;
        }

        $configured = (string) Config::get('theme_accent', 'blue');

        return array_key_exists($configured, self::ACCENTS) ? $configured : 'blue';
    }

    /**
     * @return array<string, string> accent id => display label
     */
    public static function accents(): array
    {
        return self::ACCENTS;
    }

    public static function isValidAccent(string $accent): bool
    {
        return array_key_exists($accent, self::ACCENTS);
    }
}
