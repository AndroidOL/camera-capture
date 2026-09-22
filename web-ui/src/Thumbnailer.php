<?php
namespace Gallery;

final class Thumbnailer
{
    public static function available(): bool
    {
        return function_exists('imagecreatefromjpeg')
            && function_exists('imagecreatetruecolor')
            && function_exists('imagecopyresampled')
            && function_exists('imagejpeg');
    }

    public static function forFile(string $sourcePath, ?int $maxDimension = null, ?int $quality = null): ?string
    {
        if (!self::available() || !is_file($sourcePath)) {
            return null;
        }

        $max = $maxDimension === null ? Config::getInt('thumb_max_dimension', 420) : $maxDimension;
        $quality = $quality === null ? Config::getInt('thumb_quality', 78) : $quality;
        if ($max < 32) {
            $max = 32;
        }
        if ($quality < 10 || $quality > 100) {
            $quality = 78;
        }

        $mtime = @filemtime($sourcePath) ?: 0;
        $directory = Config::cacheDir() . '/thumbs';
        $target = $directory . '/' . hash('sha256', $sourcePath . '|' . $mtime . '|' . $max . '|' . $quality) . '.jpg';

        if (is_file($target) && (@filemtime($target) ?: 0) >= $mtime) {
            return $target;
        }

        $info = @getimagesize($sourcePath);
        if ($info === false || empty($info[0]) || empty($info[1])) {
            return null;
        }

        $width = (int) $info[0];
        $height = (int) $info[1];
        $ratio = min($max / $width, $max / $height);
        if ($ratio >= 1) {
            $newWidth = $width;
            $newHeight = $height;
        } else {
            $newWidth = max(1, (int) round($width * $ratio));
            $newHeight = max(1, (int) round($height * $ratio));
        }

        $source = @imagecreatefromjpeg($sourcePath);
        if ($source === false) {
            return null;
        }
        $canvas = @imagecreatetruecolor($newWidth, $newHeight);
        if ($canvas === false) {
            imagedestroy($source);
            return null;
        }

        @imagecopyresampled($canvas, $source, 0, 0, 0, 0, $newWidth, $newHeight, $width, $height);

        if (!is_dir($directory)) {
            @mkdir($directory, 0755, true);
        }

        $ok = @imagejpeg($canvas, $target, $quality);
        imagedestroy($source);
        imagedestroy($canvas);

        if (!$ok) {
            return null;
        }

        @chmod($target, 0644);
        return $target;
    }
}
