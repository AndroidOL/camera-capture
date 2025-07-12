<?php
// config.php

// !!! 警告：生产环境中绝不要明文存储密码 !!!
// !!! 请使用 password_hash() 生成哈希值，并使用 password_verify() 进行验证 !!!
define('GALLERY_PASSWORD', 'passowrd'); // 【请务必修改为您自己的强密码】

define('SESSION_NAME', 'PhotoGallerySession'); // 自定义会话名称
define('SESSION_TIMEOUT_DURATION', 1800); // Session超时时间 (秒), 例如30分钟 = 1800

// 开启更安全的会话设置
if (session_status() == PHP_SESSION_NONE) {
    // 设置会话cookie参数，增加安全性
    $cookieParams = session_get_cookie_params();
    session_set_cookie_params([
        'lifetime' => 0, // Cookie随浏览器关闭而失效 (Session本身的超时由 SESSION_TIMEOUT_DURATION 控制)
        'path' => $cookieParams['path'],
        'domain' => $cookieParams['domain'],
        'secure' => isset($_SERVER['HTTPS']) && $_SERVER['HTTPS'] === 'on', // 仅在HTTPS下发送
        'httponly' => true, // JS无法访问Cookie
        'samesite' => 'Lax' // SameSite属性，有助于防止CSRF
    ]);
    
    session_name(SESSION_NAME); // 使用自定义会话名
    session_start();
}

/**
 * 检查用户是否已认证且会话未超时
 * @return bool True 如果已认证且有效，否则 false
 */
function check_authentication() {
    if (!isset($_SESSION['authenticated']) || $_SESSION['authenticated'] !== true) {
        return false;
    }
    if (isset($_SESSION['last_activity']) && (time() - $_SESSION['last_activity']) > SESSION_TIMEOUT_DURATION) {
        // 会话超时，销毁会话
        unset($_SESSION['authenticated']);
        unset($_SESSION['user_ip']);
        unset($_SESSION['user_agent']);
        unset($_SESSION['last_activity']);
        // session_destroy(); // 可选：如果希望完全清除
        return false;
    }
    // 安全性增强：检查IP和User Agent是否与登录时一致 (可选，可能导致某些网络环境下问题)
    // if ($_SESSION['user_ip'] !== $_SERVER['REMOTE_ADDR'] || $_SESSION['user_agent'] !== $_SERVER['HTTP_USER_AGENT']) {
    //     unset($_SESSION['authenticated']); // IP或UA不匹配，可能是会话劫持
    //     return false;
    // }

    $_SESSION['last_activity'] = time(); // 更新用户活动时间
    return true;
}

/**
 * 认证成功后设置会话
 */
function set_authenticated_session() {
    // session_regenerate_id(true); // 登录成功后重新生成 Session ID，防止会话固定攻击
    $_SESSION['authenticated'] = true;
    $_SESSION['last_activity'] = time();
    $_SESSION['user_ip'] = $_SERVER['REMOTE_ADDR']; // 记录IP用于校验 (可选)
    $_SESSION['user_agent'] = $_SERVER['HTTP_USER_AGENT']; // 记录User Agent (可选)
}

/**
 * 销毁认证会话 (登出)
 */
function destroy_authentication_session() {
    $_SESSION = array(); // 清空会话变量

    if (ini_get("session.use_cookies")) {
        $params = session_get_cookie_params();
        setcookie(session_name(), '', time() - 42000,
            $params["path"], $params["domain"],
            $params["secure"], $params["httponly"]
        );
    }
    session_destroy();
}
?>
