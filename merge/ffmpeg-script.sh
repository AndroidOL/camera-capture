#!/bin/bash

# ==============================================================================
# Daily Automated Photo-to-Video Processing Script with Advanced Features
#
# Version: 1.4.3
# Author: Your Name/INFO (with assistance from AI, incorporating colleague's feedback)
# Date: 2025-05-15
#
# Changes in 1.4.3:
#   - Corrected argument passing for `execute_cmd` wrapper function and updated all its call sites.
#     The first argument to execute_cmd is now the description, followed by the command and its arguments.
#   - Added '--' to `logger` command before the message payload to prevent misinterpretation of messages
#     starting with '-' as options.
#   - Minor updates to comments and log messages for clarity.
#
# Description: (Same as v1.4.0)
# ...
# ==============================================================================

# --- Configuration Parameters ---
readonly SCRIPT_VERSION="1.5.1"
# ... (Rest of CONFIGURATION PARAMETERS are IDENTICAL to v1.4.2) ...
readonly SCRIPT_NAME="$(basename "$0")"

readonly ARMBIAN_USER="tianhao"
readonly ARMBIAN_IP="am40.tianhao.me"
readonly ARMBIAN_IMAGE_BASE_DIR="/opt/camera/captures"      # No trailing slash

readonly RAMDISK_MOUNT_POINT="/mnt/ramdisk"
readonly RAMDISK_SIZE="5G" # legacy default; actual size will be computed dynamically at mount time
readonly IMAGE_STAGING_PARENT_DIR_ON_RAMDISK="${RAMDISK_MOUNT_POINT}/image_source" # No trailing slash
readonly FFMPEG_TEMP_OUTPUT_PARENT_DIR_ON_RAMDISK="${RAMDISK_MOUNT_POINT}/ffmpeg_tmp" # No trailing slash

readonly PRIMARY_FINAL_VIDEO_TARGET_BASE_DIR="/opt/camera/merge"    # No trailing slash
readonly FALLBACK_FINAL_VIDEO_TARGET_BASE_DIR="/opt/camera/merge-emmc" # No trailing slash
readonly FFMPEG_EXE_PATH="/usr/bin/ffmpeg"

readonly OUTPUT_FPS="6"
readonly VIDEO_CODEC="hevc_rkmpp"
readonly VIDEO_BITRATE="1M"
readonly VIDEO_QUALITY="26"

readonly LOG_FILE="/var/log/daily_photo_to_video.log"
readonly LOG_MAX_SIZE_KB=10240 
readonly DEFAULT_ENABLE_SYSLOG_LOGGING="true"
readonly SYSLOG_TAG="${SCRIPT_NAME}" 

readonly MAX_CATCH_UP_DAYS=10
readonly MIN_VALID_VIDEO_SIZE_KB=10 

readonly DEFAULT_DRY_RUN_CONFIG="false" 
readonly DEFAULT_ENABLE_LOCKING="true"  
readonly DEFAULT_SCRIPT_DEBUG_TRACE="false" 

readonly LOCK_FILE_DIR="/var/lock" 
readonly LOCK_FILE_NAME="${SCRIPT_NAME}.lock"
readonly LOCK_FD=200 
# --- End of Configuration Parameters ---

# --- PushPlus Notification Configuration ---
readonly DEFAULT_ENABLE_PUSHPLUS="true"
readonly PUSHPLUS_API_URL="https://www.pushplus.plus/send"

# --- Reliability/Timeout Configuration ---
readonly RSYNC_MAX_ATTEMPTS="3"
readonly RSYNC_RETRY_DELAY_SEC="10"
readonly RSYNC_TIMEOUT_SEC="900"              # hard timeout wrapper seconds (if `timeout` is available)
readonly FFMPEG_MAX_ATTEMPTS="2"
readonly FFMPEG_RETRY_DELAY_SEC="15"
readonly FFMPEG_TIMEOUT_SEC="1800"            # hard timeout wrapper seconds (if `timeout` is available)
readonly ENABLE_HARD_TIMEOUTS_DEFAULT="true"  # can be overridden via env: ENABLE_HARD_TIMEOUTS_ENV_OVERRIDE

readonly TIMEOUT_CMD="$(command -v timeout || echo "")"
readonly FFPROBE_EXE_PATH_GUESS="$(dirname "${FFMPEG_EXE_PATH}")/ffprobe"

# --- Dynamic Ramdisk Sizing Config ---
readonly RAMDISK_MIN_SIZE_MB_DEFAULT="5120"   # 5.0G min as requested
readonly RAMDISK_MAX_SIZE_MB_DEFAULT="6144"   # cap around 6G by default
readonly RAMDISK_RESERVE_MB_DEFAULT="1024"    # keep ~1G headroom
RAMDISK_MIN_SIZE_MB="${RAMDISK_MIN_SIZE_MB_ENV_OVERRIDE:-${RAMDISK_MIN_SIZE_MB_DEFAULT}}"
RAMDISK_MAX_SIZE_MB="${RAMDISK_MAX_SIZE_MB_ENV_OVERRIDE:-${RAMDISK_MAX_SIZE_MB_DEFAULT}}"
RAMDISK_RESERVE_MB="${RAMDISK_RESERVE_MB_ENV_OVERRIDE:-${RAMDISK_RESERVE_MB_DEFAULT}}"

# --- Output Size Estimation (permille to avoid floating point) ---
readonly OUTPUT_ESTIMATE_INPUT_RATIO_PERMILLE_DEFAULT="100"   # 0.100 = 10%
readonly OUTPUT_ESTIMATE_HEADROOM_PERMILLE_DEFAULT="120"      # 1.20 = +20%
OUTPUT_ESTIMATE_INPUT_RATIO_PERMILLE="${OUTPUT_ESTIMATE_INPUT_RATIO_PERMILLE_ENV_OVERRIDE:-${OUTPUT_ESTIMATE_INPUT_RATIO_PERMILLE_DEFAULT}}"
OUTPUT_ESTIMATE_HEADROOM_PERMILLE="${OUTPUT_ESTIMATE_HEADROOM_PERMILLE_ENV_OVERRIDE:-${OUTPUT_ESTIMATE_HEADROOM_PERMILLE_DEFAULT}}"


# --- Script Internal Setup ---
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export TZ="Asia/Shanghai" 
umask 027 

set -e 
set -u 
set -o pipefail 
set -o errtrace 

DRY_RUN="${SCRIPT_DRY_RUN_ENV_OVERRIDE:-${DEFAULT_DRY_RUN_CONFIG}}"
ENABLE_LOCKING="${SCRIPT_ENABLE_LOCKING_ENV_OVERRIDE:-${DEFAULT_ENABLE_LOCKING}}"
ENABLE_SYSLOG_LOGGING="${SCRIPT_SYSLOG_LOG_ENV_OVERRIDE:-${DEFAULT_ENABLE_SYSLOG_LOGGING}}"
SCRIPT_DEBUG_TRACE="${SCRIPT_DEBUG_TRACE_ENV_OVERRIDE:-${DEFAULT_SCRIPT_DEBUG_TRACE}}"
ENABLE_HARD_TIMEOUTS="${ENABLE_HARD_TIMEOUTS_ENV_OVERRIDE:-${ENABLE_HARD_TIMEOUTS_DEFAULT}}"
ENABLE_PUSHPLUS="${ENABLE_PUSHPLUS_ENV_OVERRIDE:-${DEFAULT_ENABLE_PUSHPLUS}}"
PUSHPLUS_TOKEN="${PUSHPLUS_TOKEN_ENV_OVERRIDE:-}" # 从环境注入，避免硬编码

if [[ "${SCRIPT_DEBUG_TRACE,,}" == "true" ]]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') [CONFIG] Bash execution trace (set -x) enabled." >&2 
    set -x
fi

RUN_ID=$(uuidgen || echo "uuidgen-failed-$(date +%s%N)") 
if [[ -z "${RUN_ID}" || "${RUN_ID}" == "uuidgen-failed-"* ]]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') [CRITICAL] - Failed to generate RUN_ID. uuidgen might be missing (try 'apt install uuid-runtime') or failed. Aborting." >&2
    exit 2 
fi

SCRIPT_MOUNTED_RAMDISK=false
CURRENT_IMAGE_STAGING_DIR_FOR_TRAP="" 
FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP=""    
EFFECTIVE_FINAL_VIDEO_TARGET_BASE_DIR="${PRIMARY_FINAL_VIDEO_TARGET_BASE_DIR}" 
DO_CATCH_UP_PROCESSING=true 
CURRENT_PROCESSING_DATE_FOR_TRAP="N/A" 
PREVIOUS_SCRIPT_RAMDISK_DETECTED=false 

