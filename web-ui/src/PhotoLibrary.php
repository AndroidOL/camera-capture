<?php
namespace Gallery;

use Gallery\Support\FileCache;

final class PhotoLibrary
{
    private const FILE_PATTERN = '/^capture_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(?:_(\d+))?\.(jpe?g)$/i';
    private const RELATIVE_PATTERN = '#^\d{4}-\d{2}/\d{2}/capture_[A-Za-z0-9_\-]+\.jpe?g$#i';

    private $baseDir;
    private $dayIndex = [];

    public function __construct(?string $baseDir = null)
    {
        $this->baseDir = rtrim($baseDir === null ? Config::capturesDir() : $baseDir, '/');
    }

    public function baseDir(): string
    {
        return $this->baseDir;
    }

    public function isAvailable(): bool
    {
        return is_dir($this->baseDir);
    }

    public static function validateDate(string $date): ?array
    {
        if (!preg_match('/^(\d{4})-(\d{2})-(\d{2})$/', $date, $m)) {
            return null;
        }
        if (!checkdate((int) $m[2], (int) $m[3], (int) $m[1])) {
            return null;
        }
        return [$m[1], $m[2], $m[3]];
    }

    public static function validateHour($value): ?string
    {
        if ($value === null || $value === '' || !is_numeric($value)) {
            return null;
        }
        $hour = (int) $value;
        return ($hour >= 0 && $hour <= 23) ? sprintf('%02d', $hour) : null;
    }

    public static function validateMinute($value): ?string
    {
        if ($value === null || $value === '' || !is_numeric($value)) {
            return null;
        }
        $minute = (int) $value;
        return ($minute >= 0 && $minute <= 59) ? sprintf('%02d', $minute) : null;
    }

    public static function validateSlot($value): ?int
    {
        if ($value === null || $value === '' || !is_numeric($value)) {
            return null;
        }
        $slot = (int) $value;
        return ($slot >= 0 && $slot <= 5) ? $slot : null;
    }

    public static function parseFilename(string $filename): ?array
    {
        if (!preg_match(self::FILE_PATTERN, $filename, $m)) {
            return null;
        }
        return [
            'year' => $m[1],
            'month' => $m[2],
            'day' => $m[3],
            'hour' => $m[4],
            'minute' => $m[5],
            'second' => $m[6],
        ];
    }

    public function resolve(string $relative): ?string
    {
        $relative = str_replace('\\', '/', trim($relative));
        if ($relative === '' || strpos($relative, "\0") !== false) {
            return null;
        }
        if (!preg_match(self::RELATIVE_PATTERN, $relative)) {
            return null;
        }

        $baseReal = realpath($this->baseDir);
        $target = realpath($this->baseDir . '/' . $relative);
        if ($baseReal === false || $target === false || !is_file($target)) {
            return null;
        }
        if (strncmp($target, $baseReal . DIRECTORY_SEPARATOR, strlen($baseReal) + 1) !== 0) {
            return null;
        }
        return $target;
    }

    public function earliestDate(): ?string
    {
        foreach ($this->monthDirs() as $month) {
            foreach ($this->dayDirs($month) as $day) {
                $date = $month . '-' . $day;
                if ($this->hasPhoto($date)) {
                    return $date;
                }
            }
        }
        return null;
    }

    public function latestDate(): ?string
    {
        $months = array_reverse($this->monthDirs());
        foreach ($months as $month) {
            $days = array_reverse($this->dayDirs($month));
            foreach ($days as $day) {
                $date = $month . '-' . $day;
                if ($this->hasPhoto($date)) {
                    return $date;
                }
            }
        }
        return null;
    }

    public function availableDates(): array
    {
        $key = 'available_dates:' . $this->baseDir;
        $cached = FileCache::get($key, 'index');
        if (is_array($cached)) {
            return $cached;
        }

        $dates = [];
        foreach ($this->monthDirs() as $month) {
            foreach ($this->dayDirs($month) as $day) {
                $date = $month . '-' . $day;
                if ($this->hasPhoto($date)) {
                    $dates[] = $date;
                }
            }
        }

        FileCache::set($key, $dates, 300, 'index');
        return $dates;
    }

