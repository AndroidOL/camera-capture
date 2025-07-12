<!DOCTYPE html>
<html lang="zh-CN">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>照片查看器</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css" />
        <style>
            /* --- CSS Variables for Theming --- */
            :root {
                --main-bg-color: #f0f2f5;
                --container-bg-color: #ffffff;
                --text-color-primary: #1f2937;
                --text-color-secondary: #4b5563;
                --text-color-muted: #6b7280;
                --controls-bg-color: #eef2ff;
                --border-color-light: #dbeafe;
                --border-color-medium: #cbd5e1;
                --border-color-dark: #e5e7eb;
                --button-primary-bg: #2563eb;
                --button-primary-hover-bg: #1d4ed8;
                --button-secondary-bg: #64748b;
                --button-secondary-hover-bg: #475569;
                --button-success-bg: #16a34a;
                --button-success-hover-bg: #15803d;
                --button-danger-bg: #dc2626;
                --button-danger-hover-bg: #b91c1c;
                --button-warning-bg: #f59e0b;
                --button-warning-hover-bg: #d97706;
                --link-color: #1d4ed8;
                --link-hover-bg: #dbeafe;
                --accent-color: #1e40af;
                --placeholder-bg: #f3f4f6;

                --modal-overlay-bg: rgba(0, 0, 0, 0.85);

                --lightbox-content-bg-light: #ffffff;
                --lightbox-text-color-light: #1f2937;
                --lightbox-close-color-light: #6b7280;
                --lightbox-close-hover-color-light: #1f2937;

                --slideshow-content-bg-light: #f8f9fa;
                --slideshow-text-color-light: #1f2937;
                --slideshow-counter-color-light: #4b5563;
                --slideshow-close-color-light: #6b7280;
                --slideshow-close-hover-color-light: #1f2937;
            }

            body.dark-theme {
                --main-bg-color: #111827;
                --container-bg-color: #1f2937;
                --text-color-primary: #f3f4f6;
                --text-color-secondary: #d1d5db;
                --text-color-muted: #9ca3af;
                --controls-bg-color: #374151;
                --border-color-light: #4b5568;
                --border-color-medium: #6b7280;
                --border-color-dark: #4b5563;
                --button-primary-bg: #3b82f6;
                --button-primary-hover-bg: #2563eb;
                --button-secondary-bg: #9ca3af;
                --button-secondary-hover-bg: #6b7280;
                --link-color: #93c5fd;
                --link-hover-bg: #374151;
                --accent-color: #60a5fa;
                --placeholder-bg: #374151;

                --lightbox-content-bg-dark: #1f2937;
                --lightbox-text-color-dark: #f3f4f6;
                --lightbox-close-color-dark: #9ca3af;
                --lightbox-close-hover-color-dark: #f3f4f6;

                --slideshow-content-bg-dark: #2d3748;
                --slideshow-text-color-dark: #e5e7eb;
                --slideshow-counter-color-dark: #9ca3af;
                --slideshow-close-color-dark: #9ca3af;
                --slideshow-close-hover-color-dark: #e5e7eb;
            }

            body {
                background-color: var(--main-bg-color);
                color: var(--text-color-primary);
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                margin: 0;
                padding: 15px;
                line-height: 1.6;
                font-size: 16px;
            }
            .container {
                background: var(--container-bg-color);
                max-width: 1700px;
                margin: 20px auto;
                padding: 20px 25px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
                border-radius: 10px;
            }
            h1 {
                text-align: center;
                color: var(--accent-color);
                margin-bottom: 20px;
                font-weight: 600;
                font-size: 1.8em;
            }
            .controls {
                background-color: var(--controls-bg-color);
                border: 1px solid var(--border-color-light);
                margin-bottom: 20px;
                display: flex;
                align-items: center;
                gap: 10px;
                flex-wrap: wrap;
                padding: 15px;
                border-radius: 8px;
            }
            .controls label {
                font-weight: 500;
                color: var(--text-color-secondary);
                margin-right: 5px;
            }
            #datePicker {
                padding: 10px 14px;
                border: 1px solid var(--border-color-medium);
                border-radius: 6px;
                font-size: 1rem;
                color: var(--text-color-primary);
                background-color: var(--container-bg-color);
                min-width: 170px;
            }
            .control-button {
                padding: 10px 18px;
                color: white;
                border: none;
                cursor: pointer;
                border-radius: 6px;
                font-size: 0.95em;
                transition: background-color 0.2s;
                margin-left: 5px;
            }
            #backButton {
                background-color: var(--button-secondary-bg);
            }
            #backButton:hover {
                background-color: var(--button-secondary-hover-bg);
            }
            #startMonitorBtn {
                background-color: var(--button-success-bg);
            }
            #startMonitorBtn:hover {
                background-color: var(--button-success-hover-bg);
            }
            #stopMonitorBtn {
                background-color: var(--button-danger-bg);
                display: none;
            }
            #stopMonitorBtn:hover {
                background-color: var(--button-danger-hover-bg);
            }
            #startPhotoSlideshowBtn {
                background-color: var(--button-primary-bg);
            }
            #startPhotoSlideshowBtn:hover {
                background-color: var(--button-primary-hover-bg);
            }
            #themeToggleBtn {
                background-color: var(--button-secondary-bg);
            }
            #themeToggleBtn:hover {
                background-color: var(--button-secondary-hover-bg);
            }
            #logoutButton {
                background-color: var(--button-warning-bg);
                margin-left: auto;
            }
            #logoutButton:hover {
                background-color: var(--button-warning-hover-bg);
            }
            #currentLevelInfoContainer {
                font-weight: 600;
                padding: 10px 0;
                color: var(--text-color-secondary);
                flex-grow: 1;
                text-align: right;
                font-size: 0.95em;
                min-height: 1.5em;
            }
            #currentLevelInfoContainer .breadcrumb-link {
                color: var(--link-color);
                cursor: pointer;
                text-decoration: none;
                padding: 2px 4px;
                border-radius: 3px;
                margin: 0 2px;
            }
            #currentLevelInfoContainer .breadcrumb-link:hover {
                text-decoration: underline;
                background-color: var(--link-hover-bg);
            }
            #currentLevelInfoContainer .breadcrumb-separator {
                margin: 0 3px;
                color: var(--text-color-muted);
            }
            #currentLevelInfoContainer .breadcrumb-static {
                margin: 0 2px;
            }
            #status,
            #loading {
                margin-top: 10px;
                margin-bottom: 10px;
                padding: 12px 15px;
                border-radius: 6px;
                font-size: 0.95em;
                visibility: hidden;
                opacity: 0;
                transition: opacity 0.3s ease-in-out, visibility 0s linear 0.3s;
                min-height: 1.5em;
            }
            #status.visible,
            #loading.visible {
                visibility: visible;
                opacity: 1;
                transition: opacity 0.3s ease-in-out;
            }
            #status.success {
                background-color: #dcfce7;
                border: 1px solid #b7eb8f;
                color: #166534;
            }
            body.dark-theme #status.success {
                background-color: #102c1a;
                border-color: #295936;
                color: #a7f3d0;
            }
            #status.error {
                background-color: #fee2e2;
                border: 1px solid #fca5a5;
                color: #991b1b;
            }
            body.dark-theme #status.error {
                background-color: #3b1212;
                border-color: #7f1d1d;
                color: #fecaca;
            }
            #loading {
                text-align: center;
                color: var(--button-primary-bg);
                background-color: transparent;
                border: none;
            }
            #displayArea,
            #monitoringSection {
                min-height: 300px;
            }
            #monitoringSection {
                display: none;
                background-color: var(--placeholder-bg);
                border: 1px solid var(--border-color-dark);
                text-align: center;
                padding: 20px;
                border-radius: 8px;
            }
            #monitorImage {
                max-width: 90%;
                max-height: 70vh;
                border: 1px solid var(--border-color-dark);
                border-radius: 6px;
                margin-bottom: 10px;
                background-color: var(--container-bg-color);
            }
            #monitorFilename,
            #monitorTimestamp {
                font-size: 0.95em;
                color: var(--text-color-secondary);
                margin: 5px 0;
            }

            .preview-grid {
                display: grid;
                gap: 15px;
                margin-top: 20px;
                grid-template-columns: repeat(2, 1fr);
                align-items: start;
            }
            @media (min-width: 576px) {
                .preview-grid {
                    grid-template-columns: repeat(3, 1fr);
                }
            }
            @media (min-width: 768px) {
                .preview-grid {
                    grid-template-columns: repeat(4, 1fr);
                }
            }
            @media (min-width: 992px) {
                .preview-grid {
                    grid-template-columns: repeat(5, 1fr);
                }
            }
            @media (min-width: 1200px) {
                .preview-grid {
                    grid-template-columns: repeat(6, 1fr);
                }
            }

            .preview-item {
                border: 1px solid var(--border-color-dark);
                padding: 10px;
                text-align: center;
                cursor: pointer;
                background-color: var(--container-bg-color);
                border-radius: 8px;
                transition: transform 0.2s ease-out, box-shadow 0.2s ease-out;
                overflow: hidden;
                display: flex;
                flex-direction: column;
                justify-content: flex-start;
            }
            .preview-item:hover {
                transform: translateY(-5px);
                box-shadow: 0 6px 16px rgba(0, 0, 0, 0.12);
                border-color: var(--button-primary-bg);
            }
            .preview-item img {
                width: 100%;
                height: 120px;
                object-fit: cover;
                display: block;
                margin-bottom: 8px;
                border-radius: 6px;
                background-color: var(--placeholder-bg);
            }
            .preview-item p {
                font-size: 0.85em;
                margin: 0;
                padding: 0 2px;
                color: var(--text-color-secondary);
                word-break: break-all;
                line-height: 1.4;
                text-align: center;
            }

            .minute-view-gallery {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
                gap: 18px;
                margin-top: 10px;
                align-items: start;
            }
            .minute-view-gallery .photo-container {
                border: 1px solid var(--border-color-dark);
                padding: 10px;
                border-radius: 8px;
                text-align: center;
                transition: box-shadow 0.2s ease-out, background-color 0.3s, color 0.3s;
                cursor: pointer;
                display: flex;
                flex-direction: column;
                justify-content: flex-start;
                /* APPLYING SLIDESHOW STYLES FOR CONSISTENCY AS REQUESTED */
                background-color: var(--slideshow-content-bg-light);
                color: var(--slideshow-text-color-light);
            }
            body.dark-theme .minute-view-gallery .photo-container {
                background-color: var(--slideshow-content-bg-dark);
                color: var(--slideshow-text-color-dark);
            }
            .minute-view-gallery .photo-container:hover {
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
                border-color: var(--button-primary-bg);
            }
            .minute-view-gallery img {
                max-width: 100%;
                height: auto;
                display: block;
                border-radius: 6px;
                margin: 0 auto 8px auto;
            }
            .minute-view-gallery p {
                font-size: 0.85em;
                text-align: center;
                margin-top: 8px; /* Increased margin slightly */
                /* Color will be inherited from .photo-container if not specified here. */
                /* If explicit control needed: color: var(--slideshow-text-color-light); */
                /* body.dark-theme & { color: var(--slideshow-text-color-dark); } */
                word-break: break-all;
                line-height: 1.4;
            }

            .lightbox-modal {
                display: none;
                position: fixed;
                z-index: 1000;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                overflow: hidden;
                align-items: center;
                justify-content: center;
                flex-direction: column;
                background-color: var(--modal-overlay-bg);
            }
            .lightbox-content-wrapper {
                position: relative;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.3);
                max-width: 90vw;
                max-height: 90vh;
                display: flex;
                flex-direction: column;
                align-items: center;
                overflow: hidden;
                margin: 20px;
            }
            .lightbox-image-container {
                flex: 1;
                width: 100%;
                min-height: 0;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 10px 0;
                overflow: hidden;
                position: relative;
            }
            .lightbox-image {
                max-width: 100%;
                max-height: calc(75vh - 200px);
                object-fit: contain;
                height: auto;
                display: block;
                margin: 0;
                border-radius: 4px;
            }
            .maximize-btn {
                position: absolute;
                top: 15px;
                right: 15px;
                background-color: rgba(0, 0, 0, 0.5);
                color: white;
                border: none;
                border-radius: 50%;
                width: 30px;
                height: 30px;
                cursor: pointer;
                z-index: 1010;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: background-color 0.3s ease;
                padding: 0;
            }
            .maximize-btn svg {
                width: 16px;
                height: 16px;
                fill: currentColor;
            }
            .lightbox-image-container.maximized .lightbox-close {
                top: 170px;
                right: 90px;
            }
            .lightbox-image-container.maximized .maximize-btn {
                top: 170px;
                right: 35px;
            }
            .lightbox-details-container {
                width: 100%;
                overflow-y: auto;
                padding: 0 10px;
                margin-top: 10px;
                flex-shrink: 0;
            }
            .lightbox-details {
                font-size: 0.9em;
                margin-bottom: 15px;
                max-width: 600px;
                width: 100%;
                padding: 0 10px;
                box-sizing: border-box;
                text-align: left;
            }
            .lightbox-details p {
                margin: 5px 0;
                word-break: break-all;
            }
            .lightbox-controls {
                width: 100%;
                max-width: 600px;
                padding: 10px;
                margin-top: 10px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                flex-shrink: 0;
            }
            .lightbox-nav {
                display: flex;
                gap: 10px;
            }
            .lightbox-nav button,
            .lightbox-download-btn {
                color: white;
                border: none;
                padding: 10px 18px;
                text-align: center;
                text-decoration: none;
                display: inline-block;
                font-size: 1em;
                cursor: pointer;
                border-radius: 5px;
                background-color: var(--button-primary-bg);
            }
            .lightbox-nav button:hover,
            .lightbox-download-btn:hover {
                filter: brightness(110%);
            }
            body.dark-theme .lightbox-nav button:hover,
            body.dark-theme .lightbox-download-btn:hover {
                filter: brightness(120%);
            }
            .lightbox-nav button:disabled {
                background-color: var(--text-color-muted);
                opacity: 0.6;
                cursor: not-allowed;
            }

            #lightboxModal .lightbox-content-wrapper {
                background-color: var(--lightbox-content-bg-light);
                color: var(--lightbox-text-color-light);
                position: relative;
            }
            body.dark-theme #lightboxModal .lightbox-content-wrapper {
                background-color: var(--lightbox-content-bg-dark);
                color: var(--lightbox-text-color-dark);
            }
            .lightbox-close {
                position: absolute;
                right: 70px;
                top: 15px;
                cursor: pointer;
                z-index: 1010;
                width: 32px;
                height: 32px;
                background-color: rgba(0, 0, 0, 0.5);
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                line-height: 1;
                transition: background-color 0.3s ease;
                color: white !important;
                border: none;
            }
            .lightbox-close svg {
                width: 16px;
                height: 16px;
                fill: currentColor;
            }
            .lightbox-close:hover {
                background-color: rgba(0, 0, 0, 0.7);
            }

            /* 控制按钮容器 */
            .image-controls {
                position: absolute;
                top: 15px;
                right: 15px;
                display: flex;
                gap: 10px;
                z-index: 1010;
            }

            /* 统一按钮样式 */
            .image-controls button {
                width: 32px;
                height: 32px;
                border: none;
                border-radius: 50%;
                background-color: rgba(0, 0, 0, 0.5);
                color: white;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: background-color 0.3s ease;
                padding: 0;
            }

            .image-controls button:hover {
                background-color: rgba(0, 0, 0, 0.7);
            }

            .lightbox-close {
                font-size: 24px;
                line-height: 1;
            }

            .maximize-btn svg {
                width: 16px;
                height: 16px;
                fill: currentColor;
            }

            /* 计数器样式 */
            .counter {
                position: absolute;
                bottom: 20%;
                left: 50%;
                transform: translateX(-50%);
                background-color: rgba(0, 0, 0, 0.5);
                color: white !important;
                padding: 5px 12px;
                border-radius: 15px;
                font-size: 0.9em;
                z-index: 1000;
            }

            #lightboxCounter {
                position: absolute;
                bottom: 3%;
                left: 50%;
                transform: translateX(-50%);
                background-color: rgba(0, 0, 0, 0.5);
                color: white !important;
                padding: 5px 12px;
                border-radius: 15px;
                font-size: 0.9em;
                z-index: 1000;
            }

            body.dark-theme .counter,
            body.dark-theme #lightboxCounter {
                background-color: rgba(0, 0, 0, 0.7);
            }

            .lightbox-image-container.maximized .image-controls {
                top: 20px;
                right: 20px;
            }

            @media (max-width: 575px) {
                .preview-grid {
                    grid-template-columns: repeat(2, 1fr);
                }
                .preview-item img {
                    height: 100px;
                }
                .minute-view-gallery {
                    grid-template-columns: 1fr;
                }
            }

            .lightbox-image-container.maximized {
                position: fixed;
                top: 0;
                left: 0;
                width: 100vw;
                height: 100vh;
                z-index: 1100;
                background-color: var(--modal-overlay-bg);
                margin: 0;
            }

            .lightbox-image-container.maximized .lightbox-image {
                max-height: 95vh;
                max-width: 95vw;
            }

            #photoSlideshowModal {
                z-index: 1050;
            }

            #photoSlideshowModal .lightbox-content-wrapper {
                background-color: var(--slideshow-content-bg-light);
                color: var(--slideshow-text-color-light);
                position: relative;
            }

            body.dark-theme #photoSlideshowModal .lightbox-content-wrapper {
                background-color: var(--slideshow-content-bg-dark);
                color: var(--slideshow-text-color-dark);
            }

            #lightboxDetails, #photoSlideshowDetails, #monitoringSection .lightbox-details {
                text-align: left;
                margin: 15px auto;
                max-width: 600px;
                width: 100%;
                padding: 0 10px;
                box-sizing: border-box;
            }

            @media (max-height: 700px) {
                .lightbox-image {
                    max-height: calc(70vh - 150px);
                }
                .lightbox-content-wrapper {
                    margin: 15px;
                    padding: 15px;
                }
            }

            .maximize-btn:hover {
                background-color: rgba(0, 0, 0, 0.7);
            }

            /* 监控页面的最大化按钮单独样式 */
            #monitoringSection .maximize-btn {
                position: absolute;
                top: 205px;
                right: 94px;
                background-color: rgba(0, 0, 0, 0.5);
                color: white;
                border: none;
                border-radius: 50%;
                width: 32px;
                height: 32px;
                cursor: pointer;
                z-index: 1010;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: background-color 0.3s ease;
            }

            /* 监控页面的最大化按钮单独样式 */
            #monitoringSection .maximize-btn {
                position: absolute;
                top: 30px;
                right: 94px;
                background-color: rgba(0, 0, 0, 0.5);
                color: white;
                border: none;
                border-radius: 50%;
                width: 32px;
                height: 32px;
                cursor: pointer;
                z-index: 1010;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: background-color 0.3s ease;
            }

            #slideshowCounter {
                position: absolute;
                bottom: 240px; /* 调整到更上方 */
                left: 50%;
                transform: translateX(-50%);
                background-color: rgba(0, 0, 0, 0.5);
                color: white !important;
                padding: 5px 12px;
                border-radius: 15px;
                font-size: 0.9em;
                z-index: 1000;
            }

            body.dark-theme #slideshowCounter {
                background-color: rgba(0, 0, 0, 0.7);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>照片查看器</h1>
            <div class="controls">
                <label for="datePicker">选择日期:</label>
                <input type="text" id="datePicker" placeholder="选择日期..." />
                <button id="backButton" class="control-button">返回上一级</button>
                <button id="startPhotoSlideshowBtn" class="control-button">照片轮播</button>
                <button id="startMonitorBtn" class="control-button">实时监控</button>
                <button id="stopMonitorBtn" class="control-button">停止监控</button>
                <button id="themeToggleBtn" class="control-button" title="切换主题">☀️</button>
                <a href="logout.php" id="logoutButton" class="control-button">登出</a>
                <div id="currentLevelInfoContainer">
                    <span id="currentLevelInfo"></span>
                </div>
            </div>
            <div id="status" role="status" aria-live="polite"></div>
            <div id="loading" role="alert" aria-busy="true">正在加载，请稍候...</div>

            <div id="displayArea"></div>
            <div id="monitoringSection">
                <h2 style="font-size: 1.2em; color: var(--text-color-primary); margin-bottom: 15px;">实时监控中...</h2>
                <div class="lightbox-image-container">
                    <img id="monitorImage" src="" alt="实时照片" class="lightbox-image" />
                    <button class="maximize-btn" title="最大化">
                        <svg viewBox="0 0 24 24" class="maximize-icon">
                            <path d="M3 3h7v2H5v5H3V3m18 0v7h-2V5h-5V3h7M3 21v-7h2v5h5v2H3m18-7v7h-7v-2h5v-5h2"/>
                        </svg>
                    </button>
                </div>
                <div class="lightbox-details">
                    <p><strong>文件名称:</strong> <span id="monitorFilename"></span></p>
                    <p><strong>文件大小:</strong> <span id="monitorFilesize"></span></p>
                    <p><strong>拍摄时间:</strong> <span id="monitorTimestamp"></span></p>
                </div>
            </div>
        </div>

        <div id="lightboxModal" class="lightbox-modal" role="dialog" aria-modal="true" aria-labelledby="lightboxDetailFilename">
            <div class="lightbox-content-wrapper">
                <div class="lightbox-image-container">
                    <img class="lightbox-image" id="lightboxImage" src="" alt="放大图片" />
                    <div class="image-controls">
                        <button class="lightbox-close" id="lightboxCloseBtn" title="关闭 (Esc)" role="button" tabindex="0">
                            <svg viewBox="0 0 24 24">
                                <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                            </svg>
                        </button>
                        <button class="maximize-btn" title="最大化">
                            <svg viewBox="0 0 24 24" class="maximize-icon">
                                <path d="M3 3h7v2H5v5H3V3m18 0v7h-2V5h-5V3h7M3 21v-7h2v5h5v2H3m18-7v7h-7v-2h5v-5h2"/>
                            </svg>
                        </button>
                    </div>
                </div>
                <div class="lightbox-details-container">
                    <div id="lightboxDetails" class="lightbox-details">
                        <p><strong>文件名称:</strong> <span id="detailFilename"></span></p>
                        <p><strong>文件大小:</strong> <span id="detailFilesize"></span></p>
                        <p><strong>拍摄时间:</strong> <span id="detailTimestamp"></span></p>
                    </div>
                </div>
                <div class="lightbox-controls">
                    <a id="lightboxDownload" href="#" download class="lightbox-download-btn">下载图片</a>
                    <div class="lightbox-nav">
                        <button id="lightboxPrev" title="上一张 (←)">‹ 上一张</button>
                        <button id="lightboxNext" title="下一张 (→)">下一张 ›</button>
                    </div>
                </div>
            </div>
        </div>

        <div id="photoSlideshowModal" class="lightbox-modal" role="dialog" aria-modal="true">
            <div class="lightbox-content-wrapper">
                <div class="lightbox-image-container">
                    <img class="lightbox-image" id="photoSlideshowImage" src="" alt="轮播图片" />
                    <div class="image-controls">
                        <button class="lightbox-close" id="photoSlideshowCloseBtn" title="关闭 (Esc)" role="button" tabindex="0">
                            <svg viewBox="0 0 24 24">
                                <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                            </svg>
                        </button>
                        <button class="maximize-btn" title="最大化">
                            <svg viewBox="0 0 24 24" class="maximize-icon">
                                <path d="M3 3h7v2H5v5H3V3m18 0v7h-2V5h-5V3h7M3 21v-7h2v5h5v2H3m18-7v7h-7v-2h5v-5h2"/>
                            </svg>
                        </button>
                    </div>
                </div>
                <div id="slideshowCounter"></div>
                <div class="lightbox-details-container">
                    <div id="photoSlideshowDetails" class="lightbox-details">
                        <p><strong>文件名称:</strong> <span id="slideshowDetailFilename"></span></p>
                        <p><strong>文件大小:</strong> <span id="slideshowDetailFilesize"></span></p>
                        <p><strong>拍摄时间:</strong> <span id="slideshowDetailTimestamp"></span></p>
                    </div>
                </div>
                <div class="lightbox-controls">
                    <a id="photoSlideshowDownload" href="#" download class="lightbox-download-btn">下载当前图片</a>
                    <div class="lightbox-nav">
                        <button id="photoSlideshowPrev" title="上一张 (←)">‹ 上一张</button>
                        <button id="photoSlideshowNext" title="下一张 (→)">下一张 ›</button>
                    </div>
                </div>
            </div>
        </div>

        <script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>
        <script>
            // --- DOM Elements ---
            const datePickerEl = document.getElementById("datePicker");
            const displayArea = document.getElementById("displayArea");
            const backButton = document.getElementById("backButton");
            const currentLevelInfoContainer = document.getElementById("currentLevelInfoContainer");
            const currentLevelInfoEl = document.getElementById("currentLevelInfo");
            const loadingEl = document.getElementById("loading");
            const statusEl = document.getElementById("status");
            const lightboxModal = document.getElementById("lightboxModal");
            const lightboxImage = document.getElementById("lightboxImage");
            const lightboxCloseBtn = document.getElementById("lightboxCloseBtn");
            const detailFilename = document.getElementById("detailFilename");
            const detailFilesize = document.getElementById("detailFilesize");
            const detailTimestamp = document.getElementById("detailTimestamp");
            const lightboxDownload = document.getElementById("lightboxDownload");
            const lightboxPrevBtn = document.getElementById("lightboxPrev");
            const lightboxNextBtn = document.getElementById("lightboxNext");
            const startMonitorBtn = document.getElementById("startMonitorBtn");
            const stopMonitorBtn = document.getElementById("stopMonitorBtn");
            const monitoringSection = document.getElementById("monitoringSection");
            const monitorImageEl = document.getElementById("monitorImage");
            const monitorFilenameEl = document.getElementById("monitorFilename");
            const monitorTimestampEl = document.getElementById("monitorTimestamp");
            const monitorFilesizeEl = document.getElementById("monitorFilesize");
            const startPhotoSlideshowBtn = document.getElementById("startPhotoSlideshowBtn");
            const photoSlideshowModal = document.getElementById("photoSlideshowModal");
            const photoSlideshowCloseBtn = document.getElementById("photoSlideshowCloseBtn");
            const photoSlideshowImage = document.getElementById("photoSlideshowImage");
            const slideshowCounterEl = document.getElementById("slideshowCounter");
            const slideshowDetailFilename = document.getElementById("slideshowDetailFilename");
            const slideshowDetailFilesize = document.getElementById("slideshowDetailFilesize");
            const slideshowDetailTimestamp = document.getElementById("slideshowDetailTimestamp");
            const photoSlideshowDownload = document.getElementById("photoSlideshowDownload");
            const photoSlideshowPrevBtn = document.getElementById("photoSlideshowPrev");
            const photoSlideshowNextBtn = document.getElementById("photoSlideshowNext");
            const themeToggleBtn = document.getElementById("themeToggleBtn");

            // --- Application State ---
            let currentState = { level: 0, date: "", hour: "", intervalSlot: "", minute: "" };
            let historyStack = [];
            let flatpickrInstance = null;

            // --- Lightbox State & Monitoring State & Global Slideshow State ---
            let lightboxCurrentItems = [];
            let lightboxCurrentIndex = -1;
            let isMonitoringActive = false;
            let monitorTimeoutId = null;
            let currentMonitorPhoto = { filename: "", imageUrl: "", timestampEpoch: 0, filesize: 0 };
            const CAMERA_INTERVAL_MS = 2500; // 相机拍摄间隔，可配置（默认5秒）
            const POLLING_OFFSET_MS = 80; // 轮询偏移量（0.15秒）
            const MONITOR_RETRY_NO_NEW_PHOTO_MS = 3000;
            const MONITOR_RETRY_NO_PHOTO_AT_ALL_MS = 10000;
            let lastPollCount = 0; // 记录连续轮询次数
            let globalSlideshowItems = [];
            let globalSlideshowCurrentIndex = -1;
            let isGlobalSlideshowActive = false;

            // --- Utility Functions ---
            function showLoading(show) {
                loadingEl.classList.toggle("visible", show);
            }
            function updateStatus(message, isError = false) {
                statusEl.textContent = message;
                statusEl.classList.toggle("visible", !!message);
                if (message) {
                    statusEl.className = isError ? "error visible" : "success visible";
                } else {
                    statusEl.className = "";
                }
            }
            async function fetchData(action, params = {}) {
                /* ... (与之前包含错误处理的版本相同) ... */ showLoading(true);
                const qPO = { ...params };
                if (currentState.date && !qPO.date && action !== "getEarliestDate" && action !== "getLatestPhoto" && action !== "getPhotoListForRange") {
                    qPO.date = currentState.date;
                }
                const qP = new URLSearchParams(qPO).toString();
                const url = `gallery_api.php?action=${action}${qP ? "&" + qP : ""}`;
                try {
                    const r = await fetch(url);
                    if (!r.ok) {
                        let eT = `HTTP error ${r.status} (${r.statusText})`;
                        try {
                            const eD = await r.json();
                            if (eD && eD.error) eT = eD.error;
                        } catch (e) {}
                        throw new Error(eT);
                    }
                    const d = await r.json();
                    if (d.error && action !== "getEarliestDate" && !(action === "getLatestPhoto" && d.latest_photo === null) && !(action === "getPhotoListForRange" && d.photos !== undefined)) {
                        throw new Error(d.error);
                    }
                    return d;
                } catch (e) {
                    console.error(`Workspace error for action "${action}" with params "${qP}":`, e);
                    // Check if the error message indicates an authorization issue
                    if (e.message && e.message.includes("访问未授权或会话已超时，请重新登录")) {
                        // Redirect to login.php
                        window.location.href = 'login.php';
                        // It's good practice to return or throw to prevent further execution if redirecting
                        return null;
                    } else {
                        // For any other errors, update the status as usual
                        updateStatus(`加载数据失败: ${e.message}`, true);
                    }
                    return null;
                } finally {
                    showLoading(false);
                }
            }

            // --- Rendering Functions (恢复网格预览) ---
            function preloadImages(urls) {
                urls.forEach(url => {
                    const img = new Image();
                    img.src = url;
                });
            }

            function renderPreviews(items, itemClickHandler, gridClassName, generateContentFunc) {
                displayArea.innerHTML = "";
                displayArea.className = `preview-grid ${gridClassName}`;
                
                if (!items || items.length === 0) {
                    updateStatus("当前层级没有找到照片。", false);
                    return;
                }
                
                const fragment = document.createDocumentFragment();
                const preloadUrls = [];
                
                items.forEach((item, index) => {
                    const div = document.createElement("div");
                    div.className = "preview-item";
                    div.style.opacity = "0";
                    div.style.transform = "translateY(20px)";
                    div.style.transition = "opacity 0.3s ease, transform 0.3s ease";
                    div.innerHTML = generateContentFunc(item);
                    div.onclick = () => itemClickHandler(item);
                    
                    // 收集预加载URL
                    if (item.preview_image_url) {
                        preloadUrls.push(item.preview_image_url);
                    }
                    if (item.image_url) {
                        preloadUrls.push(item.image_url);
                    }
                    
                    // 添加渐入动画
                    setTimeout(() => {
                        div.style.opacity = "1";
                        div.style.transform = "translateY(0)";
                    }, index * 50);
                    
                    fragment.appendChild(div);
                });
                
                displayArea.appendChild(fragment);
                
                // 预加载下一级别的图片
                preloadImages(preloadUrls);
            }
            function renderMinutePhotos(photos) {
                displayArea.innerHTML = "";
                displayArea.className = "minute-view-gallery";
                if (!photos || photos.length === 0) {
                    updateStatus("此分钟没有照片。", false);
                    return;
                }
                const fragment = document.createDocumentFragment();
                photos.forEach((photo, index) => {
                    const container = document.createElement("div");
                    container.className = "photo-container";
                    const parts = photo.filename.split("_");
                    const timePart = parts.length > 2 ? parts[2].match(/.{1,2}/g).join(":") : photo.filename;
                    const sequencePart = parts.length > 3 ? parts[3].split(".")[0] : "";
                    container.innerHTML = `<img src="${photo.image_url}" alt="${photo.filename}" title="点击放大: ${photo.filename}" loading="lazy"><p>${timePart}${sequencePart ? ` (${sequencePart})` : ""}</p>`;
                    container.onclick = () => openLightbox(photos, index);
                    fragment.appendChild(container);
                });
                displayArea.appendChild(fragment);
            }

            // --- Lightbox Functions ---
            function openLightbox(items, startIndex) {
                if (!items || items.length === 0) return;
                lightboxCurrentItems = items;
                lightboxCurrentIndex = startIndex;
                updateLightboxContent();
                lightboxModal.style.display = "flex";
                document.body.style.overflow = "hidden";
                document.addEventListener("keydown", handleKeydownEvents);
            }
            function closeLightbox() {
                lightboxModal.style.display = "none";
                document.body.style.overflow = "auto";
                document.removeEventListener("keydown", handleKeydownEvents);
            }
            function updateLightboxContent() {
                if (lightboxCurrentIndex < 0 || lightboxCurrentIndex >= lightboxCurrentItems.length) {
                    closeLightbox();
                    return;
                }
                const item = lightboxCurrentItems[lightboxCurrentIndex];
                lightboxImage.src = item.image_url;
                lightboxImage.alt = item.filename;
                detailFilename.textContent = item.filename;
                detailFilesize.textContent = formatFileSize(item.filesize);
                const parts = item.filename.match(/capture_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
                if (parts && parts.length >= 7) {
                    detailTimestamp.textContent = `${parts[1]}-${parts[2]}-${parts[3]} ${parts[4]}:${parts[5]}:${parts[6]}`;
                } else {
                    detailTimestamp.textContent = "N/A";
                }
                lightboxDownload.href = item.image_url;
                lightboxDownload.download = item.filename;
                lightboxPrevBtn.disabled = lightboxCurrentIndex === 0;
                lightboxNextBtn.disabled = lightboxCurrentIndex === lightboxCurrentItems.length - 1;
                
                // 更新计数器
                const counterEl = document.createElement('div');
                counterEl.id = 'lightboxCounter';
                counterEl.className = 'counter';
                counterEl.textContent = `${lightboxCurrentIndex + 1} / ${lightboxCurrentItems.length}`;
                
                // 移除旧的计数器（如果存在）
                const existingCounter = document.getElementById('lightboxCounter');
                if (existingCounter) {
                    existingCounter.remove();
                }
                
                // 将计数器添加到图片容器中
                const container = document.querySelector('#lightboxModal .lightbox-image-container');
                container.appendChild(counterEl);
            }
            function lightboxNavigate(direction) {
                const newIndex = lightboxCurrentIndex + direction;
                if (newIndex >= 0 && newIndex < lightboxCurrentItems.length) {
                    lightboxCurrentIndex = newIndex;
                    updateLightboxContent();
                }
            }

            // --- Global Photo Slideshow Functions ---
            // 添加预加载控制变量
            let preloadedImages = new Map(); // 用于缓存已预加载的图片

            // 预加载指定图片
            function preloadImage(url) {
                if (preloadedImages.has(url)) {
                    return preloadedImages.get(url);
                }

                const promise = new Promise((resolve) => {
                    const img = new Image();
                    img.onload = () => resolve(url);
                    img.onerror = () => resolve(url); // 即使加载失败也继续
                    img.src = url;
                });
                preloadedImages.set(url, promise);
                return promise;
            }

            // 预加载当前图片及其相邻图片
            function preloadAdjacentImages(currentIndex) {
                const indexes = [currentIndex];
                if (currentIndex > 0) indexes.push(currentIndex - 1);
                if (currentIndex < globalSlideshowItems.length - 1) indexes.push(currentIndex + 1);

                const preloadPromises = indexes.map(index => {
                    const item = globalSlideshowItems[index];
                    return preloadImage(item.image_url);
                });

                return Promise.all(preloadPromises);
            }

            async function initiateGlobalSlideshow() {
                if (!currentState.date) {
                    updateStatus("请先选择一个日期以开始轮播。", true);
                    return;
                }
                if (isMonitoringActive) {
                    updateStatus("请先停止实时监控，再开始照片轮播。", true);
                    return;
                }
                isGlobalSlideshowActive = true;
                if (currentState.level > 0 || currentState.date !== "") saveCurrentStateToHistory();
                updateStatus("正在加载轮播照片列表...", false);
                displayArea.style.display = "none";
                currentLevelInfoContainer.style.display = "none";
                backButton.style.display = "none";
                startMonitorBtn.disabled = true;
                startPhotoSlideshowBtn.disabled = true;
                
                let params = { date: currentState.date };
                if (currentState.level >= 2 && currentState.hour) params.hour = currentState.hour;
                if (currentState.level >= 3 && currentState.intervalSlot !== "") params.interval_slot = currentState.intervalSlot;
                if (currentState.level >= 4 && currentState.minute) params.minute = currentState.minute;
                
                const data = await fetchData("getPhotoListForRange", params);
                if (data && data.photos && data.photos.length > 0) {
                    globalSlideshowItems = data.photos;
                    globalSlideshowCurrentIndex = 0;
                    preloadedImages.clear(); // 清除之前的预加载缓存
                    
                    // 只预加载第一张图片和第二张图片
                    await preloadAdjacentImages(0);
                    
                    updateGlobalSlideshowDisplay();
                    photoSlideshowModal.style.display = "flex";
                    document.body.style.overflow = "hidden";
                    document.addEventListener("keydown", handleKeydownEvents);
                    updateStatus(`轮播已开始，第 1 / ${globalSlideshowItems.length} 张照片。`, false);
                } else {
                    updateStatus("在此选定范围内未找到照片进行轮播。", true);
                    closeGlobalSlideshow(false);
                }
            }
            function updateGlobalSlideshowDisplay() {
                if (globalSlideshowCurrentIndex < 0 || globalSlideshowCurrentIndex >= globalSlideshowItems.length) {
                    closeGlobalSlideshow();
                    return;
                }
                const item = globalSlideshowItems[globalSlideshowCurrentIndex];
                
                // 使用 CSS 类控制过渡效果
                photoSlideshowImage.classList.add('fade-out');
                
                // 设置新图片
                setTimeout(() => {
                    photoSlideshowImage.src = item.image_url;
                    photoSlideshowImage.classList.remove('fade-out');
                }, 50);
                
                photoSlideshowImage.alt = item.filename;
                slideshowCounterEl.textContent = `${globalSlideshowCurrentIndex + 1} / ${globalSlideshowItems.length}`;
                slideshowDetailFilename.textContent = item.filename;
                slideshowDetailFilesize.textContent = formatFileSize(item.filesize);
                const parts = item.filename.match(/capture_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
                if (parts && parts.length >= 7) {
                    slideshowDetailTimestamp.textContent = `${parts[1]}-${parts[2]}-${parts[3]} ${parts[4]}:${parts[5]}:${parts[6]}`;
                } else {
                    slideshowDetailTimestamp.textContent = "N/A";
                }
                photoSlideshowDownload.href = item.image_url;
                photoSlideshowDownload.download = item.filename;
                photoSlideshowPrevBtn.disabled = globalSlideshowCurrentIndex === 0;
                photoSlideshowNextBtn.disabled = globalSlideshowCurrentIndex === globalSlideshowItems.length - 1;
            }
            function globalSlideshowNavigate(direction) {
                const newIndex = globalSlideshowCurrentIndex + direction;
                if (newIndex >= 0 && newIndex < globalSlideshowItems.length) {
                    globalSlideshowCurrentIndex = newIndex;
                    // 预加载新位置的相邻图片
                    preloadAdjacentImages(globalSlideshowCurrentIndex).then(() => {
                        updateGlobalSlideshowDisplay();
                    });
                }
            }
            function closeGlobalSlideshow(restoreFromHistory = true) {
                photoSlideshowModal.style.display = "none";
                document.body.style.overflow = "auto";
                document.removeEventListener("keydown", handleKeydownEvents);
                isGlobalSlideshowActive = false;
                displayArea.style.display = "grid";
                currentLevelInfoContainer.style.display = "block";
                startMonitorBtn.disabled = false;
                startPhotoSlideshowBtn.disabled = false;
                preloadedImages.clear(); // 清除预加载的图片缓存
                if (restoreFromHistory && historyStack.length > 0) {
                    backButton.click();
                } else {
                    updateUI();
                }
                updateStatus("照片轮播已关闭。", false);
            }

            function handleKeydownEvents(event) {
                if (lightboxModal.style.display === "flex" && !isGlobalSlideshowActive && !isMonitoringActive) {
                    switch (event.key) {
                        case "Escape":
                            closeLightbox();
                            break;
                        case "ArrowLeft":
                            if (!lightboxPrevBtn.disabled) lightboxNavigate(-1);
                            break;
                        case "ArrowRight":
                            if (!lightboxNextBtn.disabled) lightboxNavigate(1);
                            break;
                    }
                } else if (isGlobalSlideshowActive && photoSlideshowModal.style.display === "flex") {
                    switch (event.key) {
                        case "Escape":
                            closeGlobalSlideshow();
                            break;
                        case "ArrowLeft":
                            if (!photoSlideshowPrevBtn.disabled) globalSlideshowNavigate(-1);
                            break;
                        case "ArrowRight":
                            if (!photoSlideshowNextBtn.disabled) globalSlideshowNavigate(1);
                            break;
                    }
                }
            }

            startPhotoSlideshowBtn.onclick = initiateGlobalSlideshow;
            photoSlideshowCloseBtn.onclick = closeGlobalSlideshow;
            photoSlideshowPrevBtn.onclick = () => globalSlideshowNavigate(-1);
            photoSlideshowNextBtn.onclick = () => globalSlideshowNavigate(1);
            photoSlideshowModal.addEventListener("click", function (event) {
                if (event.target === photoSlideshowModal) {
                    closeGlobalSlideshow();
                }
            });
            lightboxCloseBtn.onclick = closeLightbox;
            lightboxPrevBtn.onclick = () => lightboxNavigate(-1);
            lightboxNextBtn.onclick = () => lightboxNavigate(1);
            lightboxModal.addEventListener("click", function (event) {
                if (event.target === lightboxModal) {
                    closeLightbox();
                }
            });

            // --- Theme Toggle ---
            function applyTheme(theme) {
                if (theme === "dark") {
                    document.body.classList.add("dark-theme");
                    themeToggleBtn.textContent = "浅色主题";
                    themeToggleBtn.title = "切换到日间模式";
                } else {
                    // Light theme
                    document.body.classList.remove("dark-theme");
                    themeToggleBtn.textContent = "深色主题";
                    themeToggleBtn.title = "切换到夜间模式";
                }
            }
            themeToggleBtn.onclick = () => {
                const currentTheme = document.body.classList.contains("dark-theme") ? "dark" : "light";
                const newTheme = currentTheme === "dark" ? "light" : "dark";
                localStorage.setItem("galleryTheme", newTheme);
                applyTheme(newTheme);
            };

            // --- UI Update and State Management ---
            function _updateAndClearState(targetLevel, params) {
                currentState.level = targetLevel;
                currentState.date = params.date !== undefined ? params.date : currentState.date;
                currentState.hour = targetLevel >= 2 && params.hour !== undefined ? params.hour : "";
                currentState.intervalSlot = targetLevel >= 3 && params.intervalSlot !== undefined ? params.intervalSlot : "";
                currentState.minute = targetLevel >= 4 && params.minute !== undefined ? params.minute : "";
                if (targetLevel < 4) currentState.minute = "";
                if (targetLevel < 3) currentState.intervalSlot = "";
                if (targetLevel < 2) currentState.hour = "";
            }
            function navigateToLevelAndSaveHistory(targetLevel, params = {}) {
                saveCurrentStateToHistory();
                _updateAndClearState(targetLevel, params);
                updateUI();
            }
            function jumpToLevelViaBreadcrumb(targetLevel, params = {}) {
                historyStack = [];
                _updateAndClearState(targetLevel, params);
                updateUI();
            }

            function updateUI() {
                updateStatus("");
                backButton.style.display = historyStack.length > 0 && !isMonitoringActive && !isGlobalSlideshowActive ? "inline-block" : "none";
                const breadcrumbFragment = document.createDocumentFragment();
                if (isGlobalSlideshowActive) {
                    const sTS = document.createElement("span");
                    sTS.className = "breadcrumb-static";
                    sTS.textContent = "照片轮播模式";
                    breadcrumbFragment.appendChild(sTS);
                } else if (isMonitoringActive) {
                    const mTS = document.createElement("span");
                    mTS.className = "breadcrumb-static";
                    mTS.textContent = "实时监控模式";
                    breadcrumbFragment.appendChild(mTS);
                } else if (currentState.date) {
                    const dS = document.createElement("span");
                    dS.textContent = `日期: ${currentState.date}`;
                    if (currentState.level > 1) {
                        dS.className = "breadcrumb-link";
                        dS.title = `返回 ${currentState.date} 小时视图`;
                        dS.onclick = () => jumpToLevelViaBreadcrumb(1, { date: currentState.date });
                    } else {
                        dS.className = "breadcrumb-static";
                    }
                    breadcrumbFragment.appendChild(dS);
                    if (currentState.hour) {
                        const s1 = document.createElement("span");
                        s1.className = "breadcrumb-separator";
                        s1.textContent = ">";
                        breadcrumbFragment.appendChild(s1);
                        const hS = document.createElement("span");
                        hS.textContent = ` ${currentState.hour}点`;
                        if (currentState.level > 2) {
                            hS.className = "breadcrumb-link";
                            hS.title = `返回 ${currentState.hour}点 10分钟段视图`;
                            hS.onclick = () => jumpToLevelViaBreadcrumb(2, { date: currentState.date, hour: currentState.hour });
                        } else {
                            hS.className = "breadcrumb-static";
                        }
                        breadcrumbFragment.appendChild(hS);
                    }
                    const slotNum = Number(currentState.intervalSlot);
                    if (currentState.intervalSlot !== "" && currentState.intervalSlot != null && !isNaN(slotNum) && slotNum >= 0 && slotNum <= 5) {
                        const s2 = document.createElement("span");
                        s2.className = "breadcrumb-separator";
                        s2.textContent = ">";
                        breadcrumbFragment.appendChild(s2);
                        const iS = document.createElement("span");
                        const startMin = slotNum * 10;
                        iS.textContent = ` ${String(startMin).padStart(2, "0")}-${String(startMin + 9).padStart(2, "0")}分段`;
                        if (currentState.level > 3) {
                            iS.className = "breadcrumb-link";
                            iS.title = `返回此10分钟段分钟视图`;
                            iS.onclick = () => jumpToLevelViaBreadcrumb(3, { date: currentState.date, hour: currentState.hour, intervalSlot: currentState.intervalSlot });
                        } else {
                            iS.className = "breadcrumb-static";
                        }
                        breadcrumbFragment.appendChild(iS);
                    } else if (currentState.level >= 3 && currentState.intervalSlot !== "" && currentState.intervalSlot != null) {
                        console.warn("intervalSlot invalid:", currentState.intervalSlot);
                    }
                    if (currentState.minute) {
                        const s3 = document.createElement("span");
                        s3.className = "breadcrumb-separator";
                        s3.textContent = ">";
                        breadcrumbFragment.appendChild(s3);
                        const mS = document.createElement("span");
                        mS.textContent = ` 第 ${currentState.minute} 分钟`;
                        mS.className = "breadcrumb-static";
                        breadcrumbFragment.appendChild(mS);
                    }
                } else {
                    const pS = document.createElement("span");
                    pS.className = "breadcrumb-static";
                    pS.textContent = "日期: 未选择";
                    breadcrumbFragment.appendChild(pS);
                }
                currentLevelInfoEl.innerHTML = "";
                currentLevelInfoEl.appendChild(breadcrumbFragment);

                if (isMonitoringActive) {
                    displayArea.style.display = "none";
                    monitoringSection.style.display = "block";
                    photoSlideshowModal.style.display = "none";
                } else if (isGlobalSlideshowActive) {
                    displayArea.style.display = "none";
                    monitoringSection.style.display = "none"; /* photoSlideshowModal is managed by its own functions */
                } else {
                    displayArea.style.display = "grid";
                    monitoringSection.style.display = "none";
                    photoSlideshowModal.style.display = "none";
                    switch (currentState.level) {
                        case 0:
                            displayArea.innerHTML = "";
                            updateStatus("请选择一个日期开始浏览。");
                            break;
                        case 1:
                            fetchDailySummary(currentState.date);
                            break;
                        case 2:
                            fetchHourlySummary(currentState.date, currentState.hour);
                            break;
                        case 3:
                            fetchTenMinuteSummary(currentState.date, currentState.hour, currentState.intervalSlot);
                            break;
                        case 4:
                            fetchMinutePhotos(currentState.date, currentState.hour, currentState.minute);
                            break;
                        default:
                            console.error("Unknown UI level:", currentState.level);
                            updateStatus("发生未知错误。", true);
                    }
                }
            }
            function saveCurrentStateToHistory() {
                const lS = historyStack.length > 0 ? historyStack[historyStack.length - 1] : null;
                if (!lS || JSON.stringify(lS) !== JSON.stringify(currentState)) {
                    historyStack.push(JSON.parse(JSON.stringify(currentState)));
                }
            }
            backButton.onclick = () => {
                if (historyStack.length > 0) {
                    currentState = historyStack.pop();
                    if (flatpickrInstance) {
                        const cDP = flatpickrInstance.selectedDates.length > 0 ? flatpickrInstance.formatDate(flatpickrInstance.selectedDates[0], "Y-m-d") : "";
                        if (currentState.date && cDP !== currentState.date) {
                            flatpickrInstance.setDate(currentState.date, false);
                        } else if (!currentState.date && cDP !== "") {
                            flatpickrInstance.clear(false);
                        }
                    }
                    updateUI();
                }
            };
            function parseTimestampFromFilename(filename) {
                const match = filename.match(/capture_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
                if (match) {
                    const year = parseInt(match[1], 10);
                    const month = parseInt(match[2], 10) - 1;
                    const day = parseInt(match[3], 10);
                    const hour = parseInt(match[4], 10);
                    const minute = parseInt(match[5], 10);
                    const second = parseInt(match[6], 10);
                    const dateObj = new Date(year, month, day, hour, minute, second);
                    return Math.floor(dateObj.getTime() / 1000);
                }
                console.warn("Could not parse timestamp from filename:", filename);
                return null;
            }

            // --- Monitoring Functions ---
            async function fetchAndDisplayLatestForMonitor() {
                if (!isMonitoringActive) return;
                const data = await fetchData("getLatestPhoto", {});
                let newPhotoEpochTime = null;

                if (data && data.latest_photo && data.latest_photo.filename) {
                    const newPhoto = data.latest_photo;
                    newPhotoEpochTime = parseTimestampFromFilename(newPhoto.filename);

                    if (newPhoto.filename !== currentMonitorPhoto.filename) {
                        lastPollCount = 0;
                        
                        currentMonitorPhoto.filename = newPhoto.filename;
                        currentMonitorPhoto.imageUrl = newPhoto.image_url;
                        currentMonitorPhoto.timestampEpoch = newPhotoEpochTime;
                        currentMonitorPhoto.filesize = newPhoto.filesize;
                        
                        monitorImageEl.src = currentMonitorPhoto.imageUrl;
                        monitorFilenameEl.textContent = currentMonitorPhoto.filename;
                        monitorFilesizeEl.textContent = formatFileSize(currentMonitorPhoto.filesize);
                        
                        if (currentMonitorPhoto.timestampEpoch) {
                            const dateObj = new Date(currentMonitorPhoto.timestampEpoch * 1000);
                            monitorTimestampEl.textContent = dateObj.toLocaleString("zh-CN", { hour12: false });
                        } else {
                            monitorTimestampEl.textContent = "N/A";
                        }
                        
                        updateStatus("已更新为最新照片。", false);
                    } else {
                        // 没有获取到新照片，增加轮询计数
                        lastPollCount++;
                    }

                    if (currentMonitorPhoto.timestampEpoch) {
                        scheduleNextMonitorPoll(currentMonitorPhoto.timestampEpoch);
                    } else {
                        console.warn("Monitor: No valid timestamp. Retrying.");
                        if (monitorTimeoutId) clearTimeout(monitorTimeoutId);
                        monitorTimeoutId = setTimeout(fetchAndDisplayLatestForMonitor, MONITOR_RETRY_NO_NEW_PHOTO_MS);
                    }
                } else {
                    lastPollCount++;
                    updateStatus("暂无照片可监控，稍后重试。", false);
                    if (monitorTimeoutId) clearTimeout(monitorTimeoutId);
                    monitorTimeoutId = setTimeout(fetchAndDisplayLatestForMonitor, MONITOR_RETRY_NO_PHOTO_AT_ALL_MS);
                }
            }
            function scheduleNextMonitorPoll(lastPhotoEpochSeconds) {
                if (!isMonitoringActive) return;
                if (monitorTimeoutId) clearTimeout(monitorTimeoutId);

                const nowMs = Date.now();
                const lastPhotoMs = lastPhotoEpochSeconds * 1000;
                
                // 计算下次轮询时间
                // 基准时间 + (轮询次数 × 间隔时间) + 偏移量
                const nextPollTimeMs = lastPhotoMs + ((lastPollCount + 1) * CAMERA_INTERVAL_MS) + POLLING_OFFSET_MS;
                
                let delayMs = nextPollTimeMs - nowMs;
                
                // 如果计算出的延迟时间小于最小轮询间隔，则使用最小轮询间隔
                if (delayMs < POLLING_OFFSET_MS) {
                    delayMs = CAMERA_INTERVAL_MS + POLLING_OFFSET_MS;
                }

                monitorTimeoutId = setTimeout(fetchAndDisplayLatestForMonitor, delayMs);
            }
            startMonitorBtn.onclick = async () => {
                if (isMonitoringActive) return;
                isMonitoringActive = true;
                if (currentState.level > 0 || currentState.date) {
                    saveCurrentStateToHistory();
                }
                displayArea.style.display = "none";
                currentLevelInfoContainer.style.display = "none";
                datePickerEl.disabled = true;
                backButton.style.display = "none";
                startPhotoSlideshowBtn.disabled = true;
                monitoringSection.style.display = "block";
                startMonitorBtn.style.display = "none";
                stopMonitorBtn.style.display = "inline-block";
                updateStatus("启动实时监控...", false);
                await fetchAndDisplayLatestForMonitor();
            };
            stopMonitorBtn.onclick = () => {
                if (!isMonitoringActive) return;
                isMonitoringActive = false;
                if (monitorTimeoutId) clearTimeout(monitorTimeoutId);
                monitorTimeoutId = null;
                monitoringSection.style.display = "none";
                startMonitorBtn.style.display = "inline-block";
                stopMonitorBtn.style.display = "none";
                displayArea.style.display = "grid";
                currentLevelInfoContainer.style.display = "block";
                datePickerEl.disabled = false;
                startPhotoSlideshowBtn.disabled = false;
                if (historyStack.length > 0) {
                    backButton.click();
                } else {
                    const cDP = flatpickrInstance.selectedDates.length > 0 ? flatpickrInstance.formatDate(flatpickrInstance.selectedDates[0], "Y-m-d") : "";
                    currentState = { level: 0, date: cDP, hour: "", intervalSlot: "", minute: "" };
                    if (currentState.date) currentState.level = 1;
                    updateUI();
                }
                updateStatus("实时监控已停止。", false);
            };

            // --- Initialization ---
            async function initializeApp() {
                const storedTheme = localStorage.getItem("galleryTheme") || "light";
                applyTheme(storedTheme);

                const earliestDateData = await fetchData("getEarliestDate", {});
                let minDateOption = null;
                if (earliestDateData && earliestDateData.earliestDate) {
                    minDateOption = earliestDateData.earliestDate;
                } else {
                    console.warn("无法获取最早照片日期。");
                }

                flatpickrInstance = flatpickr(datePickerEl, {
                    dateFormat: "Y-m-d",
                    maxDate: "today",
                    minDate: minDateOption,
                    // defaultDate will be set in onReady to ensure minDate is considered
                    onReady: function (selectedDates, dateStr, instance) {
                        const todayFull = new Date();
                        const todayStr = instance.formatDate(todayFull, "Y-m-d");
                        let dateToSetAsDefault = todayStr;

                        if (minDateOption) {
                            // Ensure minDateOption is a string like "YYYY-MM-DD"
                            if (todayStr < minDateOption) {
                                dateToSetAsDefault = minDateOption;
                            }
                        }

                        if (dateToSetAsDefault) {
                            const defaultDateObj = instance.parseDate(dateToSetAsDefault, "Y-m-d");
                            if (defaultDateObj) {
                                instance.jumpToDate(defaultDateObj); // Jump calendar to the month
                            }
                            // Set date AND trigger onChange to load data.
                            instance.setDate(dateToSetAsDefault, true);
                        } else {
                            // No valid date found (e.g., minDate is in future and today is also in future w.r.t maxDate)
                            // This case should be rare if maxDate is "today".
                            updateUI(); // Show "请选择一个日期" message
                        }
                    },
                    onChange: function (selectedDates, dateStr, instance) {
                        if (isMonitoringActive || isGlobalSlideshowActive) return;
                        // Only process if a date is selected and it's different from current,
                        // OR if it's an initial load from level 0 (dateStr might be same as empty currentState.date initially)
                        if (dateStr && (dateStr !== currentState.date || currentState.level === 0)) {
                            if (currentState.level > 0 && currentState.date && currentState.date !== dateStr) {
                                saveCurrentStateToHistory();
                            }
                            currentState = { level: 1, date: dateStr, hour: "", intervalSlot: "", minute: "" };
                            historyStack = []; // New date selection is a new root for history
                            updateUI();
                        } else if (!dateStr && currentState.date) {
                            // Date selection was cleared by user
                            currentState = { level: 0, date: "", hour: "", intervalSlot: "", minute: "" };
                            historyStack = [];
                            updateUI();
                        }
                    },
                });
                // If onReady did not trigger an onChange (e.g. if dateToSetAsDefault was already selected by flatpickr by chance)
                // and we are still at level 0, call updateUI to show initial message.
                if (currentState.level === 0 && (!flatpickrInstance || flatpickrInstance.selectedDates.length === 0)) {
                    updateUI();
                }
            }

            document.addEventListener("DOMContentLoaded", initializeApp);

            // --- Fetch and render functions for gallery levels ---
            async function fetchDailySummary(dateStr) {
                const data = await fetchData("getDailySummary", { date: dateStr });
                if (data && data.hourly_previews) {
                    renderPreviews(
                        data.hourly_previews,
                        (item) => {
                            navigateToLevelAndSaveHistory(2, { date: currentState.date, hour: item.hour });
                        },
                        "daily-view-grid",
                        (item) => `<img src="${item.preview_image_url}" alt="Hour ${item.hour}" loading="lazy"><p>${item.hour}:00 (该小时首张)</p>`
                    );
                    if (data.hourly_previews.length > 0) {
                        updateStatus(`显示 ${dateStr} 的全天预览，共 ${data.hourly_previews.length} 个时段有照片。`, false);
                    }
                } else {
                    displayArea.innerHTML = "";
                }
            }
            async function fetchHourlySummary(dateStr, hourStr) {
                const data = await fetchData("getHourlySummary", { date: dateStr, hour: hourStr });
                if (data && data.ten_minute_previews) {
                    renderPreviews(
                        data.ten_minute_previews,
                        (item) => {
                            navigateToLevelAndSaveHistory(3, { date: currentState.date, hour: currentState.hour, intervalSlot: item.interval_slot });
                        },
                        "hourly-view-grid",
                        (item) => `<img src="${item.preview_image_url}" alt="${item.label}" loading="lazy"><p>${item.label}</p>`
                    );
                    if (data.ten_minute_previews.length > 0) {
                        updateStatus(`显示 ${dateStr} > ${hourStr}:00~${hourStr}:59 的每10分钟预览，共 ${data.ten_minute_previews.length} 个时段有照片。`, false);
                    }
                } else {
                    displayArea.innerHTML = "";
                }
            }
            async function fetchTenMinuteSummary(dateStr, hourStr, intervalSlot) {
                const data = await fetchData("getTenMinuteSummary", { date: dateStr, hour: hourStr, interval_slot: intervalSlot });
                if (data && data.minute_previews) {
                    renderPreviews(
                        data.minute_previews,
                        (item) => {
                            navigateToLevelAndSaveHistory(4, { date: currentState.date, hour: currentState.hour, intervalSlot: currentState.intervalSlot, minute: item.minute });
                        },
                        "ten-minute-view-grid",
                        (item) => `<img src="${item.preview_image_url}" alt="Minute ${item.minute}" loading="lazy"><p>${hourStr}:${String(item.minute).padStart(2, '0')} (该分钟首张)</p>`
                    );
                    if (data.minute_previews.length > 0) {
                        const startMin = intervalSlot * 10;
                        const endMin = startMin + 9;
                        updateStatus(`显示 ${dateStr} > ${hourStr}:${String(startMin).padStart(2, '0')}~${hourStr}:${String(endMin).padStart(2, '0')} 的每分钟预览，共 ${data.minute_previews.length} 个分钟有照片。`, false);
                    }
                } else {
                    displayArea.innerHTML = "";
                }
            }
            async function fetchMinutePhotos(dateStr, hourStr, minuteStr) {
                const data = await fetchData("getMinutePhotos", { date: dateStr, hour: hourStr, minute: minuteStr });
                if (data && data.photos) {
                    renderMinutePhotos(data.photos);
                    if (data.photos.length > 0) {
                        const minuteStart = Math.floor(minuteStr / 10) * 10;
                        const minuteEnd = minuteStart + 9;
                        updateStatus(`显示 ${dateStr} > ${hourStr}:${String(minuteStart).padStart(2, '0')}~${hourStr}:${String(minuteEnd).padStart(2, '0')} 的 ${data.photos.length} 张照片。`, false);
                    }
                } else {
                    displayArea.innerHTML = "";
                }
            }

            // 添加一个格式化文件大小的函数
            function formatFileSize(bytes) {
                if (!bytes || bytes === 0) return 'N/A';
                const units = ['B', 'KB', 'MB', 'GB'];
                let size = bytes;
                let unitIndex = 0;
                while (size >= 1024 && unitIndex < units.length - 1) {
                    size /= 1024;
                    unitIndex++;
                }
                return `${size.toFixed(2)} ${units[unitIndex]}`;
            }

            // 添加最大化功能
            function setupMaximizeButtons() {
                document.querySelectorAll('.maximize-btn').forEach(btn => {
                    btn.addEventListener('click', function() {
                        const container = this.closest('.lightbox-image-container');
                        const isMaximized = container.classList.toggle('maximized');
                        
                        // 更新按钮图标
                        const path = this.querySelector('path');
                        if (isMaximized) {
                            path.setAttribute('d', 'M3 3h7v2H5v5H3V3m18 0v7h-2V5h-5V3h7M3 21v-7h2v5h5v2H3m18-7v7h-7v-2h5v-5h2');
                            this.title = '还原';
                        } else {
                            path.setAttribute('d', 'M3 3h7v2H5v5H3V3m18 0v7h-2V5h-5V3h7M3 21v-7h2v5h5v2H3m18-7v7h-7v-2h5v-5h2');
                            this.title = '最大化';
                        }
                    });
                });
            }

            // 在页面加载完成后初始化最大化按钮
            document.addEventListener('DOMContentLoaded', function() {
                setupMaximizeButtons();
                // ... 其他初始化代码 ...
            });

            // 优化轮播和监控模式的切换动画
            function updateMonitoringDisplay(show) {
                const monitorSection = document.getElementById('monitoringSection');
                monitorSection.style.transition = 'opacity 0.3s ease';
                
                if (show) {
                    monitorSection.style.display = 'block';
                    setTimeout(() => {
                        monitorSection.style.opacity = '1';
                    }, 10);
                } else {
                    monitorSection.style.opacity = '0';
                    setTimeout(() => {
                        monitorSection.style.display = 'none';
                    }, 300);
                }
            }

            // 添加图片加载错误处理
            function handleImageError(img) {
                img.onerror = () => {
                    img.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="14">加载失败</text></svg>';
                    img.style.background = '#f5f5f5';
                };
            }

            // 修改现有的图片加载相关代码
            document.querySelectorAll('img').forEach(handleImageError);
        </script>
    </body>
</html>