# --- Statistics (per-run) ---
STATS_NUM_DATES_ATTEMPTED=0
STATS_NUM_DATES_SUCCEEDED=0
STATS_NUM_DATES_FAILED=0
STATS_TOTAL_PHOTOS_SYNCED=0
STATS_TOTAL_RSYNC_ATTEMPTS=0
STATS_TOTAL_RSYNC_RETRIES=0
STATS_TOTAL_FFMPEG_ATTEMPTS=0
STATS_TOTAL_FFMPEG_RETRIES=0
STATS_LAST_NUM_PHOTOS=0
STATS_LAST_VIDEO_SECONDS=0
STATS_TOTAL_OUTPUT_VIDEO_SECONDS=0
STATS_LAST_VIDEO_SIZE_BYTES=0
STATS_TOTAL_OUTPUT_VIDEO_SIZE_BYTES=0
LAST_DATE_PROCESSED=""
LAST_FINAL_VIDEO_PATH=""
LAST_ENCODE_DIRECT="false"


# --- Logging Functions ---
_log_base() {
    local level_input="$1"; shift; local message="$*"
    local level_formatted; printf -v level_formatted "%-7s" "${level_input}" 
    local level_lowercase="${level_input,,}"          
    local log_line; log_line="$(date '+%Y-%m-%d %H:%M:%S') [RUN_ID: ${RUN_ID}] [${level_formatted}] - ${message}"
    
    echo "${log_line}" >&2 
    echo "${log_line}" >> "${LOG_FILE}" 

    if [[ "${ENABLE_SYSLOG_LOGGING,,}" == "true" ]]; then
        case "${level_lowercase}" in
            info|warning|error|debug|notice|crit|alert|emerg) 
                # MODIFICATION v1.4.3: Added -- before "${message}"
                ( logger -t "${SYSLOG_TAG}[${RUN_ID}]" -p "user.${level_lowercase}" -- "${message}" ) || \
                echo "$(date '+%Y-%m-%d %H:%M:%S') [RUN_ID: ${RUN_ID}] [WARNING] - Failed to write to syslog for message: ${message}" >> "${LOG_FILE}"
                ;;
            *) 
                ( logger -t "${SYSLOG_TAG}[${RUN_ID}]" -p "user.notice" -- "Unknown log level '${level_input}': ${message}" ) || \
                echo "$(date '+%Y-%m-%d %H:%M:%S') [RUN_ID: ${RUN_ID}] [WARNING] - Failed to write to syslog (unknown level '${level_input}') for message: ${message}" >> "${LOG_FILE}"
                ;;
        esac
    fi
}
log_info() { _log_base "INFO" "$@"; }
log_warn() { _log_base "WARNING" "$@"; }
log_error() { _log_base "ERROR" "$@"; }


# --- Dry-Run Wrapper Function ---
# MODIFICATION v1.4.3: Description is FIRST argument, then command and its args
execute_cmd() {
    local cmd_description="$1" 
    shift # Remove description from argument list
    # Now "$@" contains the command and all its arguments
    local cmd_and_args=("$@") 
    local cmd_string_for_log # For display purposes
    # Safely quote all parts of the command for logging
    printf -v cmd_string_for_log "%q " "${cmd_and_args[@]}"

    if [[ "${DRY_RUN,,}" == "true" ]]; then
        log_info "[DRY-RUN] Would execute (${cmd_description}): ${cmd_string_for_log}"
        return 0 
    else
        log_info "Executing (${cmd_description}): ${cmd_string_for_log}"
        "${cmd_and_args[@]}" # Execute command array
        local cmd_exit_status=$?
        if [ ${cmd_exit_status} -ne 0 ]; then
            # ERR trap will also log this, but specific context here can be useful.
            log_warn "Execution of (${cmd_description}) returned non-zero status ${cmd_exit_status}."
        fi
        return ${cmd_exit_status}
    fi
}

# --- Trap Definitions ---
# (cleanup_on_exit and handle_error trap functions are IDENTICAL to v1.4.2,
#  but calls to execute_cmd within cleanup_on_exit will use the new signature)
cleanup_on_exit() {
    local exit_status=$1  
    log_info "--- Starting Main Cleanup (Script Exit Status: ${exit_status}, Date Context: ${CURRENT_PROCESSING_DATE_FOR_TRAP}) ---"

    if [ -n "${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}" ] && [ -f "${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}" ]; then
        log_warn "Main cleanup: Found leftover ffmpeg temp video: ${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}."
        execute_cmd "Delete leftover temp video" "rm" "-f" "${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}"
    fi
    if [ -n "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}" ] && [ -d "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}" ]; then
        log_warn "Main cleanup: Found leftover image staging directory: ${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}."
        execute_cmd "Delete leftover image staging directory" "rm" "-rf" "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}"
    fi
    
    if [ -d "${FFMPEG_TEMP_OUTPUT_PARENT_DIR_ON_RAMDISK}" ] && ! find "${FFMPEG_TEMP_OUTPUT_PARENT_DIR_ON_RAMDISK}" -mindepth 1 -print -quit | grep -q .; then 
        log_info "Main cleanup: Attempting to delete empty ffmpeg temp parent directory: ${FFMPEG_TEMP_OUTPUT_PARENT_DIR_ON_RAMDISK}"
        execute_cmd "Delete empty ffmpeg temp parent" "rmdir" "${FFMPEG_TEMP_OUTPUT_PARENT_DIR_ON_RAMDISK}"
    fi
    if [ -d "${IMAGE_STAGING_PARENT_DIR_ON_RAMDISK}" ] && ! find "${IMAGE_STAGING_PARENT_DIR_ON_RAMDISK}" -mindepth 1 -print -quit | grep -q .; then 
         log_info "Main cleanup: Attempting to delete empty image staging parent directory: ${IMAGE_STAGING_PARENT_DIR_ON_RAMDISK}"
         execute_cmd "Delete empty image staging parent" "rmdir" "${IMAGE_STAGING_PARENT_DIR_ON_RAMDISK}"
    fi

    if [[ "${SCRIPT_MOUNTED_RAMDISK,,}" == "true" ]]; then # Case-insensitive
        if [[ "${DRY_RUN,,}" == "true" ]]; then 
            log_info "[DRY-RUN] Would unmount ramdisk: ${RAMDISK_MOUNT_POINT}"
        elif mountpoint -q "${RAMDISK_MOUNT_POINT}"; then 
            log_info "Main cleanup: Attempting to unmount ramdisk: ${RAMDISK_MOUNT_POINT}"
            if execute_cmd "Unmount ramdisk" "umount" "${RAMDISK_MOUNT_POINT}"; then
                log_info "Main cleanup: Ramdisk unmounted successfully."
            else 
                log_error "Main cleanup: Failed to unmount ramdisk ${RAMDISK_MOUNT_POINT}. It might be in use."
            fi
        else 
            log_warn "Main cleanup: Ramdisk ${RAMDISK_MOUNT_POINT} was already unmounted prior to explicit cleanup."
        fi
    else
        log_info "Main cleanup: Ramdisk was not mounted by this script, so not attempting to unmount it."
    fi

    if [[ "${ENABLE_LOCKING,,}" == "true" ]]; then # Case-insensitive
        if exec "${LOCK_FD}>&-" 2>/dev/null; then
            log_info "Main cleanup: Script lock FD ${LOCK_FD} explicitly closed, lock released."
        else
            log_warn "Main cleanup: Attempt to close lock FD ${LOCK_FD} did not report success."
        fi
    fi

    # Append per-run statistics near very end
    log_stats_summary

    # Build and send PushPlus markdown summary
    if [[ "${ENABLE_PUSHPLUS,,}" == "true" && -n "${PUSHPLUS_TOKEN}" ]]; then
        local end_epoch=$(date +%s)
        local elapsed=$(( end_epoch - START_EPOCH ))
        local md_body
        md_body=$(cat <<MD_EOF
## 每日相册转码任务结果

- **脚本版本**: v${SCRIPT_VERSION}
- **运行ID**: ${RUN_ID}
- **执行用户**: $(whoami)
- **执行模式**: ${DRY_RUN}
- **锁启用**: ${ENABLE_LOCKING}
- **Ramdisk**: ${RAMDISK_MOUNT_POINT} (mounted by script: ${SCRIPT_MOUNTED_RAMDISK})

### 处理摘要
- **日期尝试**: ${STATS_NUM_DATES_ATTEMPTED}
- **成功**: ${STATS_NUM_DATES_SUCCEEDED}
- **失败**: ${STATS_NUM_DATES_FAILED}
- **总照片数**: ${STATS_TOTAL_PHOTOS_SYNCED}

### 编解码
- **Rsync 尝试/重试**: ${STATS_TOTAL_RSYNC_ATTEMPTS} / ${STATS_TOTAL_RSYNC_RETRIES}
- **FFmpeg 尝试/重试**: ${STATS_TOTAL_FFMPEG_ATTEMPTS} / ${STATS_TOTAL_FFMPEG_RETRIES}

### 输出
- **最新视频时长**: ${STATS_LAST_VIDEO_SECONDS} 秒 ($(format_hms ${STATS_LAST_VIDEO_SECONDS}))
- **累计视频时长**: ${STATS_TOTAL_OUTPUT_VIDEO_SECONDS} 秒 ($(format_hms ${STATS_TOTAL_OUTPUT_VIDEO_SECONDS}))
- **最新视频大小**: ${STATS_LAST_VIDEO_SIZE_BYTES} B
- **累计视频大小**: ${STATS_TOTAL_OUTPUT_VIDEO_SIZE_BYTES} B
- **最后处理日期**: ${LAST_DATE_PROCESSED}
- **最终视频路径**: ${LAST_FINAL_VIDEO_PATH}
- **是否直写最终路径**: ${LAST_ENCODE_DIRECT}

### 耗时
- **总耗时**: ${elapsed} 秒 ($(format_hms ${elapsed}))
MD_EOF
)
        # JSON-stringify markdown
        local md_json
        md_json=$(printf '%s' "${md_body}" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e ':a;N;$!ba;s/\n/\\n/g')
        md_json="\"${md_json}\""

        pushplus_send_markdown "相册转码结果 (RUN_ID:${RUN_ID})" "${md_json}" || log_error "Failed to send PushPlus notification."
    fi

    log_info "--- Main Cleanup Finished (Exit Status: ${exit_status}) ---"
    if [ "${exit_status}" -ne 0 ]; then
      log_error "Script is exiting with an overall error status: ${exit_status}."
    fi
}
trap 'cleanup_on_exit $?' EXIT

