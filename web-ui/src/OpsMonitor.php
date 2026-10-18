<?php
namespace Gallery;

use Gallery\Support\FileCache;

final class OpsMonitor
{
    private $library;

    public function __construct(PhotoLibrary $library)
    {
        $this->library = $library;
    }

    public function overview(bool $refresh = false): array
    {
        $cacheKey = 'ops_overview:' . $this->library->baseDir();

        /* 运维面板会被反复切换进入；磁盘探测（尤其是网络/FUSE 挂载）可能很慢，
           因此整块结果做短 TTL 缓存，让"回到运维页"始终是即时的。 */
        if (!$refresh) {
            $cached = FileCache::get($cacheKey, 'ops');
            if (is_array($cached)) {
                $cached['from_cache'] = true;
                return $cached;
            }
        }

        try {
            $service = $this->service();
            $storage = $this->storage();
            $security = $this->security();

            try {
                $library = $this->library->libraryStats($refresh);
            } catch (\Throwable $e) {
                error_log('[gallery] library stats failed: ' . $e->getMessage());
                $library = $this->emptyLibraryStats();
                $library['warnings'] = ['照片库统计失败：' . $e->getMessage()];
            }

            $warnings = array_merge(
                isset($security['warnings']) ? $security['warnings'] : [],
                isset($storage['warnings']) ? $storage['warnings'] : [],
                isset($service['warnings']) ? $service['warnings'] : [],
                isset($library['warnings']) ? $library['warnings'] : []
            );

            $payload = [
                'service' => $service,
                'storage' => $storage,
                'library' => $library,
                'security' => $security,
                'warnings' => $warnings,
                'generated_at' => time(),
                'from_cache' => false,
                'degraded' => !empty($library['warnings']),
            ];

            FileCache::set($cacheKey, $payload, max(5, Config::getInt('ops_cache_ttl', 20)), 'ops');
            return $payload;
        } catch (\Throwable $e) {
            /* 极端情况下（磁盘/健康文件异常）退回上一次成功结果，面板至少还能看 */
            error_log('[gallery] ops overview failed: ' . $e->getMessage());
            $stale = FileCache::getStale($cacheKey, 'ops');
            if (is_array($stale)) {
                $stale['from_cache'] = true;
                $stale['degraded'] = true;
                $stale['warnings'] = isset($stale['warnings']) && is_array($stale['warnings'])
                    ? $stale['warnings']
                    : [];
                $stale['warnings'][] = '本次刷新失败，展示的是上一次成功结果。';
                return $stale;
            }
            throw $e;
        }
    }

    private function emptyLibraryStats(): array
    {
        return [
            'months' => 0,
            'dates' => 0,
            'total_files' => 0,
            'total_bytes' => 0,
            'earliest' => null,
            'latest' => null,
            'by_month' => [],
            'recent_days' => [],
            'window_days' => max(1, Config::getInt('stats_recent_days', 31)),
            'computed_at' => time(),
        ];
    }

    private function security(): array
    {
        $hash = Config::passwordHash();
        $plain = (string) Config::get('password');

        if ($hash !== '') {
            $passwordMode = 'hash';
        } elseif ($plain !== '') {
            $passwordMode = 'plaintext';
        } else {
            $passwordMode = 'none';
        }

        $https = Config::isHttps();
        $imageMode = Config::get('image_mode') === 'direct' ? 'direct' : 'proxy';

        $warnings = [];
        if ($passwordMode === 'plaintext') {
            $warnings[] = '检测到明文密码配置，但明文登录已停用（不会被采纳），请改用 password_hash。';
        }
        if ($passwordMode === 'none') {
            $warnings[] = '尚未设置访问密码，任何人都可以访问。';
        }
        if (!$https) {
            $warnings[] = '当前非 HTTPS，密码与会话 Cookie 会以明文传输。';
        }
        if ($imageMode === 'direct') {
            $warnings[] = '图片为直链模式，请确认已在 Web 服务器层保护 captures 目录。';
        }

        return [
            'password_mode' => $passwordMode,
            'https' => $https,
            'image_mode' => $imageMode,
            'cookie_secure' => $https,
            'cookie_prefix' => $https ? '__Host-' : '（非 HTTPS 无前缀）',
            'trust_proxy' => Config::getBool('trust_proxy'),
            'robots_blocked' => is_file(GALLERY_ROOT . '/robots.txt'),
            'warnings' => $warnings,
        ];
    }

