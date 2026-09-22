<?php
namespace Gallery\Security;

use Gallery\Config;

final class Headers
{
    public static function apply(string $context): void
    {
        if (headers_sent()) {
            return;
        }

        header('X-Content-Type-Options: nosniff');
        header('X-Frame-Options: DENY');
        header('Referrer-Policy: no-referrer');
        header('X-Robots-Tag: noindex, nofollow, noarchive, nosnippet');
        header('Cross-Origin-Resource-Policy: same-origin');
        header('Cross-Origin-Opener-Policy: same-origin');
        header('X-Permitted-Cross-Domain-Policies: none');
        header('Permissions-Policy: geolocation=(), microphone=(), camera=(), payment=(), usb=()');

        $https = Config::isHttps();
        if ($https) {
            header('Strict-Transport-Security: max-age=31536000; includeSubDomains');
        }

        if ($context === 'image') {
            return;
        }

        header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
        header('Pragma: no-cache');
        header('Expires: 0');

        $csp = "default-src 'self'; base-uri 'none'; object-src 'none'; "
            . "frame-ancestors 'none'; form-action 'self'; img-src 'self' data:; "
            . "style-src 'self'; script-src 'self'; connect-src 'self'; font-src 'self'";
        if ($https) {
            $csp .= '; upgrade-insecure-requests';
        }
        header('Content-Security-Policy: ' . $csp);
    }
}