handle_error() {
    local err_lineno="$1"; local err_command="$2"; local err_exit_status="$3"
    log_error "ERR trap: Script error near line ${err_lineno}. Last command recorded: '${err_command}'. Exit status: ${err_exit_status}. Date context: ${CURRENT_PROCESSING_DATE_FOR_TRAP}."
}
trap 'handle_error $LINENO "$BASH_COMMAND" $?' ERR

# Termination signals
trap 'log_error "Received SIGINT. Aborting run gracefully."; exit 130' INT
trap 'log_error "Received SIGTERM. Aborting run gracefully."; exit 143' TERM


# --- Utility and Core Logic Functions ---
# (rotate_log, check_dependencies, setup_ramdisk_if_needed, determine_target_config, 
#  select_date_to_process, process_single_date now use the new execute_cmd signature)

# --- Reliability Helpers ---
supports_hard_timeouts() {
    [[ -n "${TIMEOUT_CMD}" && "${ENABLE_HARD_TIMEOUTS,,}" == "true" ]]
}

safe_sleep() { # sleep with guard against negative/empty
    local seconds="$1"
    if [[ -z "${seconds}" || "${seconds}" -lt 1 ]]; then
        seconds=1
    fi
    sleep "${seconds}"
}

# run_with_retry CATEGORY DESCRIPTION MAX_ATTEMPTS RETRY_DELAY_SEC TIMEOUT_SEC ACCEPTABLE_CODES_CSV -- CMD ARGS...
run_with_retry() {
    local category="$1"; shift
    local desc="$1"; shift
    local max_attempts="$1"; shift
    local retry_delay="$1"; shift
    local timeout_sec="$1"; shift
    local acceptable_csv="$1"; shift
    # Expect -- separator before command
    if [[ "$1" != "--" ]]; then
        log_warn "run_with_retry called without -- separator for ${desc}. Proceeding anyway."
    else
        shift
    fi
    local -a cmd=("$@")

    local attempt=1
    local rc=0

    while :; do
        local attempt_note="attempt ${attempt}/${max_attempts}"
        if supports_hard_timeouts && [[ -n "${timeout_sec}" && "${timeout_sec}" -gt 0 ]]; then
            local timeout_duration="${timeout_sec}s"
            local kill_after="5s"
            # 预检测 timeout 支持的标志，尽量使用 --preserve-status 与 --foreground，避免残留与状态丢失
            local -a timeout_flags=("-k" "${kill_after}" "${timeout_duration}")
            if "${TIMEOUT_CMD}" --help 2>&1 | grep -q -- "--preserve-status"; then
                timeout_flags=("--preserve-status" "${timeout_flags[@]}")
            fi
            if "${TIMEOUT_CMD}" --help 2>&1 | grep -q -- "--foreground"; then
                timeout_flags=("--foreground" "${timeout_flags[@]}")
            fi
            log_info "${desc} with timeout ${timeout_duration} (${attempt_note})"
            if "${TIMEOUT_CMD}" "${timeout_flags[@]}" "${cmd[@]}"; then rc=0; else rc=$?; fi
        else
            log_info "${desc} (${attempt_note})"
            if "${cmd[@]}"; then rc=0; else rc=$?; fi
        fi

        # Stats by category
        case "${category}" in
            RSYNC)
                STATS_TOTAL_RSYNC_ATTEMPTS=$((STATS_TOTAL_RSYNC_ATTEMPTS + 1))
                ;;
            FFMPEG)
                STATS_TOTAL_FFMPEG_ATTEMPTS=$((STATS_TOTAL_FFMPEG_ATTEMPTS + 1))
                ;;
        esac

        # Check acceptable non-zero codes
        if [[ ${rc} -ne 0 && -n "${acceptable_csv}" ]]; then
            IFS=',' read -r -a acceptable_arr <<< "${acceptable_csv}"
            local code
            for code in "${acceptable_arr[@]}"; do
                if [[ "${rc}" -eq "${code}" ]]; then
                    log_warn "${desc} returned acceptable non-zero code ${rc}; treating as success."
                    rc=0
                    break
                fi
            done
        fi

        if [[ ${rc} -eq 0 ]]; then
            return 0
        fi

        if [[ ${attempt} -ge ${max_attempts} ]]; then
            log_error "${desc} failed after ${attempt} attempts. Last status: ${rc}."
            return ${rc}
        fi

        case "${category}" in
            RSYNC) STATS_TOTAL_RSYNC_RETRIES=$((STATS_TOTAL_RSYNC_RETRIES + 1)) ;;
            FFMPEG) STATS_TOTAL_FFMPEG_RETRIES=$((STATS_TOTAL_FFMPEG_RETRIES + 1)) ;;
        esac

        log_warn "${desc} failed with status ${rc}. Retrying after ${retry_delay}s..."
        safe_sleep "${retry_delay}"
        attempt=$((attempt + 1))
    done
}

# Compute duration in seconds using ffprobe when available
probe_video_duration_seconds() {
    local video_path="$1"
    local ffprobe_path="${FFPROBE_EXE_PATH_GUESS}"
    if [[ -x "${ffprobe_path}" ]]; then
        local duration
        duration=$("${ffprobe_path}" -v error -hide_banner -show_entries format=duration -of default=nw=1:nk=1 "${video_path}" 2>/dev/null || echo "0")
        # Truncate to integer seconds
        printf '%d\n' "${duration%%.*}" 2>/dev/null || echo 0
        return 0
    fi
    echo 0
}

parse_bitrate_to_bps() {
    local rate="$1"
    local lower="${rate,,}"
    local num
    case "${lower}" in
        *m)
            num="${lower%m}"
            echo $(( num * 1000000 ))
            ;;
        *k)
            num="${lower%k}"
            echo $(( num * 1000 ))
            ;;
        *)
            # assume plain bits per second integer
            echo $(( lower ))
            ;;
    esac
}

format_hms() {
    local total="$1"
    local h=$(( total / 3600 ))
    local m=$(( (total % 3600) / 60 ))
    local s=$(( total % 60 ))
    printf '%02d:%02d:%02d' "${h}" "${m}" "${s}"
}