    public function latestPhoto(): ?array
    {
        $months = $this->monthDirs();
        if (!$months) {
            return null;
        }
        $month = end($months);

        $days = $this->dayDirs($month);
        if (!$days) {
            return null;
        }
        $day = end($days);
        $date = $month . '-' . $day;

        $dayPath = $this->baseDir . '/' . $month . '/' . $day;
        $mtime = @filemtime($dayPath) ?: 0;
        $cacheKey = 'latest_photo:' . $dayPath;
        $cached = FileCache::get($cacheKey, 'index');
        if (is_array($cached) && isset($cached['mtime']) && $cached['mtime'] === $mtime) {
            return isset($cached['photo']) ? $cached['photo'] : null;
        }

        $photo = null;
        $index = $this->loadDayIndex($date);
        if ($index !== null && !empty($index['files'])) {
            $names = array_keys($index['files']);
            $photo = $this->photoInfo($date, (string) end($names));
        }

        FileCache::set($cacheKey, ['mtime' => $mtime, 'photo' => $photo], 0, 'index');
        return $photo;
    }

    public function dailySummary(string $date): array
    {
        $index = $this->loadDayIndex($date);
        if ($index === null) {
            return [];
        }

        $items = [];
        for ($hour = 23; $hour >= 0; $hour--) {
            $key = sprintf('%02d', $hour);
            if (isset($index['firstByHour'][$key])) {
                $count = isset($index['countByHour'][$key]) ? $index['countByHour'][$key] : 0;
                $items[] = array_merge(
                    ['hour' => $key, 'count' => $count],
                    $this->photoInfo($date, $index['firstByHour'][$key])
                );
            }
        }
        return $items;
    }

    public function hourlySummary(string $date, string $hour): array
    {
        $index = $this->loadDayIndex($date);
        if ($index === null) {
            return [];
        }

        $items = [];
        for ($slot = 5; $slot >= 0; $slot--) {
            $start = $slot * 10;
            $slotCount = 0;
            $first = null;
            for ($minute = $start; $minute <= $start + 9; $minute++) {
                $key = $hour . sprintf('%02d', $minute);
                if (!isset($index['listByMinute'][$key])) {
                    continue;
                }
                $slotCount += count($index['listByMinute'][$key]);
                if ($first === null) {
                    $first = $index['firstByMinute'][$key];
                }
            }
            if ($first !== null) {
                $items[] = array_merge(
                    [
                        'interval_slot' => $slot,
                        'label' => sprintf('%s:%02d - %s:%02d', $hour, $start, $hour, $start + 9),
                        'count' => $slotCount,
                    ],
                    $this->photoInfo($date, $first)
                );
            }
        }
        return $items;
    }

    public function tenMinuteSummary(string $date, string $hour, int $slot): array
    {
        $index = $this->loadDayIndex($date);
        if ($index === null) {
            return [];
        }

        $items = [];
        $start = $slot * 10;
        for ($offset = 9; $offset >= 0; $offset--) {
            $minute = sprintf('%02d', $start + $offset);
            $key = $hour . $minute;
            if (isset($index['firstByMinute'][$key])) {
                $count = isset($index['listByMinute'][$key]) ? count($index['listByMinute'][$key]) : 0;
                $items[] = array_merge(
                    ['minute' => $minute, 'count' => $count],
                    $this->photoInfo($date, $index['firstByMinute'][$key])
                );
            }
        }
        return $items;
    }

    public function minutePhotos(string $date, string $hour, string $minute): array
    {
        $index = $this->loadDayIndex($date);
        if ($index === null) {
            return [];
        }

        $key = $hour . $minute;
        $names = isset($index['listByMinute'][$key]) ? $index['listByMinute'][$key] : [];
        $items = [];
        foreach (array_reverse($names) as $name) {
            $items[] = $this->photoInfo($date, $name);
        }
        return $items;
    }