    private function service(): array
    {
        $file = Config::healthFile();

        $payload = [
            'available' => false,
            'state' => 'unknown',
            'health_file' => $file,
            'boot_id' => null,
            'reported_at' => null,
            'age_seconds' => null,
            'interval' => null,
            'fourcc' => null,
            'read_failures' => null,
            'imwrite_failures' => null,
            'disk_cleanup_batches' => null,
            'last_saved' => null,
            'last_saved_at' => null,
            'warnings' => [],
        ];

        if ($file === '' || !is_file($file) || !is_readable($file)) {
            $payload['warnings'][] = $file === ''
                ? '未接入采集服务：尚未配置 health_file；不监控采集端可忽略。'
                : '未接入采集服务：未找到 health.json（' . $file . '）；不监控采集端可忽略。';

            return $payload;
        }

        $raw = @file_get_contents($file);
        if ($raw === false || $raw === '') {
            return $payload;
        }

        $data = json_decode($raw, true);
        if (!is_array($data)) {
            return $payload;
        }

        $payload['available'] = true;

        $reportedAt = isset($data['ts']) && is_numeric($data['ts']) ? (float) $data['ts'] : null;
        $payload['reported_at'] = $reportedAt;

        if ($reportedAt !== null) {
            $age = max(0, time() - (int) $reportedAt);
            $payload['age_seconds'] = $age;
            $payload['state'] = $age <= Config::getInt('health_stale_seconds', 900) ? 'running' : 'stale';
        }

        $lastSaved = isset($data['last_saved']) && is_string($data['last_saved']) && $data['last_saved'] !== ''
            ? basename($data['last_saved'])
            : null;
        $payload['last_saved'] = $lastSaved;
        if ($lastSaved !== null) {
            $parsed = PhotoLibrary::parseFilename($lastSaved);
            if ($parsed !== null) {
                $payload['last_saved_at'] = sprintf(
                    '%s-%s-%s %s:%s:%s',
                    $parsed['year'],
                    $parsed['month'],
                    $parsed['day'],
                    $parsed['hour'],
                    $parsed['minute'],
                    $parsed['second']
                );
            }
        }

        $payload['boot_id'] = isset($data['boot_id']) ? (string) $data['boot_id'] : null;
        $payload['interval'] = isset($data['interval']) && is_numeric($data['interval']) ? (float) $data['interval'] : null;
        $payload['fourcc'] = isset($data['fourcc']) ? (string) $data['fourcc'] : null;
        $payload['read_failures'] = isset($data['read_failures']) ? (int) $data['read_failures'] : null;
        $payload['imwrite_failures'] = isset($data['imwrite_failures']) ? (int) $data['imwrite_failures'] : null;
        $payload['disk_cleanup_batches'] = isset($data['disk_cleanup_batches']) ? (int) $data['disk_cleanup_batches'] : null;

        return $payload;
    }

    private function storage(): array
    {
        $path = $this->library->baseDir();
        $warn = Config::getInt('disk_warn_percent', 85);

        /* 目录可能因为卷没挂上而不存在 —— 这是 Docker 部署最常见的坑，
           明确报出来，否则前端只会显示"没有照片"，很难定位。 */
        $exists = is_dir($path);
        $readable = $exists && is_readable($path);

        $warnings = [];
        if (!$exists) {
            $warnings[] = '照片库目录不存在：' . $path
                . ' —— Docker 部署请确认卷映射，并用 GALLERY_CAPTURES_DIR 指向容器内的挂载点。';
        } elseif (!$readable) {
            $warnings[] = '照片库目录不可读：' . $path . ' —— 请检查挂载目录的权限。';
        }

        $total = null;
        $free = null;

        if (function_exists('disk_total_space')) {
            $value = @disk_total_space($path);
            if ($value !== false) {
                $total = (float) $value;
            }
        }
        if (function_exists('disk_free_space')) {
            $value = @disk_free_space($path);
            if ($value !== false) {
                $free = (float) $value;
            }
        }

        $used = ($total !== null && $free !== null) ? max(0.0, $total - $free) : null;
        $percent = ($total !== null && $total > 0 && $used !== null) ? round($used / $total * 100, 1) : null;

        $status = 'unknown';
        if ($percent !== null) {
            $status = $percent >= $warn ? 'warning' : 'ok';
        }

        return [
            'path' => $path,
            'path_exists' => $exists,
            'path_readable' => $readable,
            'total_bytes' => $total,
            'free_bytes' => $free,
            'used_bytes' => $used,
            'used_percent' => $percent,
            'warn_percent' => $warn,
            'status' => $status,
            'warnings' => $warnings,
        ];
    }
}