log_stats_summary() {
    local end_epoch=$(date +%s)
    local elapsed=$(( end_epoch - START_EPOCH ))
    log_info "--- Run Statistics Summary ---"
    log_info "Dates attempted: ${STATS_NUM_DATES_ATTEMPTED}; succeeded: ${STATS_NUM_DATES_SUCCEEDED}; failed: ${STATS_NUM_DATES_FAILED}"
    log_info "Photos synced (total): ${STATS_TOTAL_PHOTOS_SYNCED}; last date photos: ${STATS_LAST_NUM_PHOTOS}"
    log_info "Rsync attempts: ${STATS_TOTAL_RSYNC_ATTEMPTS}; retries: ${STATS_TOTAL_RSYNC_RETRIES}"
    log_info "FFmpeg attempts: ${STATS_TOTAL_FFMPEG_ATTEMPTS}; retries: ${STATS_TOTAL_FFMPEG_RETRIES}"
    log_info "Video seconds (total): ${STATS_TOTAL_OUTPUT_VIDEO_SECONDS} ($(format_hms ${STATS_TOTAL_OUTPUT_VIDEO_SECONDS})); last video seconds: ${STATS_LAST_VIDEO_SECONDS}"
    log_info "Output size bytes (total): ${STATS_TOTAL_OUTPUT_VIDEO_SIZE_BYTES}; last size bytes: ${STATS_LAST_VIDEO_SIZE_BYTES}"
    log_info "Elapsed seconds: ${elapsed} ($(format_hms ${elapsed}))"
    log_info "--- End of Run Statistics ---"
}

md_escape() {
    # Escape characters that may break markdown formatting in push content
    # For simplicity, replace backticks and backslashes; do not over-escape code blocks
    sed -E 's/\\/\\\\/g; s/`/\`/g'
}

pushplus_send_markdown() {
    if [[ "${ENABLE_PUSHPLUS,,}" != "true" ]]; then
        return 0
    fi
    if [[ -z "${PUSHPLUS_TOKEN}" ]]; then
        log_warn "PushPlus enabled but PUSHPLUS_TOKEN is empty. Skip sending."
        return 0
    fi
    local title="$1"
    local content_md="$2"
    local payload
    # Build JSON safely. Use printf %q is not JSON-safe; construct with minimal escaping.
    # We rely on curl --data and set content-type application/json
    payload=$(cat <<JSON
{
  "token": "${PUSHPLUS_TOKEN}",
  "title": "${title}",
  "content": ${content_md},
  "template": "markdown",
  "channel": "wechat"
}
JSON
)
    # Send
    local http_code
    http_code=$(curl -sS -o /tmp/pushplus_resp_${RUN_ID}.json -w "%{http_code}" -H "Content-Type: application/json" -X POST "${PUSHPLUS_API_URL}" --data "${payload}" || echo "000")
    if [[ "${http_code}" != "200" ]]; then
        log_error "PushPlus HTTP status ${http_code}. Response: $(head -c 2000 /tmp/pushplus_resp_${RUN_ID}.json 2>/dev/null | tr -d '\n')"
        return 1
    fi
    local code_field
    code_field=$(grep -o '"code"[[:space:]]*:[[:space:]]*[0-9]+' /tmp/pushplus_resp_${RUN_ID}.json 2>/dev/null | head -n1 | sed -E 's/.*: *([0-9]+).*/\1/')
    if [[ -n "${code_field}" && "${code_field}" -ne 200 ]]; then
        log_error "PushPlus returned code=${code_field}. Raw: $(head -c 2000 /tmp/pushplus_resp_${RUN_ID}.json | tr -d '\n')"
        return 1
    fi
    log_info "PushPlus sent successfully."
}

rotate_log() { 
    if [ "${LOG_MAX_SIZE_KB}" -gt 0 ] && [ -f "${LOG_FILE}" ]; then
        local current_size_kb
        current_size_kb=$(du -k "${LOG_FILE}" 2>/dev/null | cut -f1) || current_size_kb=0 
        if [ -n "${current_size_kb}" ] && [ "${current_size_kb}" -gt "${LOG_MAX_SIZE_KB}" ]; then
            local backup_log_file="${LOG_FILE}.$(date +%Y%m%d_%H%M%S).bak" # MODIFIED v1.4.3
            log_info "Log file ${LOG_FILE} (size ${current_size_kb}KB) exceeds max size ${LOG_MAX_SIZE_KB}KB. Rotating."
            # These are meta-operations. Using execute_cmd for consistency though.
            if execute_cmd "Rotate log (mv)" "mv" "${LOG_FILE}" "${backup_log_file}"; then
                 execute_cmd "Rotate log (touch)" "touch" "${LOG_FILE}" || log_warn "Failed to touch new log file after rotation."
                 execute_cmd "Rotate log (chmod)" "chmod" "640" "${LOG_FILE}" || log_warn "Failed to chmod new log file."
                 log_info "Log file rotated to ${backup_log_file}."
            else
                 log_warn "Failed to move log file for rotation. Logging continues to old file."
            fi
        fi
    elif [ ! -f "${LOG_FILE}" ]; then 
        # Using execute_cmd for consistency
        if execute_cmd "Create log file (touch)" "touch" "${LOG_FILE}" && \
           execute_cmd "Create log file (chmod)" "chmod" "640" "${LOG_FILE}"; then
            log_info "Log file ${LOG_FILE} created."
        else
            echo "$(date '+%Y-%m-%d %H:%M:%S') [RUN_ID: ${RUN_ID}] [ERROR  ] - Failed to create log file ${LOG_FILE}." >&2
        fi
    fi
}

check_dependencies() { # No side-effects within, so no execute_cmd calls
    log_info "Checking script dependencies..."
    # ... enhanced with advisory checks for optional tools
    local missing_deps=0
    local dep
    for dep in rsync "${FFMPEG_EXE_PATH}" date find mkdir rm stat tee du mv wc mountpoint cp umount mount ssh grep sort head dirname uuidgen flock logger curl; do
        if ! command -v "${dep}" &> /dev/null; then
            if [ "${dep}" == "uuidgen" ]; then 
                log_error "Critical dependency missing: ${dep}. Consider installing 'uuid-runtime' package or similar."
            else
                log_error "Critical dependency missing: ${dep}."
            fi
            missing_deps=1
        fi
    done
    # Optional tools: timeout, ffprobe
    if [[ -z "${TIMEOUT_CMD}" ]]; then
        log_warn "Optional tool 'timeout' not found. Hard timeouts will be disabled."
        ENABLE_HARD_TIMEOUTS="false"
    fi
    if [[ ! -x "${FFPROBE_EXE_PATH_GUESS}" ]]; then
        log_warn "Optional tool 'ffprobe' not found at ${FFPROBE_EXE_PATH_GUESS}. Video duration stats will be 0."
    fi
    if [ "${missing_deps}" -eq 1 ]; then
        log_error "One or more critical dependencies are missing. Exiting."
        exit 1 
    fi
    log_info "All critical dependencies found."
}

setup_ramdisk_if_needed() { 
    log_info "Checking and setting up ramdisk at ${RAMDISK_MOUNT_POINT}..."
    execute_cmd "Create parent for ramdisk mount point" "mkdir" "-p" "$(dirname "${RAMDISK_MOUNT_POINT}")" || exit 1
    if [ ! -d "${RAMDISK_MOUNT_POINT}" ]; then
        log_info "Ramdisk mount point directory ${RAMDISK_MOUNT_POINT} does not exist. Creating..."
        execute_cmd "Create ramdisk mount point directory" "mkdir" "-p" "${RAMDISK_MOUNT_POINT}" || exit 1
    fi

    if mountpoint -q "${RAMDISK_MOUNT_POINT}"; then
        if findmnt -n -o FSTYPE -T "${RAMDISK_MOUNT_POINT}" | grep -q "^tmpfs$"; then
            # 已经是 tmpfs，检查是否包含脚本惯用的目录，用于判定是否为本脚本先前挂载
            if [ -d "${IMAGE_STAGING_PARENT_DIR_ON_RAMDISK}" ] && [ -d "${FFMPEG_TEMP_OUTPUT_PARENT_DIR_ON_RAMDISK}" ]; then
                PREVIOUS_SCRIPT_RAMDISK_DETECTED=true
                log_info "Ramdisk ${RAMDISK_MOUNT_POINT} 已挂载且检测到脚本期望的目录存在，视为之前由本脚本挂载。跳过挂载步骤。"
            else
                log_warn "Ramdisk ${RAMDISK_MOUNT_POINT} 已挂载为 tmpfs，但未检测到脚本期望的目录。将按需创建目录后继续。"
            fi
            SCRIPT_MOUNTED_RAMDISK=false 
        else
            log_error "Critical: ${RAMDISK_MOUNT_POINT} is mounted but NOT as tmpfs. Exiting."
            exit 1
        fi
    else
        # Compute dynamic size based on MemAvailable and a reserve margin; clamp between min and max
        local mem_available_kb
        mem_available_kb=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
        local mem_available_mb=$(( mem_available_kb / 1024 ))
        local desired_mb
        if [[ ${mem_available_mb} -gt ${RAMDISK_RESERVE_MB} ]]; then
            desired_mb=$(( mem_available_mb - RAMDISK_RESERVE_MB ))
        else
            desired_mb=${RAMDISK_MIN_SIZE_MB}
        fi
        if [[ ${desired_mb} -lt ${RAMDISK_MIN_SIZE_MB} ]]; then
            desired_mb=${RAMDISK_MIN_SIZE_MB}
        fi
        if [[ ${desired_mb} -gt ${RAMDISK_MAX_SIZE_MB} ]]; then
            desired_mb=${RAMDISK_MAX_SIZE_MB}
        fi
        local size_opt="${desired_mb}m"
        log_info "Attempting to mount tmpfs ramdisk at ${RAMDISK_MOUNT_POINT} with dynamic size ${size_opt} (Avail: ${mem_available_mb}MB, Reserve: ${RAMDISK_RESERVE_MB}MB, Clamp: ${RAMDISK_MIN_SIZE_MB}-${RAMDISK_MAX_SIZE_MB}MB) ..."
        if ! execute_cmd "Mount tmpfs ramdisk" "mount" "-t" "tmpfs" "-o" "size=${size_opt},noatime" "tmpfs" "${RAMDISK_MOUNT_POINT}"; then
            exit 1 
        fi
        SCRIPT_MOUNTED_RAMDISK=true 
        log_info "Ramdisk mounted successfully by the script."
    fi
}

