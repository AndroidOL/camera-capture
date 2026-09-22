<?php
namespace Gallery\Api;

use Gallery\Support\Response;

final class Router
{
    private const ACTIONS = [
        'getEarliestDate',
        'getLatestDate',
        'getAvailableDates',
        'getLatestPhoto',
        'getDailySummary',
        'getHourlySummary',
        'getTenMinuteSummary',
        'getMinutePhotos',
        'getPhotoListForRange',
        'getOpsOverview',
    ];

    private $controller;

    public function __construct(GalleryController $controller)
    {
        $this->controller = $controller;
    }

    public function dispatch(string $action, array $query): void
    {
        if (!in_array($action, self::ACTIONS, true)) {
            Response::error('无效的操作指令。', 400);
            return;
        }

        try {
            Response::json($this->controller->{$action}($query));
        } catch (\InvalidArgumentException $e) {
            Response::error($e->getMessage(), 400);
        } catch (\Throwable $e) {
            error_log('[gallery] API failure in ' . $action . ': ' . $e->getMessage());
            Response::error('服务器内部错误，请稍后重试。', 500);
        }
    }
}
