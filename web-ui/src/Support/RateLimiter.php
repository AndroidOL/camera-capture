<?php
namespace Gallery\Support;

use Gallery\Config;

final class RateLimiter
{
    private static function dir(): string
    {
        $dir = Config::cacheDir() . '/ratelimit';
        if (!is_dir($dir)) {
            @mkdir($dir, 0755, true);
        }
        return $dir;
    }

    /**
     * @return array{allowed:bool,remaining:int,retry_after:int}
     */
    public static function check(string $key, int $limit, int $window): array
    {
        $limit = max(1, $limit);
        $window = max(1, $window);
        $file = self::dir() . '/' . hash('sha256', $key) . '.json';
        $now = time();

        $handle = @fopen($file, 'c+');
        if ($handle === false) {
            return ['allowed' => true, 'remaining' => $limit, 'retry_after' => 0];
        }

        @flock($handle, LOCK_EX);
        $raw = stream_get_contents($handle);
        $data = json_decode($raw === false ? '' : $raw, true);

        if (!is_array($data) || !isset($data['start'], $data['count']) || ($now - (int) $data['start']) >= $window) {
            $data = ['start' => $now, 'count' => 0];
        }

        $data['count'] = (int) $data['count'] + 1;
        $allowed = $data['count'] <= $limit;
        $retryAfter = $allowed ? 0 : max(1, $window - ($now - (int) $data['start']));

        rewind($handle);
        ftruncate($handle, 0);
        fwrite($handle, json_encode($data));
        fflush($handle);
        @flock($handle, LOCK_UN);
        fclose($handle);

        return [
            'allowed' => $allowed,
            'remaining' => max(0, $limit - (int) $data['count']),
            'retry_after' => $retryAfter,
        ];
    }

    public static function reset(string $key): void
    {
        @unlink(self::dir() . '/' . hash('sha256', $key) . '.json');
    }
}