determine_target_config() { 
    log_info "Determining final video storage path and catch-up strategy..."
    execute_cmd "Ensure primary video target base exists" "mkdir" "-p" "${PRIMARY_FINAL_VIDEO_TARGET_BASE_DIR}" || exit 1
    execute_cmd "Ensure fallback video target base exists" "mkdir" "-p" "${FALLBACK_FINAL_VIDEO_TARGET_BASE_DIR}" || exit 1

    # ... (Rest of determine_target_config logic is IDENTICAL to v1.4.2)
    if mountpoint -q "${PRIMARY_FINAL_VIDEO_TARGET_BASE_DIR}"; then
        log_info "Primary video target ${PRIMARY_FINAL_VIDEO_TARGET_BASE_DIR} is a mount point. Using it."
        EFFECTIVE_FINAL_VIDEO_TARGET_BASE_DIR="${PRIMARY_FINAL_VIDEO_TARGET_BASE_DIR}"
        DO_CATCH_UP_PROCESSING=true
        log_info "Catch-up processing will be ENABLED."
    else
        log_warn "${PRIMARY_FINAL_VIDEO_TARGET_BASE_DIR} is NOT a mount point."
        log_warn "Switching to fallback video target: ${FALLBACK_FINAL_VIDEO_TARGET_BASE_DIR}"
        EFFECTIVE_FINAL_VIDEO_TARGET_BASE_DIR="${FALLBACK_FINAL_VIDEO_TARGET_BASE_DIR}"
        DO_CATCH_UP_PROCESSING=false
        log_warn "Catch-up processing will be DISABLED due to using fallback path."
    fi
    log_info "Effective final video base directory set to: ${EFFECTIVE_FINAL_VIDEO_TARGET_BASE_DIR}"
}

select_date_to_process() { # ssh is read-only, not wrapped by execute_cmd
    # ... (select_date_to_process function content IDENTICAL to v1.4.2, using case-insensitive boolean checks)
    local selected_date=""
    local today_iso
    today_iso=$(date "+%Y-%m-%d")

    if [[ "${DO_CATCH_UP_PROCESSING,,}" == "true" ]]; then
        log_info "Catch-up processing is ENABLED. Max lookback: ${MAX_CATCH_UP_DAYS} days (excluding today)."
        for i in $(seq "${MAX_CATCH_UP_DAYS}" -1 1); do 
            local check_date; check_date=$(date -d "${today_iso} -${i} days" "+%Y-%m-%d")
            local check_ym; check_ym=$(date -d "${check_date}" "+%Y-%m")
            local expected_video_file="${EFFECTIVE_FINAL_VIDEO_TARGET_BASE_DIR}/${check_ym}/${check_date}.mp4"
            local min_valid_size_bytes=$((MIN_VALID_VIDEO_SIZE_KB * 1024))
            local video_exists_and_valid=false
            if [ -f "${expected_video_file}" ]; then
                if [[ "${DRY_RUN,,}" == "true" ]]; then 
                    log_info "[DRY-RUN] Catch-up: Video for ${check_date} (Path: ${expected_video_file}) exists. Assuming valid for dry run."
                    video_exists_and_valid=true
                elif [ -s "${expected_video_file}" ] && [ "$(stat -c%s "${expected_video_file}")" -gt "${min_valid_size_bytes}" ]; then
                    video_exists_and_valid=true
                fi
            fi

            if [ "${video_exists_and_valid}" = true ]; then
                log_info "Catch-up: Video for ${check_date} (Path: ${expected_video_file}) already exists and is valid. Skipping."
                continue 
            fi
            
            if [ -f "${expected_video_file}" ]; then 
                 log_warn "Catch-up: Video for ${check_date} (Path: ${expected_video_file}) exists but is too small or invalid. Will attempt re-process."
            else 
                 log_info "Catch-up: Video for ${check_date} (Path: ${expected_video_file}) does NOT exist. Checking Armbian source."
            fi
            
            local armbian_source_check_path="${ARMBIAN_IMAGE_BASE_DIR}/${check_ym}/$(date -d "${check_date}" "+%d")/"
            local ssh_check_successful=false
            if [[ "${DRY_RUN,,}" == "true" ]]; then
                log_info "[DRY-RUN] Would check Armbian source: ssh ... test -d '${armbian_source_check_path}' ..."
                if [ "${check_date}" = "$(date -d "yesterday" "+%Y-%m-%d")" ]; then
                    log_warn "[DRY-RUN] Simulated: Source images found on Armbian for ${check_date}."
                    ssh_check_successful=true
                else
                    log_info "[DRY-RUN] Simulated: No source images for ${check_date} on Armbian (unless it's yesterday)."
                fi
            else 
                if ssh -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no \
                    "${ARMBIAN_USER}@${ARMBIAN_IP}" \
                    "test -d '${armbian_source_check_path}' && find '${armbian_source_check_path}' -maxdepth 1 -type f -iname '*.jpg' -print -quit | grep -q ." ; then
                    ssh_check_successful=true
                fi
            fi

            if [ "${ssh_check_successful}" = true ]; then
                 log_info "Catch-up: Source images found on Armbian for ${check_date}. This is the oldest missing/invalid date to process."
                 selected_date="${check_date}"
                 break
            else 
                 if [[ "${DRY_RUN,,}" == "false" ]]; then 
                    log_info "Catch-up: No source images found on Armbian for ${check_date} at ${armbian_source_check_path}. Skipping."
                 fi 
            fi
        done 

        if [ -z "${selected_date}" ]; then 
            if [[ "${DRY_RUN,,}" == "false" ]]; then
                log_info "Catch-up: No missing or invalid videos found within the last ${MAX_CATCH_UP_DAYS} days that have source images on Armbian."
            elif [[ "${DRY_RUN,,}" == "true" ]] && [ -z "${selected_date}" ]; then 
                 log_info "[DRY-RUN] Catch-up: No date was simulated for processing."
            fi
        fi
    else 
        log_info "Catch-up processing is DISABLED (likely due to fallback storage path)."
        local yesterday_iso; yesterday_iso=$(date -d "yesterday" "+%Y-%m-%d")
        local yesterday_ym; yesterday_ym=$(date -d "${yesterday_iso}" "+%Y-%m")
        local yesterday_d; yesterday_d=$(date -d "${yesterday_iso}" "+%d")
        local expected_video_file="${EFFECTIVE_FINAL_VIDEO_TARGET_BASE_DIR}/${yesterday_ym}/${yesterday_iso}.mp4"
        local min_valid_size_bytes=$((MIN_VALID_VIDEO_SIZE_KB * 1024))
        local video_exists_and_valid_yesterday=false

        if [ -f "${expected_video_file}" ]; then
            if [[ "${DRY_RUN,,}" == "true" ]]; then 
                video_exists_and_valid_yesterday=true
            elif [ -s "${expected_video_file}" ] && [ "$(stat -c%s "${expected_video_file}")" -gt "${min_valid_size_bytes}" ]; then
                video_exists_and_valid_yesterday=true
            fi
        fi
        
        if [ "${video_exists_and_valid_yesterday}" = true ]; then
             log_info "Video for yesterday (${yesterday_iso}) (Path: ${expected_video_file}) already exists and seems valid."
        else 
            if [ -f "${expected_video_file}" ]; then 
                log_warn "Video for yesterday (${yesterday_iso}) (Path: ${expected_video_file}) exists but is too small or invalid. Will attempt to re-process."
            else 
                log_info "Video for yesterday (${yesterday_iso}) (Path: ${expected_video_file}) does NOT exist. Checking Armbian source."
            fi
            local armbian_source_check_path="${ARMBIAN_IMAGE_BASE_DIR}/${yesterday_ym}/${yesterday_d}/"
            local ssh_check_successful=false
            if [[ "${DRY_RUN,,}" == "true" ]]; then
                log_warn "[DRY-RUN] Simulated: Source images found on Armbian for yesterday (${yesterday_iso}). Selecting this date."
                ssh_check_successful=true 
            else
                 if ssh -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no \
                    "${ARMBIAN_USER}@${ARMBIAN_IP}" \
                    "test -d '${armbian_source_check_path}' && find '${armbian_source_check_path}' -maxdepth 1 -type f -iname '*.jpg' -print -quit | grep -q ." ; then
                    ssh_check_successful=true
                fi
            fi

            if [ "${ssh_check_successful}" = true ]; then
                log_info "Source images found on Armbian for yesterday (${yesterday_iso}). Selecting this date for processing."
                selected_date="${yesterday_iso}"
            else 
                 if [[ "${DRY_RUN,,}" == "false" ]]; then
                    log_info "No source images found on Armbian for yesterday (${yesterday_iso}) at ${armbian_source_check_path}."
                 fi
            fi
        fi
    fi
    
    if [ -n "${selected_date}" ]; then
        echo "${selected_date}" 
    else
        return 1 
    fi
}

