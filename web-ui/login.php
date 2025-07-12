<?php
require_once 'config.php'; // 包含配置并启动会话

$error_message = '';

// 如果已登录，直接跳转到相册页面
if (check_authentication()) {
    header('Location: index.php');
    exit;
}

// 处理登录表单提交
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $password_attempt = $_POST['password'] ?? '';
    
    // !!! 在生产环境中，这里应该使用 password_verify($password_attempt, $hashed_password_from_db) !!!
    if ($password_attempt === GALLERY_PASSWORD) {
        set_authenticated_session(); // 设置认证成功的会话
        header('Location: index.php');
        exit;
    } else {
        $error_message = '密码错误，请重试。';
    }
}

// 处理URL中的错误提示（例如会话超时）
if (isset($_GET['error'])) {
    if ($_GET['error'] === 'session_timeout') {
        $error_message = '会话已超时，请重新登录。';
    } elseif ($_GET['error'] === 'unauthorized') {
        $error_message = '您需要登录才能访问。';
    }
}
?>
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>登录 - 照片查看器</title>
    <style>
        body { display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; background-color: #f0f2f5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
        .login-container { background: #fff; padding: 30px 40px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); text-align: center; width: 100%; max-width: 380px; }
        h2 { color: #1e40af; margin-bottom: 25px; font-size: 1.6em; font-weight: 600;}
        label { display: block; text-align: left; margin-bottom: 8px; font-weight: 500; color: #374151; }
        input[type="password"] { width: calc(100% - 24px); padding: 12px; margin-bottom: 20px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 1rem; box-sizing: border-box; }
        button[type="submit"] { width: 100%; background-color: #2563eb; color: white; padding: 12px 0; border: none; border-radius: 6px; cursor: pointer; font-size: 1.1rem; transition: background-color 0.2s; font-weight: 500; }
        button[type="submit"]:hover { background-color: #1d4ed8; }
        .error-message { color: #dc2626; margin-top: 15px; font-size: 0.9em; padding: 10px; background-color: #fee2e2; border: 1px solid #fca5a5; border-radius: 4px;}
    </style>
</head>
<body>
    <div class="login-container">
        <h2>照片查看器登录</h2>
        <form method="POST" action="login.php" novalidate>
            <div>
                <label for="password">密码:</label>
                <input type="password" name="password" id="password" required>
            </div>
            <button type="submit">登 录</button>
        </form>
        <?php if ($error_message): ?>
            <p class="error-message"><?php echo htmlspecialchars($error_message); ?></p>
        <?php endif; ?>
    </div>
</body>
</html>