    public function rangePhotos(string $date, ?string $hour, ?int $slot, ?string $minute): array
    {
        $index = $this->loadDayIndex($date);
        if ($index === null) {
            return [];
        }

        $items = [];
        foreach ($index['files'] as $name => $hhmmss) {
            if ($hour !== null) {
                if (substr($hhmmss, 0, 2) !== $hour) {
                    continue;
                }
                if ($minute !== null) {
                    if (substr($hhmmss, 0, 4) !== $hour . $minute) {
                        continue;
                    }
                } elseif ($slot !== null) {
                    $mm = (int) substr($hhmmss, 2, 2);
                    if ($mm < $slot * 10 || $mm > $slot * 10 + 9) {
                        continue;
                    }
                }
            }
            $items[] = $this->photoInfo($date, $name);
        }
        return $items;
    }

    private function photoInfo(string $date, string $filename): array
    {
        $relative = substr($date, 0, 7) . '/' . substr($date, 8, 2) . '/' . $filename;
        $parsed = self::parseFilename($filename);

        $time = null;
        $epoch = null;
        if ($parsed !== null) {
            $time = sprintf(
                '%s-%s-%s %s:%s:%s',
                $parsed['year'],
                $parsed['month'],
                $parsed['day'],
                $parsed['hour'],
                $parsed['minute'],
                $parsed['second']
            );
            $stamp = strtotime($time);
            $epoch = $stamp === false ? null : $stamp;
        }

        $size = @filesize($this->baseDir . '/' . $relative);

        return [
            'filename' => $filename,
            'filesize' => $size === false ? null : $size,
            'time' => $time,
            'epoch' => $epoch,
            'image_url' => Media::imageUrl($relative),
            'preview_image_url' => Media::thumbUrl($relative),
            'download_url' => Media::downloadUrl($relative),
        ];
    }

    public function libraryStats(bool $refresh = false): array
    {
        $byMonth = [];
        $recentDays = [];
        $months = 0;
        $totalFiles = 0;
        $totalBytes = 0;
        $earliest = null;
        $latest = null;

        foreach ($this->monthDirs() as $month) {
            $monthFiles = 0;
            $monthBytes = 0;
            $monthDays = 0;

            foreach ($this->dayDirs($month) as $day) {
                $date = $month . '-' . $day;
                $stat = $this->dayStats($this->baseDir . '/' . $month . '/' . $day, $refresh);
                if ($stat['files'] === 0) {
                    continue;
                }
                $monthDays++;
                $monthFiles += $stat['files'];
                $monthBytes += $stat['bytes'];
                $recentDays[] = ['date' => $date, 'files' => $stat['files'], 'bytes' => $stat['bytes']];
                if ($earliest === null) {
                    $earliest = $date;
                }
                $latest = $date;
            }

            if ($monthDays === 0) {
                continue;
            }

            $months++;
            $totalFiles += $monthFiles;
            $totalBytes += $monthBytes;
            $byMonth[] = [
                'month' => $month,
                'files' => $monthFiles,
                'bytes' => $monthBytes,
                'days' => $monthDays,
            ];
        }

        $limit = max(1, Config::getInt('stats_recent_days', 14));

        /* 构造连续窗口（含 0 张的日子），柱状图才是真正的时间轴而不是「有数据的那几天」 */
        $recent = [];
        $endTs = $latest !== null ? strtotime($latest . ' 12:00:00') : false;
        if ($endTs !== false) {
            $byDate = [];
            foreach ($recentDays as $entry) {
                $byDate[$entry['date']] = $entry;
            }
            for ($offset = $limit - 1; $offset >= 0; $offset--) {
                $date = date('Y-m-d', strtotime('-' . $offset . ' day', $endTs));
                $recent[] = isset($byDate[$date])
                    ? $byDate[$date]
                    : ['date' => $date, 'files' => 0, 'bytes' => 0];
            }
        }

        return [
            'months' => $months,
            'dates' => count($recentDays),
            'total_files' => $totalFiles,
            'total_bytes' => $totalBytes,
            'earliest' => $earliest,
            'latest' => $latest,
            'by_month' => array_reverse($byMonth),
            'recent_days' => $recent,
            'window_days' => $limit,
            'computed_at' => time(),
        ];
    }