process_single_date() { # Uses execute_cmd
    # ... (process_single_date function content IDENTICAL to v1.4.2, using case-insensitive boolean checks)
    local date_to_process="$1"
    CURRENT_PROCESSING_DATE_FOR_TRAP="${date_to_process}" 

    local process_ym process_d
    process_ym=$(date -d "${date_to_process}" "+%Y-%m")
    process_d=$(date -d "${date_to_process}" "+%d")

    log_info "--- Starting processing for date: ${date_to_process} ---"

    CURRENT_IMAGE_STAGING_DIR_FOR_TRAP="${IMAGE_STAGING_PARENT_DIR_ON_RAMDISK}/${date_to_process}" 
    FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP="${FFMPEG_TEMP_OUTPUT_PARENT_DIR_ON_RAMDISK}/${date_to_process}.mp4"
    
    local source_dir_on_armbian="${ARMBIAN_IMAGE_BASE_DIR}/${process_ym}/${process_d}/" 
    local final_video_output_subdir="${EFFECTIVE_FINAL_VIDEO_TARGET_BASE_DIR}/${process_ym}" 
    local final_video_file_path="${final_video_output_subdir}/${date_to_process}.mp4"

    log_info "Target Armbian source: ${ARMBIAN_USER}@${ARMBIAN_IP}:${source_dir_on_armbian}"
    log_info "Target Ramdisk image staging: ${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}/" 
    log_info "Target Ramdisk ffmpeg temporary video: ${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}"
    log_info "Target Final video storage: ${final_video_file_path}"

    STATS_NUM_DATES_ATTEMPTED=$((STATS_NUM_DATES_ATTEMPTED + 1))

    if ! execute_cmd "Create image staging dir" "mkdir" "-p" "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}"; then
        STATS_NUM_DATES_FAILED=$((STATS_NUM_DATES_FAILED + 1))
        return 1
    fi
    if ! execute_cmd "Create ffmpeg temp parent dir" "mkdir" "-p" "${FFMPEG_TEMP_OUTPUT_PARENT_DIR_ON_RAMDISK}"; then
        STATS_NUM_DATES_FAILED=$((STATS_NUM_DATES_FAILED + 1))
        return 1
    fi
    if ! execute_cmd "Create final video output subdir" "mkdir" "-p" "${final_video_output_subdir}"; then
        STATS_NUM_DATES_FAILED=$((STATS_NUM_DATES_FAILED + 1))
        return 1
    fi
    if [[ "${DRY_RUN,,}" != "true" ]]; then
        execute_cmd "Change ownership of final video subdir to zfile" "chown" "zfile:zfile" "${final_video_output_subdir}"
    else
        log_info "[DRY RUN] Would change ownership of ${final_video_output_subdir} to zfile:zfile"
    fi

    log_info "Starting rsync of images for ${date_to_process} from Armbian..."
    if ! run_with_retry RSYNC "Rsync images" "${RSYNC_MAX_ATTEMPTS}" "${RSYNC_RETRY_DELAY_SEC}" "${RSYNC_TIMEOUT_SEC}" "24" -- \
        rsync -rtz --delete --timeout=600 \
        "${ARMBIAN_USER}@${ARMBIAN_IP}:${source_dir_on_armbian}" \
        "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}/"; then
        STATS_NUM_DATES_FAILED=$((STATS_NUM_DATES_FAILED + 1))
        return 1
    fi
    log_info "Rsync for ${date_to_process} completed successfully."

    local num_files
    if [[ "${DRY_RUN,,}" == "true" ]]; then 
        num_files=100 
        log_info "[DRY-RUN] Simulating ${num_files} JPG images found."
    else
        num_files=$(find "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}" -maxdepth 1 -type f -iname "*.jpg" | wc -l)
        log_info "Found ${num_files} JPG images in ${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP} for ${date_to_process}."
    fi
    STATS_LAST_NUM_PHOTOS=${num_files}
    STATS_TOTAL_PHOTOS_SYNCED=$((STATS_TOTAL_PHOTOS_SYNCED + num_files))
    
    if [ "${num_files}" -eq 0 ]; then
        log_info "No images for ${date_to_process} after rsync. Skipping encoding for this date."
        if [ -d "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}" ]; then 
             execute_cmd "Delete empty/non-jpg staging dir for ${date_to_process}" "rm" "-rf" "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}"
        fi
        CURRENT_IMAGE_STAGING_DIR_FOR_TRAP="" 
        CURRENT_PROCESSING_DATE_FOR_TRAP="N/A" 
        STATS_NUM_DATES_SUCCEEDED=$((STATS_NUM_DATES_SUCCEEDED + 1))
        return 0 
    fi

    log_info "Starting FFmpeg encoding for ${date_to_process} to ${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}"
    # Decide whether to encode to tmpfs or directly to final location based on free space estimation
    local ffmpeg_output_target="${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}"
    local tmp_avail_kb
    tmp_avail_kb=$(df -k --output=avail "${FFMPEG_TEMP_OUTPUT_PARENT_DIR_ON_RAMDISK}" | tail -n 1)
    local estimated_output_kb
    if [[ "${DRY_RUN,,}" == "true" ]]; then
        estimated_output_kb=$(( 300 * 1024 )) # ~300MB
    else
        # A) bitrate-based estimate
        local bps
        bps=$(parse_bitrate_to_bps "${VIDEO_BITRATE}")
        if [[ -z "${bps}" || "${bps}" -le 0 ]]; then bps=1000000; fi
        local est_seconds=$(( (num_files + ${OUTPUT_FPS} - 1) / ${OUTPUT_FPS} ))
        local est_bytes_rate=$(( (bps / 8) * est_seconds ))
        # Apply headroom
        est_bytes_rate=$(( (est_bytes_rate * OUTPUT_ESTIMATE_HEADROOM_PERMILLE) / 1000 ))

        # B) input-size-based estimate (sum of JPG sizes * ratio)
        local input_total_bytes=0
        input_total_bytes=$(find "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}" -maxdepth 1 -type f -iname "*.jpg" -printf "%s\n" 2>/dev/null | awk '{s+=$1} END {print s+0}')
        local est_bytes_input=$(( (input_total_bytes * OUTPUT_ESTIMATE_INPUT_RATIO_PERMILLE) / 1000 ))
        # Apply headroom
        est_bytes_input=$(( (est_bytes_input * OUTPUT_ESTIMATE_HEADROOM_PERMILLE) / 1000 ))

        # Choose the larger estimate
        local est_bytes_final=${est_bytes_rate}
        if [[ ${est_bytes_input} -gt ${est_bytes_rate} ]]; then
            est_bytes_final=${est_bytes_input}
        fi
        estimated_output_kb=$(( est_bytes_final / 1024 ))
    fi
    if [[ -n "${tmp_avail_kb}" && "${tmp_avail_kb}" -gt 0 && "${tmp_avail_kb}" -lt "${estimated_output_kb}" ]]; then
        log_warn "Estimated output (~$((estimated_output_kb/1024))MB) exceeds tmpfs free ($((tmp_avail_kb/1024))MB). Will encode directly to final path."
        ffmpeg_output_target="${final_video_file_path}"
    fi

    # If encoding directly to final path, perform pre-flight free space check on final storage
    if [[ "${ffmpeg_output_target}" == "${final_video_file_path}" ]]; then
        if ! execute_cmd "Ensure final video subdir exists" "mkdir" "-p" "${final_video_output_subdir}"; then
            STATS_NUM_DATES_FAILED=$((STATS_NUM_DATES_FAILED + 1))
            return 1
        fi
        local final_avail_kb
        if [[ "${DRY_RUN,,}" == "true" ]]; then
            final_avail_kb=$(( estimated_output_kb * 2 ))
        else
            final_avail_kb=$(df -k --output=avail "${final_video_output_subdir}" | tail -n 1)
        fi
        local required_final_kb=$(( estimated_output_kb + (10 * 1024) ))
        if [[ "${final_avail_kb}" -lt "${required_final_kb}" ]]; then
            log_error "Insufficient disk space in ${final_video_output_subdir} for direct-encoded video. Available: ${final_avail_kb}KB, Estimated required: ~${required_final_kb}KB."
            STATS_NUM_DATES_FAILED=$((STATS_NUM_DATES_FAILED + 1))
            return 1
        fi
    fi

    # 动态估算：按最低 10 fps 处理速率（支持 120 fps 快速转码，但保守按 10 fps 估算）
    # 示例：1.2w 张 → ceil(12000 / 10) = 1200 秒
    local ffmpeg_timeout_this_run
    local min_processing_fps=10
    local suggested_timeout=$(( (num_files + min_processing_fps - 1) / min_processing_fps ))
    # 夹在 300~2400 秒区间
    if [[ ${suggested_timeout} -lt 300 ]]; then suggested_timeout=300; fi
    if [[ ${suggested_timeout} -gt 2400 ]]; then suggested_timeout=2400; fi
    ffmpeg_timeout_this_run=${suggested_timeout}
    log_info "Dynamic timeout: frames=${num_files}, min_fps=${min_processing_fps} => ${ffmpeg_timeout_this_run}s (clamped 300-2400)"

    if ! run_with_retry FFMPEG "FFmpeg encoding" "${FFMPEG_MAX_ATTEMPTS}" "${FFMPEG_RETRY_DELAY_SEC}" "${ffmpeg_timeout_this_run}" "" -- \
        "${FFMPEG_EXE_PATH}" -hide_banner -loglevel info \
        -hwaccel rkmpp -hwaccel_output_format drm_prime -afbc rga \
        -framerate "${OUTPUT_FPS}" \
        -pattern_type glob -i "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}/*.jpg" \
        -vf "scale_rkrga=w=1920:h=1080:format=nv12:afbc=1" \
        -c:v "${VIDEO_CODEC}" \
        -rc_mode CQP -qp_init "${VIDEO_QUALITY}" \
        -profile:v main -g:v 60 \
        -an \
        -y "${ffmpeg_output_target}"; then
        log_error "FFmpeg encoding for ${date_to_process} failed."
        STATS_NUM_DATES_FAILED=$((STATS_NUM_DATES_FAILED + 1))
        return 1
    fi
    log_info "FFmpeg encoding for ${date_to_process} successful: ${ffmpeg_output_target}"

    local min_video_size_bytes=$((${MIN_VALID_VIDEO_SIZE_KB} * 1024))
    if [[ "${DRY_RUN,,}" == "false" ]] && 
       ([ ! -f "${ffmpeg_output_target}" ] || \
        [ ! -s "${ffmpeg_output_target}" ] || \
        [ "$(stat -c%s "${ffmpeg_output_target}")" -lt "${min_video_size_bytes}" ]); then
        log_error "FFmpeg for ${date_to_process} produced an invalid or too small video file: ${ffmpeg_output_target} (Size: $(stat -c%s "${ffmpeg_output_target}" 2>/dev/null || echo 0) bytes)."
        STATS_NUM_DATES_FAILED=$((STATS_NUM_DATES_FAILED + 1))
        return 1
    fi
    log_info "Encoded video for ${date_to_process} verified."

    # For PushPlus summary
    LAST_DATE_PROCESSED="${date_to_process}"
    LAST_FINAL_VIDEO_PATH="${final_video_file_path}"
    if [[ "${ffmpeg_output_target}" == "${final_video_file_path}" ]]; then
        LAST_ENCODE_DIRECT="true"
    else
        LAST_ENCODE_DIRECT="false"
    fi

    # Probe duration (best-effort)
    if [[ "${DRY_RUN,,}" == "true" ]]; then
        STATS_LAST_VIDEO_SECONDS=$(( (STATS_LAST_NUM_PHOTOS + ${OUTPUT_FPS} - 1) / ${OUTPUT_FPS} ))
    else
        STATS_LAST_VIDEO_SECONDS=$(probe_video_duration_seconds "${ffmpeg_output_target}")
    fi
    STATS_TOTAL_OUTPUT_VIDEO_SECONDS=$((STATS_TOTAL_OUTPUT_VIDEO_SECONDS + STATS_LAST_VIDEO_SECONDS))

    # If encoded to tmpfs, ensure the final storage has enough space for copying
    if [[ "${ffmpeg_output_target}" != "${final_video_file_path}" ]]; then
        local required_space_kb temp_video_size_bytes available_space_kb
        if [[ "${DRY_RUN,,}" == "true" ]]; then
            temp_video_size_bytes=$((100 * 1024 * 1024)) 
        else
            temp_video_size_bytes=$(stat -c%s "${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}")
        fi
        required_space_kb=$(( (temp_video_size_bytes / 1024) + (10 * 1024) )) 
        
        execute_cmd "Ensure final video subdir exists for df check" "mkdir" "-p" "${final_video_output_subdir}" || return 1 
        
        if [[ "${DRY_RUN,,}" == "true" ]]; then
            available_space_kb=$(( required_space_kb * 2 )) 
        else
            available_space_kb=$(df -k --output=avail "${final_video_output_subdir}" | tail -n 1)
        fi    

        if [ "${available_space_kb}" -lt "${required_space_kb}" ]; then
            log_error "Insufficient disk space in ${final_video_output_subdir} for ${date_to_process} video copy. Available: ${available_space_kb}KB, Required: ~${required_space_kb}KB."
            STATS_NUM_DATES_FAILED=$((STATS_NUM_DATES_FAILED + 1))
            return 1
        fi
        log_info "Disk space check passed for copy into ${final_video_output_subdir}."
    fi

    if [[ "${ffmpeg_output_target}" != "${final_video_file_path}" ]]; then
        log_info "Copying video for ${date_to_process} to final location: ${final_video_file_path}"
        if ! execute_cmd "Copy video to final storage" "cp" "${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}" "${final_video_file_path}"; then
            STATS_NUM_DATES_FAILED=$((STATS_NUM_DATES_FAILED + 1))
            return 1
        fi
    else
        log_info "Video already encoded directly to final location; skip copy."
    fi

    if [[ "${DRY_RUN,,}" != "true" ]]; then # 通常，实际的文件系统更改不应在 dry run 模式下执行
	execute_cmd "Change ownership of final video to zfile" "chown" "zfile:zfile" "${final_video_file_path}" || {
            log_error "Failed to change ownership to zfile for ${final_video_file_path}. Please check user/group existence and script permissions."
            # 根据你的需求，你可能希望在这里也 return 1，如果chown失败是关键错误
            # return 1
        }
    else
        log_info "[DRY RUN] Would change ownership of ${final_video_file_path} to zfile:zfile"
    fi

    if [[ "${DRY_RUN,,}" == "true" ]]; then
        STATS_LAST_VIDEO_SIZE_BYTES=0
    else
        STATS_LAST_VIDEO_SIZE_BYTES=$(stat -c%s "${final_video_file_path}" 2>/dev/null || echo 0)
    fi
    STATS_TOTAL_OUTPUT_VIDEO_SIZE_BYTES=$((STATS_TOTAL_OUTPUT_VIDEO_SIZE_BYTES + STATS_LAST_VIDEO_SIZE_BYTES))
    log_info "Video for ${date_to_process} successfully copied (Size: $( [[ "${DRY_RUN,,}" == "false" ]] && du -h "${final_video_file_path}" | cut -f1 || echo "N/A in dry run" ))."

    log_info "Cleaning up ramdisk files for successfully processed date ${date_to_process}..."
    if [[ "${ffmpeg_output_target}" != "${final_video_file_path}" ]]; then
        execute_cmd "Delete temp video for ${date_to_process}" "rm" "-f" "${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}"
        FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP="" 
    fi

    execute_cmd "Delete staged images for ${date_to_process}" "rm" "-rf" "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}"
    CURRENT_IMAGE_STAGING_DIR_FOR_TRAP="" 
    
    STATS_NUM_DATES_SUCCEEDED=$((STATS_NUM_DATES_SUCCEEDED + 1))
    log_info "--- Finished processing for date: ${date_to_process} ---"
    CURRENT_PROCESSING_DATE_FOR_TRAP="N/A" 
    return 0 
}


