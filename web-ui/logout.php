<?php
require_once 'config.php'; // 包含配置并启动会话

destroy_authentication_session(); // 调用销毁会话的函数

// 跳转到登录页面
header('Location: login.php?logged_out=true');
exit;
?>