    private function dayStats(string $dir, bool $refresh): array
    {
        $mtime = @filemtime($dir) ?: 0;
        $key = 'day_stats:' . $dir;

        if (!$refresh) {
            $cached = FileCache::get($key, 'stats');
            if (is_array($cached)
                && isset($cached['mtime'], $cached['files'], $cached['bytes'])
                && $cached['mtime'] === $mtime) {
                return ['files' => (int) $cached['files'], 'bytes' => (int) $cached['bytes']];
            }
        }

        $files = 0;
        $bytes = 0;
        $handle = @opendir($dir);
        if ($handle !== false) {
            while (($entry = readdir($handle)) !== false) {
                if ($entry === '.' || $entry === '..' || self::parseFilename($entry) === null) {
                    continue;
                }
                $files++;
                $size = @filesize($dir . '/' . $entry);
                if ($size !== false) {
                    $bytes += $size;
                }
            }
            closedir($handle);
        }

        FileCache::set(
            $key,
            ['mtime' => $mtime, 'files' => $files, 'bytes' => $bytes],
            Config::getInt('stats_cache_ttl', 3600),
            'stats'
        );
        return ['files' => $files, 'bytes' => $bytes];
    }

    private function loadDayIndex(string $date): ?array
    {
        if (array_key_exists($date, $this->dayIndex)) {
            return $this->dayIndex[$date];
        }

        $path = $this->baseDir . '/' . substr($date, 0, 7) . '/' . substr($date, 8, 2);
        $index = null;

        if (is_dir($path)) {
            $files = [];
            $handle = @opendir($path);
            if ($handle !== false) {
                while (($entry = readdir($handle)) !== false) {
                    if ($entry === '.' || $entry === '..') {
                        continue;
                    }
                    $parsed = self::parseFilename($entry);
                    if ($parsed !== null) {
                        $files[$entry] = $parsed['hour'] . $parsed['minute'] . $parsed['second'];
                    }
                }
                closedir($handle);
            }

            ksort($files, SORT_STRING);

            $firstByHour = [];
            $firstByMinute = [];
            $listByMinute = [];
            $countByHour = [];
            foreach ($files as $name => $hhmmss) {
                $hour = substr($hhmmss, 0, 2);
                $hourMinute = substr($hhmmss, 0, 4);
                if (!isset($firstByHour[$hour])) {
                    $firstByHour[$hour] = $name;
                }
                if (!isset($firstByMinute[$hourMinute])) {
                    $firstByMinute[$hourMinute] = $name;
                }
                $listByMinute[$hourMinute][] = $name;
                $countByHour[$hour] = isset($countByHour[$hour]) ? $countByHour[$hour] + 1 : 1;
            }

            $index = [
                'path' => $path,
                'files' => $files,
                'total' => count($files),
                'firstByHour' => $firstByHour,
                'firstByMinute' => $firstByMinute,
                'listByMinute' => $listByMinute,
                'countByHour' => $countByHour,
            ];
        }

        $this->dayIndex[$date] = $index;
        return $index;
    }

    private function hasPhoto(string $date): bool
    {
        $path = $this->baseDir . '/' . substr($date, 0, 7) . '/' . substr($date, 8, 2);
        $handle = @opendir($path);
        if ($handle === false) {
            return false;
        }
        $found = false;
        while (($entry = readdir($handle)) !== false) {
            if ($entry === '.' || $entry === '..') {
                continue;
            }
            if (self::parseFilename($entry) !== null) {
                $found = true;
                break;
            }
        }
        closedir($handle);
        return $found;
    }

    private function monthDirs(): array
    {
        $entries = @scandir($this->baseDir);
        if ($entries === false) {
            return [];
        }
        $months = [];
        foreach ($entries as $entry) {
            if (preg_match('/^\d{4}-\d{2}$/', $entry) && is_dir($this->baseDir . '/' . $entry)) {
                $months[] = $entry;
            }
        }
        sort($months, SORT_STRING);
        return $months;
    }

    private function dayDirs(string $month): array
    {
        $path = $this->baseDir . '/' . $month;
        $entries = @scandir($path);
        if ($entries === false) {
            return [];
        }
        $days = [];
        foreach ($entries as $entry) {
            if (preg_match('/^\d{2}$/', $entry) && is_dir($path . '/' . $entry)) {
                $days[] = $entry;
            }
        }
        sort($days, SORT_NUMERIC);
        return $days;
    }
}