display_version() { # IDENTICAL to v1.4.2
    echo "${SCRIPT_NAME} version ${SCRIPT_VERSION}"
    exit 0
}

display_help() { # Updated Exit codes slightly for v1.4.2
    cat <<EOF
Usage: ${SCRIPT_NAME} [OPTIONS]

Description:
  Daily automated script to sync photos from a remote server, encode them into
  an H.265 video using FFmpeg with hardware acceleration, and store the video.
  Includes features like catch-up for missed days, fallback storage paths,
  dry-run mode, and robust logging.

Options:
  --help        Show this help message and exit.
  --version     Show script version and exit.
  --dry-run     Simulate execution: Log actions that would be performed without
                actually modifying files or syncing/encoding data. Useful for
                testing configuration and date selection logic.
                (Can also be enabled by setting environment variable
                 SCRIPT_DRY_RUN_ENV_OVERRIDE=true)

Exit Codes:
  0   Success (or no action needed, e.g., video already exists for all relevant dates)
  1   General runtime error or operation failed (e.g., rsync, ffmpeg, cp error,
      dependency check failure, lock acquisition failure, ramdisk mount failure)
  2   UUID generation failed (critical dependency uuidgen missing or broken)
  All other non-zero codes usually indicate failure of a specific internal command
  propagated by 'set -e' or explicit exit by the script logic.

Key Configuration Variables (set near the top of the script):
  ARMBIAN_IP, ARMBIAN_USER, ARMBIAN_IMAGE_BASE_DIR
  RAMDISK_MOUNT_POINT, RAMDISK_SIZE
  PRIMARY_FINAL_VIDEO_TARGET_BASE_DIR, FALLBACK_FINAL_VIDEO_TARGET_BASE_DIR
  FFMPEG_EXE_PATH, VIDEO_BITRATE, MAX_CATCH_UP_DAYS, MIN_VALID_VIDEO_SIZE_KB
  LOG_FILE, DEFAULT_ENABLE_SYSLOG_LOGGING, DEFAULT_ENABLE_LOCKING
  DEFAULT_DRY_RUN_CONFIG
  DEFAULT_SCRIPT_DEBUG_TRACE (Environment: SCRIPT_DEBUG_TRACE_ENV_OVERRIDE=true for set -x)

Logs are written to: ${LOG_FILE}
When run via cron, ensure the user running the script (e.g., root) has
permissions for all paths, SSH key access, and necessary commands.

Environment overrides:
  SCRIPT_DRY_RUN_ENV_OVERRIDE=true|false
  SCRIPT_ENABLE_LOCKING_ENV_OVERRIDE=true|false
  SCRIPT_SYSLOG_LOG_ENV_OVERRIDE=true|false
  SCRIPT_DEBUG_TRACE_ENV_OVERRIDE=true|false
  ENABLE_HARD_TIMEOUTS_ENV_OVERRIDE=true|false
  ENABLE_PUSHPLUS_ENV_OVERRIDE=true|false
  PUSHPLUS_TOKEN_ENV_OVERRIDE=your_token_here
  OUTPUT_ESTIMATE_INPUT_RATIO_PERMILLE_ENV_OVERRIDE=100   # 输入尺寸估算比例(千分比)
  OUTPUT_ESTIMATE_HEADROOM_PERMILLE_ENV_OVERRIDE=120      # 估算裕量(千分比)
EOF
    exit 0
}

