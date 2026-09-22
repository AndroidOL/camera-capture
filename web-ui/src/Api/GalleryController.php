<?php
namespace Gallery\Api;

use Gallery\OpsMonitor;
use Gallery\PhotoLibrary;

final class GalleryController
{
    private $library;

    public function __construct(PhotoLibrary $library)
    {
        $this->library = $library;
    }

    public function getEarliestDate(array $query): array
    {
        return ['earliestDate' => $this->library->earliestDate()];
    }

    public function getLatestDate(array $query): array
    {
        return ['latestDate' => $this->library->latestDate()];
    }

    public function getAvailableDates(array $query): array
    {
        return ['availableDates' => $this->library->availableDates()];
    }

    public function getLatestPhoto(array $query): array
    {
        return ['latest_photo' => $this->library->latestPhoto()];
    }

    public function getDailySummary(array $query): array
    {
        $date = $this->requireDate($query);
        return [
            'date' => $date,
            'hourly_previews' => $this->library->dailySummary($date),
        ];
    }

    public function getHourlySummary(array $query): array
    {
        $date = $this->requireDate($query);
        $hour = $this->requireHour($query);
        return [
            'date' => $date,
            'hour' => $hour,
            'ten_minute_previews' => $this->library->hourlySummary($date, $hour),
        ];
    }

    public function getTenMinuteSummary(array $query): array
    {
        $date = $this->requireDate($query);
        $hour = $this->requireHour($query);
        $slot = $this->requireSlot($query);
        return [
            'date' => $date,
            'hour' => $hour,
            'interval_slot' => $slot,
            'minute_previews' => $this->library->tenMinuteSummary($date, $hour, $slot),
        ];
    }

    public function getMinutePhotos(array $query): array
    {
        $date = $this->requireDate($query);
        $hour = $this->requireHour($query);
        $minute = PhotoLibrary::validateMinute(isset($query['minute']) ? $query['minute'] : null);
        if ($minute === null) {
            throw new \InvalidArgumentException('minute 参数无效或缺失。');
        }
        return [
            'date' => $date,
            'hour' => $hour,
            'minute' => $minute,
            'photos' => $this->library->minutePhotos($date, $hour, $minute),
        ];
    }

    public function getPhotoListForRange(array $query): array
    {
        $date = $this->requireDate($query);
        $hour = PhotoLibrary::validateHour(isset($query['hour']) ? $query['hour'] : null);
        $slot = PhotoLibrary::validateSlot(isset($query['interval_slot']) ? $query['interval_slot'] : null);
        $minute = PhotoLibrary::validateMinute(isset($query['minute']) ? $query['minute'] : null);

        $photos = $this->library->rangePhotos($date, $hour, $slot, $minute);

        return [
            'date' => $date,
            'hour' => $hour,
            'interval_slot' => $slot,
            'minute' => $minute,
            'photos' => $photos,
            'total_photos_in_range' => count($photos),
        ];
    }

    public function getOpsOverview(array $query): array
    {
        $refresh = isset($query['refresh']) && $query['refresh'] !== '' && $query['refresh'] !== '0';
        $ops = new OpsMonitor($this->library);
        return $ops->overview($refresh);
    }

    private function requireDate(array $query): string
    {
        $date = isset($query['date']) ? (string) $query['date'] : '';
        if ($date === '' || PhotoLibrary::validateDate($date) === null) {
            throw new \InvalidArgumentException('date 参数缺失或格式无效。');
        }
        return $date;
    }

    private function requireHour(array $query): string
    {
        $hour = PhotoLibrary::validateHour(isset($query['hour']) ? $query['hour'] : null);
        if ($hour === null) {
            throw new \InvalidArgumentException('hour 参数无效或缺失。');
        }
        return $hour;
    }

    private function requireSlot(array $query): int
    {
        $slot = PhotoLibrary::validateSlot(isset($query['interval_slot']) ? $query['interval_slot'] : null);
        if ($slot === null) {
            throw new \InvalidArgumentException('interval_slot 参数无效或缺失。');
        }
        return $slot;
    }
}
