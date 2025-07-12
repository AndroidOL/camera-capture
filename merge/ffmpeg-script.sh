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
readonly SCRIPT_VERSION="1.4.3"
# ... (Rest of CONFIGURATION PARAMETERS are IDENTICAL to v1.4.2) ...
readonly SCRIPT_NAME="$(basename "$0")"

readonly ARMBIAN_USER="tianhao"
readonly ARMBIAN_IP="am40.tianhao.me"
readonly ARMBIAN_IMAGE_BASE_DIR="/opt/camera/captures"      # No trailing slash

readonly RAMDISK_MOUNT_POINT="/mnt/ramdisk"
readonly RAMDISK_SIZE="5G"
readonly IMAGE_STAGING_PARENT_DIR_ON_RAMDISK="${RAMDISK_MOUNT_POINT}/image_source" # No trailing slash
readonly FFMPEG_TEMP_OUTPUT_PARENT_DIR_ON_RAMDISK="${RAMDISK_MOUNT_POINT}/ffmpeg_tmp" # No trailing slash

readonly PRIMARY_FINAL_VIDEO_TARGET_BASE_DIR="/opt/camera/merge"    # No trailing slash
readonly FALLBACK_FINAL_VIDEO_TARGET_BASE_DIR="/opt/camera/merge-emmc" # No trailing slash
readonly FFMPEG_EXE_PATH="/usr/local/ffmpeg-rockchip/bin/ffmpeg"

readonly OUTPUT_FPS="6"
readonly VIDEO_CODEC="hevc_rkmpp"
readonly VIDEO_BITRATE="1M"

readonly LOG_FILE="/var/log/daily_photo_to_video.log"
readonly LOG_MAX_SIZE_KB=10240 
readonly DEFAULT_ENABLE_SYSLOG_LOGGING="true"
readonly SYSLOG_TAG="${SCRIPT_NAME}" 

readonly MAX_CATCH_UP_DAYS=7
readonly MIN_VALID_VIDEO_SIZE_KB=10 

readonly DEFAULT_DRY_RUN_CONFIG="false" 
readonly DEFAULT_ENABLE_LOCKING="true"  
readonly DEFAULT_SCRIPT_DEBUG_TRACE="false" 

readonly LOCK_FILE_DIR="/var/lock" 
readonly LOCK_FILE_NAME="${SCRIPT_NAME}.lock"
readonly LOCK_FD=200 
# --- End of Configuration Parameters ---


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