# --- Main Script Execution Logic ---
# (main_control_flow function is IDENTICAL to v1.4.2, with case-insensitive boolean checks)
main_control_flow() {
    local arg_dry_run_set="false" 
    if [[ "$#" -gt 0 ]]; then 
        local arg
        for arg in "$@"; do
            case "$arg" in
                --help) display_help ;;       
                --version) display_version ;; 
                --dry-run) arg_dry_run_set="true" ;; 
                *)
                    if [[ "$arg" == -* ]]; then 
                        echo "Unknown option: $arg. Use --help for usage." >&2 
                        exit 1 
                    fi ;;
            esac
        done
    fi
    
    if [[ "${arg_dry_run_set}" == "true" ]]; then
        DRY_RUN="true" 
    else 
      DRY_RUN="${SCRIPT_DRY_RUN_ENV_OVERRIDE:-${DEFAULT_DRY_RUN_CONFIG}}"
    fi

    if [[ "${DRY_RUN,,}" == "true" && "${arg_dry_run_set}" == "true" ]]; then 
        log_warn "Dry-run mode ENABLED via command line argument."
    elif [[ "${DRY_RUN,,}" == "true" ]]; then 
        log_warn "Dry-run mode ENABLED via environment variable or script default."
    fi

    if [[ "${ENABLE_LOCKING,,}" == "true" ]]; then 
        execute_cmd "Ensure lock directory exists" "mkdir" "-p" "${LOCK_FILE_DIR}" || exit 1
        local lock_file_path="${LOCK_FILE_DIR}/${LOCK_FILE_NAME}"
        eval "exec ${LOCK_FD}>'${lock_file_path}'"
        if ! flock -n "${LOCK_FD}"; then
            log_error "Another instance of ${SCRIPT_NAME} is running (PID: $(cat "${lock_file_path}" 2>/dev/null || echo "unknown")). Exiting."
            eval "exec ${LOCK_FD}>&-" 
            exit 1
        fi
        log_info "Successfully acquired script lock: ${lock_file_path} on FD ${LOCK_FD}"
        # Using execute_cmd for this echo to a FD is tricky. Direct echo is fine.
        # If this fails, it's not critical enough to halt the script.
        (echo $$ >&"${LOCK_FD}") || log_warn "Could not write PID to lock file ${lock_file_path} via FD ${LOCK_FD}."
    fi

    rotate_log 
    START_EPOCH=$(date +%s)
    log_info "================== Daily Photo-to-Video Script (v${SCRIPT_VERSION}) Started =================="
    log_info "Effective RUN_ID: ${RUN_ID}"
    log_info "Running as user: $(whoami). Effective DRY_RUN: ${DRY_RUN}. Locking enabled: ${ENABLE_LOCKING}."
    if [[ "${SCRIPT_DEBUG_TRACE,,}" == "true" ]]; then 
         log_warn "Bash execution trace (set -x) is active."
    fi
    
    check_dependencies
    determine_target_config 

    # 循环补齐历史未处理的日期，直至没有可处理的日期或达到安全上限
    local processed_dates_count=0
    local loop_guard_max="${MAX_CATCH_UP_DAYS}"
    if [[ -z "${loop_guard_max}" || "${loop_guard_max}" -le 0 ]]; then loop_guard_max=30; fi
    local ramdisk_prepared_for_run=false

    while :; do
        local date_to_process_selected
        if ! date_to_process_selected=$(select_date_to_process); then 
            if [[ ${processed_dates_count} -eq 0 ]]; then
                log_info "No date selected for processing based on current checks. Exiting."
                log_info "================== Daily Photo-to-Video Script (v${SCRIPT_VERSION}) Finished (No Action) =================="
            else
                log_info "No more dates to process in this run. Total processed: ${processed_dates_count}."
                log_info "================== Daily Photo-to-Video Script (v${SCRIPT_VERSION}) Finished Successfully =================="
            fi
            break
        fi

        # 仅在确定有可处理日期后，才准备（挂载）ramdisk；且每次运行只准备一次
        if [[ "${ramdisk_prepared_for_run}" != "true" ]]; then
            setup_ramdisk_if_needed
            ramdisk_prepared_for_run=true
        fi

        CURRENT_PROCESSING_DATE_FOR_TRAP="${date_to_process_selected}" 
        log_info "Date selected for processing in this run: ${date_to_process_selected}"

        if process_single_date "${date_to_process_selected}"; then
            processed_dates_count=$((processed_dates_count + 1))
            log_info "Successfully completed all operations for date: ${date_to_process_selected}. (Processed so far: ${processed_dates_count})"
        else
            log_error "Overall processing failed for date: ${date_to_process_selected}. See logs for specific errors."
            exit 1 
        fi

        if [[ ${processed_dates_count} -ge ${loop_guard_max} ]]; then
            log_warn "Reached loop guard limit (${loop_guard_max}). Stopping further catch-up in this run."
            log_info "================== Daily Photo-to-Video Script (v${SCRIPT_VERSION}) Finished Successfully =================="
            break
        fi
    done
}

# --- Script Entry Point ---
main_control_flow "$@" 

exit 0