# --- Utility and Core Logic Functions ---
# (rotate_log, check_dependencies, setup_ramdisk_if_needed, determine_target_config, 
#  select_date_to_process, process_single_date now use the new execute_cmd signature)

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
    # ... (Identical to v1.4.2)
    local missing_deps=0
    local dep
    for dep in rsync "${FFMPEG_EXE_PATH}" date find mkdir rm stat tee du mv wc mountpoint cp umount mount ssh grep sort head dirname uuidgen flock logger; do
        if ! command -v "${dep}" &> /dev/null; then
            if [ "${dep}" == "uuidgen" ]; then 
                log_error "Critical dependency missing: ${dep}. Consider installing 'uuid-runtime' package or similar."
            else
                log_error "Critical dependency missing: ${dep}."
            fi
            missing_deps=1
        fi
    done
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
            log_warn "Ramdisk ${RAMDISK_MOUNT_POINT} is already mounted as tmpfs. Using existing mount."
            SCRIPT_MOUNTED_RAMDISK=false 
        else
            log_error "Critical: ${RAMDISK_MOUNT_POINT} is mounted but NOT as tmpfs. Exiting."
            exit 1
        fi
    else
        log_info "Attempting to mount tmpfs ramdisk at ${RAMDISK_MOUNT_POINT} with size ${RAMDISK_SIZE}..."
        if ! execute_cmd "Mount tmpfs ramdisk" "mount" "-t" "tmpfs" "-o" "size=${RAMDISK_SIZE},noatime" "tmpfs" "${RAMDISK_MOUNT_POINT}"; then
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

    execute_cmd "Create image staging dir" "mkdir" "-p" "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}" || return 1
    execute_cmd "Create ffmpeg temp parent dir" "mkdir" "-p" "${FFMPEG_TEMP_OUTPUT_PARENT_DIR_ON_RAMDISK}" || return 1
    execute_cmd "Create final video output subdir" "mkdir" "-p" "${final_video_output_subdir}" || return 1
    if [[ "${DRY_RUN,,}" != "true" ]]; then
        execute_cmd "Change ownership of final video subdir to zfile" "chown" "zfile:zfile" "${final_video_output_subdir}"
    else
        log_info "[DRY RUN] Would change ownership of ${final_video_output_subdir} to zfile:zfile"
    fi

    log_info "Starting rsync of images for ${date_to_process} from Armbian..."
    local rsync_exit_code
    execute_cmd "Rsync images" "rsync" "-rtz" "--delete" "--timeout=600" \
        "${ARMBIAN_USER}@${ARMBIAN_IP}:${source_dir_on_armbian}" \
        "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}/" 
    rsync_exit_code=$? 

    if [ ${rsync_exit_code} -eq 0 ]; then
        log_info "Rsync for ${date_to_process} completed successfully."
    elif [ ${rsync_exit_code} -eq 24 ]; then
        log_warn "Rsync for ${date_to_process} completed with warning code 24."
    elif [[ "${rsync_exit_code}" -eq 20 || "${rsync_exit_code}" -eq 130 || "${rsync_exit_code}" -eq 143 ]]; then 
        log_error "Rsync for ${date_to_process} was interrupted (signal related, code ${rsync_exit_code})."
        return 1
    else
        log_error "Rsync for ${date_to_process} failed with critical code ${rsync_exit_code}."
        return 1
    fi

    local num_files
    if [[ "${DRY_RUN,,}" == "true" ]]; then 
        num_files=100 
        log_info "[DRY-RUN] Simulating ${num_files} JPG images found."
    else
        num_files=$(find "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}" -maxdepth 1 -type f -iname "*.jpg" | wc -l)
        log_info "Found ${num_files} JPG images in ${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP} for ${date_to_process}."
    fi
    
    if [ "${num_files}" -eq 0 ]; then
        log_info "No images for ${date_to_process} after rsync. Skipping encoding for this date."
        if [ -d "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}" ]; then 
             execute_cmd "Delete empty/non-jpg staging dir for ${date_to_process}" "rm" "-rf" "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}"
        fi
        CURRENT_IMAGE_STAGING_DIR_FOR_TRAP="" 
        CURRENT_PROCESSING_DATE_FOR_TRAP="N/A" 
        return 0 
    fi

    log_info "Starting FFmpeg encoding for ${date_to_process} to ${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}"
    local ffmpeg_exit_code
    execute_cmd "FFmpeg encoding" "${FFMPEG_EXE_PATH}" "-hide_banner" "-loglevel" "info" \
        "-framerate" "${OUTPUT_FPS}" \
        "-pattern_type" "glob" "-i" "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}/*.jpg" \
        "-vf" "format=nv12" \
        "-c:v" "${VIDEO_CODEC}" \
        "-b:v" "${VIDEO_BITRATE}" \
        "-an" \
        "-y" "${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}" 
    ffmpeg_exit_code=$?
        
    if [ ${ffmpeg_exit_code} -ne 0 ]; then
        log_error "FFmpeg encoding for ${date_to_process} failed (Exit code: ${ffmpeg_exit_code})."
        return 1 
    fi
    log_info "FFmpeg encoding for ${date_to_process} successful: ${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}"

    local min_video_size_bytes=$((${MIN_VALID_VIDEO_SIZE_KB} * 1024))
    if [[ "${DRY_RUN,,}" == "false" ]] && 
       ([ ! -f "${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}" ] || \
        [ ! -s "${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}" ] || \
        [ "$(stat -c%s "${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}")" -lt "${min_video_size_bytes}" ]); then
        log_error "FFmpeg for ${date_to_process} produced an invalid or too small video file: ${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP} (Size: $(stat -c%s "${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}" 2>/dev/null || echo 0) bytes)."
        return 1
    fi
    log_info "Temporary video file for ${date_to_process} verified."

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
        log_error "Insufficient disk space in ${final_video_output_subdir} for ${date_to_process} video. Available: ${available_space_kb}KB, Required: ~${required_space_kb}KB."
        return 1
    fi
    log_info "Disk space check passed for ${final_video_output_subdir}."

    log_info "Copying video for ${date_to_process} to final location: ${final_video_file_path}"
    execute_cmd "Copy video to final storage" "cp" "${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}" "${final_video_file_path}" || return 1

    if [[ "${DRY_RUN,,}" != "true" ]]; then # 通常，实际的文件系统更改不应在 dry run 模式下执行
	execute_cmd "Change ownership of final video to zfile" "chown" "zfile:zfile" "${final_video_file_path}" || {
            log_error "Failed to change ownership to zfile for ${final_video_file_path}. Please check user/group existence and script permissions."
            # 根据你的需求，你可能希望在这里也 return 1，如果chown失败是关键错误
            # return 1
        }
    else
        log_info "[DRY RUN] Would change ownership of ${final_video_file_path} to zfile:zfile"
    fi

    log_info "Video for ${date_to_process} successfully copied (Size: $( [[ "${DRY_RUN,,}" == "false" ]] && du -h "${final_video_file_path}" | cut -f1 || echo "N/A in dry run" ))."

    log_info "Cleaning up ramdisk files for successfully processed date ${date_to_process}..."
    execute_cmd "Delete temp video for ${date_to_process}" "rm" "-f" "${FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP}"
    FFMPEG_TEMP_VIDEO_FILE_FOR_TRAP="" 

    execute_cmd "Delete staged images for ${date_to_process}" "rm" "-rf" "${CURRENT_IMAGE_STAGING_DIR_FOR_TRAP}"
    CURRENT_IMAGE_STAGING_DIR_FOR_TRAP="" 
    
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
    log_info "================== Daily Photo-to-Video Script (v${SCRIPT_VERSION}) Started =================="
    log_info "Effective RUN_ID: ${RUN_ID}"
    log_info "Running as user: $(whoami). Effective DRY_RUN: ${DRY_RUN}. Locking enabled: ${ENABLE_LOCKING}."
    if [[ "${SCRIPT_DEBUG_TRACE,,}" == "true" ]]; then 
         log_warn "Bash execution trace (set -x) is active."
    fi
    
    check_dependencies
    setup_ramdisk_if_needed 
    determine_target_config 

    local date_to_process_selected
    if ! date_to_process_selected=$(select_date_to_process); then 
        log_info "No date selected for processing based on current checks. Exiting."
        log_info "================== Daily Photo-to-Video Script (v${SCRIPT_VERSION}) Finished (No Action) =================="
        exit 0 
    fi
    
    CURRENT_PROCESSING_DATE_FOR_TRAP="${date_to_process_selected}" 
    log_info "Date selected for processing in this run: ${date_to_process_selected}"

    if process_single_date "${date_to_process_selected}"; then
        log_info "Successfully completed all operations for date: ${date_to_process_selected}."
    else
        log_error "Overall processing failed for date: ${date_to_process_selected}. See logs for specific errors."
        exit 1 
    fi
    
    log_info "================== Daily Photo-to-Video Script (v${SCRIPT_VERSION}) Finished Successfully =================="
}

# --- Script Entry Point ---
main_control_flow "$@" 

exit 0
