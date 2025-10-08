import cv2
import numpy as np
import time
import argparse
import json
import threading
import uuid
import datetime
import os
from pathlib import Path
import requests
import schedule
import logging
import sys
from queue import Queue
import urllib.parse
import traceback
import degirum as dg
import subprocess
import signal

model_lock = threading.Lock()

exe_name = os.path.basename(sys.argv[0])
exe_name_with_ext = os.path.splitext(exe_name)[0]

log_directory = "logs"
if not os.path.exists(log_directory):
    os.makedirs(log_directory)

try:
    settings_file = f"{exe_name_with_ext}_settings.json"
    with open(settings_file, 'r') as f:
        config = json.load(f)
    settings = config['settings']
    console_log = settings.get('console_log', True)
    print(f"Console logging: {'Enabled' if console_log else 'Disabled'}")
except Exception as e:
    print(f"Error loading settings file: {e}")
    sys.exit(1)

class ConsoleHandler(logging.StreamHandler):
    def __init__(self, console_log):
        super().__init__(sys.stdout)
        self.console_log = console_log
        
    def emit(self, record):
        if not self.console_log:
            msg = record.getMessage()
            show_patterns = [
                "alert will be sent at",
                "API response for camera",
                "Starting heatmap detection application",
                "Console logging: Disabled"
            ]
            should_show = any(pattern in msg for pattern in show_patterns)
            if should_show:
                super().emit(record)
        else:
            super().emit(record)

console_handler = ConsoleHandler(console_log)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

file_handler = logging.FileHandler(os.path.join(log_directory, "heatmap.log"))
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logger = logging.getLogger('heatmap')
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

logging.getLogger().handlers.clear()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[file_handler, console_handler]
)

try:
    mask_file = "Mask_Config.json"
    logging.info(f"Loading masking configuration from: {mask_file}")
    with open(mask_file, 'r') as f:
        mask_config = json.load(f)
    logging.info(f"Successfully loaded mask configuration from {mask_file}")
except Exception as e:
    logging.warning(f"Error loading mask file: {e}. Proceeding without masking.")
    mask_config = {}

base_image_path = settings['image_path']
api_url = settings['url']
download_api = settings['download_api']
# yolov = settings['yolo']
masked = settings['masked']
send_time = settings['send_time']
reset_time = settings['reset_time']
log_time = settings['log_time']
Processed_frame_number = settings.get('Processed_frame_number', 1800)
rejected_frames_setting = settings.get('rejected_frames', 'enable').lower()

class AppState:
    def __init__(self):
        self.running = True

app_state = AppState()

def signal_handler(sig, frame):
    logging.info("Shutdown signal received, stopping threads...")
    app_state.running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

api_send_lock = threading.Lock()

def calculate_next_interval_time(send_interval_seconds, is_first_run=False):
    now = datetime.datetime.now()
    interval_minutes = send_interval_seconds // 60  # Convert to minutes
    
    if is_first_run:
        # For first run, align to next 5-minute boundary
        current_minute = now.minute
        next_boundary_minute = ((current_minute // 5) + 1) * 5
        next_hour = now.hour
        next_day = now.day
        next_month = now.month
        next_year = now.year
        
        if next_boundary_minute >= 60:
            next_boundary_minute = 0
            next_hour += 1
            if next_hour >= 24:
                next_hour = 0
                next_day += 1
                # Handle month/year rollover if needed
                import calendar
                days_in_month = calendar.monthrange(next_year, next_month)[1]
                if next_day > days_in_month:
                    next_day = 1
                    next_month += 1
                    if next_month > 12:
                        next_month = 1
                        next_year += 1
        
        next_datetime = datetime.datetime(next_year, next_month, next_day, next_hour, next_boundary_minute, 0, 0)
    else:
        # For subsequent runs, calculate next interval
        current_minute = now.minute
        current_interval_minute = (current_minute // interval_minutes) * interval_minutes
        
        next_minute = current_interval_minute + interval_minutes
        next_hour = now.hour
        next_day = now.day
        next_month = now.month
        next_year = now.year
        
        if next_minute >= 60:
            next_minute -= 60
            next_hour += 1
            if next_hour >= 24:
                next_hour = 0
                next_day += 1
                # Handle month/year rollover
                import calendar
                days_in_month = calendar.monthrange(next_year, next_month)[1]
                if next_day > days_in_month:
                    next_day = 1
                    next_month += 1
                    if next_month > 12:
                        next_month = 1
                        next_year += 1
        
        next_datetime = datetime.datetime(next_year, next_month, next_day, next_hour, next_minute, 0, 0)
    
    # Calculate seconds until next time
    seconds_until_next = (next_datetime - now).total_seconds()
    
    # If the calculated time is in the past or too close, move to next interval
    if seconds_until_next <= 5:  # 5 second buffer
        if is_first_run:
            # For first run, try again with is_first_run=False
            return calculate_next_interval_time(send_interval_seconds, False)
        else:
            # Add one more interval
            next_datetime += datetime.timedelta(seconds=send_interval_seconds)
            seconds_until_next = (next_datetime - now).total_seconds()
    
    return next_datetime, seconds_until_next


def initialize_model(settings):
    model_cfg = settings.get("model", {})
    if not model_cfg:
        logging.error("Model configuration missing in settings file.")
        sys.exit(1)
    try:
        logging.info("Loading Degirum model...")
        model = dg.load_model(
            model_name=model_cfg.get("name"),
            inference_host_address=model_cfg.get("inference_host_address", "@local"),
            zoo_url=model_cfg.get("zoo_url"),
            token=model_cfg.get("token", "")
        )
        logging.info("✅ Model loaded successfully from zoo URL")
    except Exception as e:
        logging.error(f"❌ Failed to load model: {e}")
        sys.exit(1)
    return model


# Initialize model
# Initialize model
model = initialize_model(settings)


# Maintain existing dictionaries for camera processing
heatmaps = {}
camera_processing = {}
camera_lock = threading.Lock()
last_api_send_time = {}
camera_status = {}
frame_sequence = {}

def parse_polygon_coordinates(polygon_data):
    try:
        
        if len(polygon_data) % 2 != 0:
            logging.warning(f"Polygon data has odd number of points - dropping last point: {polygon_data}")
            polygon_data = polygon_data[:-1]
        
        polygon_data = [int(coord) for coord in polygon_data]
        points = []
        for i in range(0, len(polygon_data), 2):
            if i + 1 < len(polygon_data):
                points.append([polygon_data[i], polygon_data[i+1]])
        
        return np.array(points, dtype=np.int32)
    
    except Exception as e:
        logging.error(f"Error parsing polygon coordinates: {e}")
        logging.error(f"Problem polygon data: {polygon_data}")
        
        return np.array([], dtype=np.int32)

def load_polygon_masks(mask_config):
    polygons_by_camera = {}

    for camera_id, mask_list in mask_config.items():
        polygons = []

        if isinstance(mask_list, list) and all(isinstance(m, dict) and "Points" in m for m in mask_list):
            for mask in mask_list:
                polygon_data = mask.get("Points", [])
                polygon = parse_polygon_coordinates(polygon_data)
                if len(polygon) > 0:
                    polygons.append(polygon)
        else:
            logging.warning(f"Invalid mask format for camera {camera_id}. Skipping.")

        polygons_by_camera[camera_id] = polygons
        logging.info(f"Loaded {len(polygons)} polygon masks for camera {camera_id}")

    return polygons_by_camera

def is_inside_masked_area(point, polygons):
    if not polygons:
        return False
    
    x, y = point
    for polygon in polygons:
        if cv2.pointPolygonTest(polygon, (x, y), False) >= 0:
            return True
    
    return False

def create_detection_mask(polygons, frame_width, frame_height):
    if not polygons:
        return None
    
    mask = np.ones((frame_height, frame_width), dtype=np.uint8) * 255
    
    cv2.fillPoly(mask, polygons, 0)
    
    return mask

def is_frame_blurry(frame, threshold=100.0):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    return laplacian_var < threshold

def has_color_distortion(frame, tolerance=50):
    b, g, r = cv2.split(frame)
    mean_green = np.mean(g)
    mean_blue = np.mean(b)
    mean_red = np.mean(r)
    return mean_green > (mean_blue + tolerance) and mean_green > (mean_red + tolerance)

def has_white_band(frame, band_height=10, threshold=250):
    height, width, _ = frame.shape
    band_region = frame[:band_height, :, :]
    mean_values = np.mean(band_region, axis=(0, 1))
    return all(value > threshold for value in mean_values)

def is_frame_good_quality(frame):
    if frame is None:
        return False
    
    return not (is_frame_blurry(frame) or has_color_distortion(frame) or has_white_band(frame))

def save_rejected_frame(frame, camera_id):
    if rejected_frames_setting != 'enable':
        return
        
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        year, month, date = datetime.datetime.now().strftime("%Y"), datetime.datetime.now().strftime("%b"), datetime.datetime.now().strftime("%d")
        base_path = f"{base_image_path}rejected_frames/{year}/{month}/{date}/"
        Path(base_path).mkdir(parents=True, exist_ok=True)
        filename = os.path.join(base_path, f"rejected_cam{camera_id}_{timestamp}.jpg")
        cv2.imwrite(filename, frame)
        logging.info(f"Saved rejected frame: {filename}")
    except Exception as e:
        logging.error(f"Error saving rejected frame: {e}")

class FrameBuffer:
    def __init__(self, max_size=30):
        self.queue = Queue(maxsize=max_size)
        self.latest_frame = None
        self.lock = threading.Lock()
        self.rejected_count = 0
        
    def put(self, frame_data):
        if frame_data is None:
            return
        
        with self.lock:
            self.latest_frame = frame_data
        
        if self.queue.full():
            try:
                self.queue.get_nowait()
            except:
                pass
        
        try:
            self.queue.put(frame_data, block=False)
        except:
            pass
    
    def get(self):
        try:
            return self.queue.get(block=False)
        except:
            with self.lock:
                if self.latest_frame is not None:
                    return self.latest_frame
            return None
    
    def size(self):
        return self.queue.qsize()
    
    def clear(self):
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except:
                pass
    
    def increment_rejected(self):
        self.rejected_count += 1
        
    def get_rejected_count(self):
        return self.rejected_count

def log_camera_status(camera_id, status, fps=None, resolution=None):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"{timestamp} | Camera {camera_id} | Status: {status}"
    if status == "Online":
        log_entry += f" | FPS: {fps:.2f} | Resolution: {resolution}"
    
    logging.info(f"Camera {camera_id} | Status: {status}")

def log_frame_loss(camera_id, last_timestamp, new_timestamp, last_seq, new_seq):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    time_diff = (new_timestamp - last_timestamp).total_seconds()
    log_entry = f"{timestamp} | Camera {camera_id} | Frame Gap: {time_diff:.2f}s"
    if last_seq is not None and new_seq is not None and new_seq != last_seq + 1:
        log_entry += f" | Missing Frames: {new_seq - last_seq - 1}"
   



def send_single_camera_to_api(camera_data):
    """Send data for a single camera to the API."""
    camera_id = camera_data['camera_id']
    image_path = camera_data['image_path']
    
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    detection_type = 8
    
    dict1 = {
        "AlertTime": current_time, 
        "CameraId": camera_id, 
        "Type": detection_type, 
        "SceneImagePath": download_api + image_path
    }
    
    logging.info(f"Sending to API for camera {camera_id}")
    
    try:
        x = requests.post(api_url, json=dict1, verify=False)
        logging.info(f"API response for camera {camera_id}: {x.status_code}")
    except Exception as e:
        logging.error(f"Error sending to API for camera {camera_id}: {e}")


def synchronized_api_sender():
    thread_id = threading.get_ident()
    logging.info(f"[API Sender {thread_id}] Thread started.")

    try:
        next_datetime, seconds_until_next = calculate_next_interval_time(send_time, is_first_run=True)
        logging.info(f"First alert will be sent at {next_datetime.strftime('%H:%M:%S')}")

        while app_state.running:
            end_wait_time = time.time() + seconds_until_next
            while time.time() < end_wait_time and app_state.running:
                time.sleep(1)

            if not app_state.running:
                break

            batch_collection_start_time = datetime.datetime.now()
            logging.info(f"Starting batch collection at {batch_collection_start_time.strftime('%H:%M:%S')}")

            camera_data_batch = []
            with api_send_lock:
                heatmap_live_path = "heatmap_live/"
                for entry in config['cameras']:
                    camera_id = entry['id']
                    live_heatmap_file = os.path.join(heatmap_live_path, f"heatmap_cam{camera_id}.jpg")

                    if os.path.exists(live_heatmap_file):
                        last_modified = os.path.getmtime(live_heatmap_file)
                        age_in_seconds = time.time() - last_modified

                        if age_in_seconds <= 90:
                            try:
                                frame = cv2.imread(live_heatmap_file)
                                if frame is None:
                                    logging.warning(f"Camera {camera_id}: frame is None, retrying...")
                                    time.sleep(1)
                                    frame = cv2.imread(live_heatmap_file)

                                if frame is not None:
                                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                                    year, month, date = datetime.datetime.now().strftime("%Y %b %d").split()
                                    api_image_path = f"{base_image_path}heatmap/{year}/{month}/{date}/"
                                    Path(api_image_path).mkdir(parents=True, exist_ok=True)
                                    api_image_filename = f"heatmap_cam{camera_id}_{timestamp}.jpg"
                                    api_fullpath = os.path.join(api_image_path, api_image_filename)
                                    cv2.imwrite(api_fullpath, frame)

                                    camera_data_batch.append({
                                        'camera_id': camera_id,
                                        'image_path': api_fullpath
                                    })
                                else:
                                    logging.warning(f"Camera {camera_id}: frame still None after retry.")
                            except Exception as e:
                                logging.error(f"Camera {camera_id}: Error reading frame: {e}")
                        else:
                            logging.warning(f"Camera {camera_id}: skipped, file too old ({age_in_seconds:.1f} sec)")
                    else:
                        logging.warning(f"Camera {camera_id}: no live heatmap file found.")

            logging.info(f"Sending batch at {datetime.datetime.now().strftime('%H:%M:%S')} with {len(camera_data_batch)} cameras.")

            for camera_data in camera_data_batch:
                try:
                    dict1 = {
                        "AlertTime": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "CameraId": camera_data['camera_id'],
                        "Type": 8,
                        "SceneImagePath": download_api + camera_data['image_path']
                    }
                    x = requests.post(api_url, json=dict1, verify=False)

                    logging.info(f"API response for camera {camera_data['camera_id']}: {x.status_code}")
                except Exception as e:
                    logging.error(f"Error sending Camera {camera_data['camera_id']} API: {e}")

            next_datetime, seconds_until_next = calculate_next_interval_time(send_time, is_first_run=False)
            logging.info(f"Next alert will be sent at {next_datetime.strftime('%H:%M:%S')}")

    except Exception as e:
        logging.error(f"[API Sender {thread_id}] FATAL error: {e}")

    logging.info(f"[API Sender {thread_id}] Exiting.")


def monitor_api_sender_thread(api_sender_thread_ref):
   
    check_interval = 60
    while app_state.running:
        try:
            time.sleep(check_interval)
            
            if not app_state.running:
                break
                
            if not api_sender_thread_ref['thread'].is_alive():
                new_thread = threading.Thread(target=synchronized_api_sender, daemon=True)
                new_thread.start()
                
                api_sender_thread_ref['thread'] = new_thread
                
                logging.info("API sender thread restarted successfully")
                
        except Exception as e:
            logging.error(f"Error in API thread monitor: {e}")
            logging.error(f"Traceback: {traceback.format_exc()}")

def load_polygon_mask(file_path, camid):
    """Load polygons for a specific camera ID."""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        return [np.array(polygon, np.int32) for polygon in data.get(str(camid), [])]
    except FileNotFoundError:
        logging.error(f"File {file_path} not found.")
        return []

def apply_polygon_mask(frame, polygons):
    """Return both masked frame (for debug) and binary mask (for filtering)."""
    if not polygons:
        return frame, None
    
    # binary mask
    mask = np.ones(frame.shape[:2], dtype=np.uint8) * 255
    cv2.fillPoly(mask, polygons, 0)

    # apply for visualization
    masked_frame = cv2.bitwise_and(frame, frame, mask=mask)

    return masked_frame, mask

fade_start_hour = settings.get('fade_start_hour', 0)
fade_end_hour = settings.get('fade_end_hour', 1)
fade_rate = settings.get('fade_rate', 0.02)

def is_fading_time():
    now = datetime.datetime.now()
    start_time = now.replace(hour=fade_start_hour, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=fade_end_hour, minute=0, second=0, microsecond=0)
    return start_time <= now < end_time

def generate_smooth_blob(center_x, center_y, base_radius, frame_width, frame_height):
    
    mask = np.zeros((frame_height, frame_width), dtype=np.float32)
    
    cv2.circle(mask, (center_x, center_y), int(base_radius * 0.8), 1.0, -1)
    
    sigma = base_radius / 2
    mask = cv2.GaussianBlur(mask, (0, 0), sigma)
    
    if np.max(mask) > 0:
        mask = mask / np.max(mask)
    
    return mask

def update_heatmap_with_smooth_blobs(heatmap, detections, frame_width, frame_height):
    frame_mask = np.zeros((frame_height, frame_width), dtype=np.float32)
    
    for center_x, center_y, radius in detections:
        if 0 <= center_x < frame_width and 0 <= center_y < frame_height:
            blob_mask = generate_smooth_blob(center_x, center_y, radius, frame_width, frame_height)
            frame_mask += blob_mask
    intensity = np.random.uniform(0.8, 1.2)
    heatmap += frame_mask * intensity
    
    return heatmap
    
def first_image_save(url, camid, polygons):
    import cv2, numpy as np, subprocess, os, logging
    from pathlib import Path

    image_path = "live_image/"
    masked_image_path = "masked_images/"

    Path(image_path).mkdir(parents=True, exist_ok=True)
    Path(masked_image_path).mkdir(parents=True, exist_ok=True)

    try:
        # Grab a single frame using FFmpeg
        command = [
            "ffmpeg",
            "-rtsp_transport", "tcp",
            "-i", url,
            "-frames:v", "1",           # capture only 1 frame
            "-f", "image2pipe",
            "-vcodec", "mjpeg",         # safer for single-frame decode
            "-"
        ]
        pipe = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        raw_frame = pipe.stdout.read()
        pipe.terminate(); pipe.wait()

        if not raw_frame:
            logging.error(f"Camera {camid}: Failed to capture frame")
            return

        # Decode JPEG to OpenCV image
        frame = cv2.imdecode(np.frombuffer(raw_frame, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            logging.error(f"Camera {camid}: Decoding frame failed")
            return

        # Save live image
        live_image_file = os.path.join(image_path, f"cam{camid}.jpg")
        if cv2.imwrite(live_image_file, frame):
            logging.info(f"Live image saved at: {live_image_file}")
        else:
            logging.error(f"Camera {camid}: Failed to save live image")

        # Apply polygons and save masked image
        if polygons:
            masked_frame, binary_mask = apply_polygon_mask(frame.copy(), polygons)
            masked_image_file = os.path.join(masked_image_path, f"masked_cam{camid}.jpg")
            if masked_frame is not None and isinstance(masked_frame, np.ndarray):
                if cv2.imwrite(masked_image_file, masked_frame):
                    logging.info(f"Masked image saved at: {masked_image_file}")
                else:
                    logging.error(f"Camera {camid}: Failed to save masked image")
            else:
                logging.error(f"Camera {camid}: masked_frame is invalid")


    except Exception as e:
        logging.error(f"Camera {camid}: Error in first_image_save: {e}")


def check_camera_status(url):
    """Check if a camera is online using FFmpeg"""
    import subprocess, logging
    try:
        command = [
            "ffmpeg",
            "-rtsp_transport", "tcp",
            "-i", url,
            "-frames:v", "1",
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-"
        ]
        pipe = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        raw_frame = pipe.stdout.read()
        pipe.terminate(); pipe.wait()
        return bool(raw_frame)
    except Exception as e:
        logging.error(f"Error checking camera status: {e}")
        return False

def monitor_offline_cameras(cameras_config):
    while app_state.running:
        for entry in cameras_config:
            camid = entry['id']
            url = entry['url']
            # Get camera-specific threshold or use default
            camera_threshold = entry.get('person_detection_threshold', settings.get('person_detection_threshold', 0.6))
            
            with camera_lock:
                if not camera_processing.get(camid, True):
                    if check_camera_status(url):
                        logging.info(f"Camera {camid} is back online. Restarting processing...")
                        camera_processing[camid] = True
                        
                        if "True" == masked:
                            polygons = []
                            str_camera_id = str(camid)
                            if str_camera_id in mask_config:
                                polygons = load_polygon_masks(mask_config)[str_camera_id]
                            
                            if not polygons:
                                polygons = load_polygon_mask('Mask_Config.json', camid)
                                
                            if polygons:
                                t = threading.Thread(target=camera_worker, args=(camid, url, polygons, camera_threshold), daemon=True)
                                t.start()
                                log_camera_status(camid, "Restarted")
                            else:
                                t = threading.Thread(target=camera_worker, args=(camid, url, None, camera_threshold), daemon=True)
                                t.start()
                                log_camera_status(camid, "Restarted (without masking)")
                        else:
                            t = threading.Thread(target=camera_worker, args=(camid, url, None, camera_threshold), daemon=True)
                            t.start()
                            log_camera_status(camid, "Restarted")
        time.sleep(30)

def open_ffmpeg_stream(url, width=1280, height=720):
    """
    Start a persistent ffmpeg process that continuously decodes frames.
    Returns a subprocess.Popen object with stdout as a raw video pipe.
    """
    command = [
                "ffmpeg",
                "-rtsp_transport", "tcp",
                "-fflags", "nobuffer",
                "-flags", "low_delay",
                "-strict", "experimental",
                "-use_wallclock_as_timestamps", "1",
                "-rtsp_flags", "prefer_tcp",
                "-i", url,
                "-f", "image2pipe",
                "-vcodec", "mjpeg",
                "-"
            ]

    return subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,  # hide ffmpeg logs
        bufsize=10**8
    )

def frame_reader_thread(camera_id, url, frame_buffer: Queue, error_flag,
                        polygons=None, app_state=None, target_fps=25,
                        width=1280, height=720):

    logging.info(f"Frame reader started for camera {camera_id} at {target_fps} fps")

    try:
        command = [
            "ffmpeg",
            "-rtsp_transport", "tcp",
            "-i", url,
            "-f", "rawvideo",        # raw RGB frames
            "-pix_fmt", "bgr24",     # OpenCV compatible
            "-vf", f"fps={target_fps},scale={width}:{height}",
            "-"
        ]

        pipe = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8)
        frame_size = width * height * 3  # bgr24

        while app_state.running:
            raw_frame = pipe.stdout.read(frame_size)
            if len(raw_frame) < frame_size:
                logging.warning(f"Camera {camera_id}: incomplete frame")
                time.sleep(0.01)
                continue

            frame = np.frombuffer(raw_frame, np.uint8).reshape((height, width, 3))

            # Apply polygon mask if available
            masked_frame, binary_mask = None, None
            if polygons:
                masked_frame, binary_mask = apply_polygon_mask(frame.copy(), polygons)

            # Push to frame buffer
            frame_buffer.put({
                "frame": frame,
                "mask": binary_mask,
                "masked_frame": masked_frame
            })

    except Exception as e:
        logging.error(f"Frame reader error for camera {camera_id}: {e}")
        error_flag.set()
    finally:
        if pipe:
            pipe.terminate()
            pipe.wait()
            logging.info(f"Camera {camera_id}: ffmpeg process closed")





def process_heatmap(camera_id, frame_buffer, error_flag, detection_threshold):
    """
    Rewritten to use degirum model via callable interface: results = model(frame)
    Parses degirum results to bounding boxes and updates heatmap accordingly.
    """
    logging.info(f"Heatmap processor started for camera {camera_id} with threshold {detection_threshold}")

    # timing / stats vars
    last_hit_time = time.time()
    last_print_time = time.time()
    count = 0
    start_time2 = time.time()
    total_frames = 0
    fade_rate = 0.02
    target_fps = 5
    last_process_time = 0
    frame_counter = 0

    # wait for at least one frame
    initial_frame_data = None
    while app_state.running:
        frame_counter += 1
        initial_frame_data = frame_buffer.get()
        if initial_frame_data is not None:
            break
        time.sleep(0.1)

    if initial_frame_data is None:
        logging.error(f"Could not get initial frame for camera {camera_id}, exiting processor")
        error_flag.set()
        return

    initial_frame = initial_frame_data['frame']
    frame_height, frame_width = initial_frame.shape[:2]
    logging.info(f"Camera {camera_id}: Processing frames at {frame_width}x{frame_height}")

    if camera_id not in heatmaps:
        heatmaps[camera_id] = np.zeros((frame_height, frame_width), dtype=np.float32)

    def _parse_degirum_results(results, score_thres=0.3):
        parsed = []
        candidate_list = getattr(results, "results", results)
        if candidate_list is None:
            return parsed
        if isinstance(candidate_list, (list, tuple, np.ndarray)):
            for det in candidate_list:
                try:
                    if isinstance(det, (list, tuple, np.ndarray)):
                        arr = np.array(det).ravel()
                        if arr.size >= 5:
                            x1, y1, x2, y2, conf = map(float, arr[:5])
                            if conf < score_thres:
                                continue
                            if x2 - x1 <= 0 or y2 - y1 <= 0:
                                w, h = x2, y2
                                x2 = x1 + w
                                y2 = y1 + h
                            parsed.append([int(x1), int(y1), int(x2), int(y2), conf])
                            continue
                    elif isinstance(det, dict):
                        cat = int(det.get("category_id", det.get("class", -1)))
                        conf = float(det.get("score", det.get("confidence", 0.0)))
                        bbox = det.get("bbox", det.get("box", None))
                        if cat != 0 or conf < score_thres or bbox is None or len(bbox) < 4:
                            continue
                        x1, y1, x2, y2 = map(float, bbox[:4])
                        if x2 - x1 <= 0 or y2 - y1 <= 0:
                            x, y, w, h = x1, y1, x2, y2
                            x2 = x + w
                            y2 = y + h
                            x1, y1 = x, y
                        parsed.append([int(x1), int(y1), int(x2), int(y2), conf])
                        continue
                    elif hasattr(det, "bbox") and hasattr(det, "score") and hasattr(det, "category_id"):
                        cat = int(det.category_id)
                        conf = float(det.score)
                        bbox = det.bbox
                        if cat != 0 or conf < score_thres or bbox is None or len(bbox) < 4:
                            continue
                        x1, y1, x2, y2 = map(float, bbox[:4])
                        if x2 - x1 <= 0 or y2 - y1 <= 0:
                            x, y, w, h = x1, y1, x2, y2
                            x2 = x + w
                            y2 = y + h
                            x1, y1 = x, y
                        parsed.append([int(x1), int(y1), int(x2), int(y2), conf])
                        continue
                    elif hasattr(det, "boxes"):
                        boxes = getattr(det, "boxes")
                        data = getattr(boxes, "data", boxes)
                        for b in data:
                            arr = np.array(b).ravel()
                            if arr.size >= 5:
                                x1, y1, x2, y2, conf = map(float, arr[:5])
                                if conf < score_thres:
                                    continue
                                parsed.append([int(x1), int(y1), int(x2), int(y2), conf])
                except Exception:
                    continue
        return parsed

    # main loop
    while app_state.running:
        try:
            current_time = time.time()
            if current_time - last_process_time < 1.0 / target_fps:
                time.sleep(0.01)
                continue

            frame_data = frame_buffer.get()
            if frame_data is None:
                time.sleep(0.05)
                continue

            frame = frame_data['frame']
            detection_mask = frame_data['mask']   # <-- only used inside detection loop

            frame_counter += 1
            if frame_counter % 2 != 0:
                continue

            total_frames += 1
            last_process_time = current_time

            try:
                with model_lock:
                    results = model(frame)
                boxes = _parse_degirum_results(results, detection_threshold)
            except Exception as e:
                logging.error(f"Model inference error for camera {camera_id}: {e}")
                error_flag.set()
                time.sleep(0.5)
                continue

            circles = []
            detected_person = False

            for b in boxes:
                try:
                    x1, y1, x2, y2, conf = b
                    x1 = max(0, min(frame_width - 1, int(x1)))
                    y1 = max(0, min(frame_height - 1, int(y1)))
                    x2 = max(0, min(frame_width - 1, int(x2)))
                    y2 = max(0, min(frame_height - 1, int(y2)))
                    if x2 <= x1 or y2 <= y1:
                        continue

                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2

                    # ✅ proper mask filtering
                    if detection_mask is not None:
                        if not (0 <= center_x < detection_mask.shape[1] and 0 <= center_y < detection_mask.shape[0]):
                            continue
                        if detection_mask[center_y, center_x] == 0:
                            logging.debug(f"Camera {camera_id}: Mask rejected center ({center_x},{center_y})")
                            continue

                    radius = int((x2 - x1) / 2)
                    circles.append((center_x, center_y, radius))
                    detected_person = True
                except Exception:
                    continue

            if detected_person and circles:
                if frame_counter % 5 == 0:
                    heatmaps[camera_id] = update_heatmap_with_smooth_blobs(
                        heatmaps[camera_id].copy(), circles, frame_width, frame_height
                    )
                last_hit_time = current_time
                last_print_time = current_time
            else:
                if is_fading_time() and current_time - last_print_time >= 20:
                    count += 1
                    elapsed_time = current_time - last_hit_time
                    fade_amount = fade_rate * elapsed_time
                    heatmaps[camera_id] = np.maximum(heatmaps[camera_id] - fade_amount, 0)
                    last_print_time = current_time

            try:
                heatmap_normalized = cv2.normalize(heatmaps[camera_id], None, 0, 255, cv2.NORM_MINMAX)
                heatmap_colored = cv2.applyColorMap(np.uint8(heatmap_normalized), cv2.COLORMAP_JET)
                heatmap_colored = cv2.GaussianBlur(heatmap_colored, (5, 5), 0)
                overlay = cv2.addWeighted(frame, 0.6, heatmap_colored, 0.4, 0)
                Path("heatmap_live").mkdir(parents=True, exist_ok=True)
                live_heatmap_filename = f"heatmap_live/heatmap_cam{camera_id}.jpg"
                cv2.imwrite(live_heatmap_filename, overlay)
            except Exception as e:
                logging.error(f"Camera {camera_id}: Failed to render/save heatmap overlay: {e}")

        except Exception as e:
            logging.error(f"Error in heatmap processing for camera {camera_id}: {e}")
            error_flag.set()
            time.sleep(1)


    
def camera_worker(camera_id, url, polygons=None, detection_threshold=0.6):
    logging.info(f"Starting camera worker for camera {camera_id} with detection threshold {detection_threshold}")
    first_image_save(url, camera_id, polygons)
    frame_buffer = FrameBuffer(max_size=30)
    error_flag = threading.Event()

    # ✅ Determine FPS (per-camera > global > default=5)
    global_fps = settings.get("target_fps", 5)
    target_fps = global_fps
    for cam in config["cameras"]:
        if cam["id"] == camera_id:
            target_fps = cam.get("target_fps", global_fps)
            break

    logging.info(f"Camera {camera_id}: using target_fps={target_fps}")

    # Reader thread with fps
    reader_thread = threading.Thread(
        target=frame_reader_thread,
        args=(camera_id, url, frame_buffer, error_flag, polygons, app_state, target_fps),
        daemon=True
    )
    reader_thread.start()

    # Processor thread
    processor_thread = threading.Thread(
        target=process_heatmap,
        args=(camera_id, frame_buffer, error_flag, detection_threshold),
        daemon=True
    )
    processor_thread.start()

    while app_state.running:
        if not reader_thread.is_alive():
            logging.warning(f"Reader thread for camera {camera_id} died, restarting...")
            frame_buffer.clear()
            reader_thread = threading.Thread(
                target=frame_reader_thread,
                args=(camera_id, url, frame_buffer, error_flag, polygons, app_state, target_fps),
                daemon=True
            )
            reader_thread.start()

        if not processor_thread.is_alive():
            logging.warning(f"Processor thread for camera {camera_id} died, restarting...")
            processor_thread = threading.Thread(
                target=process_heatmap,
                args=(camera_id, frame_buffer, error_flag, detection_threshold),
                daemon=True
            )
            processor_thread.start()

        if error_flag.is_set():
            logging.warning(f"Error occurred in camera {camera_id}, resetting...")
            error_flag.clear()

        time.sleep(5)

    logging.info(f"Camera worker for camera {camera_id} stopping")


def delete_old_logs():
    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=log_retention_days)
    log_files = [
        "logs/heatmap.log"
    ]
    
    for log_file in log_files:
        if os.path.exists(log_file):
            try:
                file_mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(log_file))
                if file_mod_time < cutoff_date:
                    os.remove(log_file)
                    logging.info(f"Deleted old log file: {log_file}")
            except Exception as e:
                logging.error(f"Error deleting log file {log_file}: {e}")


def schedule_deletion():
    schedule.every().day.at(reset_time).do(delete_old_images)
    schedule.every().day.at(reset_time).do(delete_old_logs)
    while app_state.running:
        schedule.run_pending()
        time.sleep(60)

def delete_old_images():
    logging.info("Deleting old image files...")
    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=7)  # keep 7 days
    folders_to_clean = [
        os.path.join(base_image_path, 'rejected_frames'),
        os.path.join(base_image_path, 'heatmap'),
        "heatmap_live"
    ]
    for folder in folders_to_clean:
        if os.path.exists(folder):
            for root, dirs, files in os.walk(folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        file_mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
                        if file_mod_time < cutoff_date:
                            os.remove(file_path)
                            logging.info(f"Deleted old image: {file_path}")
                    except Exception as e:
                        logging.error(f"Error deleting file {file_path}: {e}")


def main(config_path=None):
    if config_path is None:
        config_path = f"{exe_name_with_ext}_settings.json"
        
    logging.info(f"Starting heatmap detection application with config {config_path}")
    global config
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        cameras = config['cameras']
    except Exception as e:
        logging.error(f"Failed to load configuration: {e}")
        return
    polygons_by_camera = load_polygon_masks(mask_config)
    logging.info(f"Loaded polygon masks for {len(polygons_by_camera)} cameras from Mask_Config.json")

    image_directories = [
        os.path.join(base_image_path, 'rejected_frames'),
        os.path.join(base_image_path, 'heatmap'),
        "live_image",
        "masked_images",
        "heatmap_live"
    ]
    
    if rejected_frames_setting == 'enable':
        for directory in image_directories:
            Path(directory).mkdir(parents=True, exist_ok=True)
    else:
        for directory in image_directories:
            if 'rejected_frames' not in directory:
                Path(directory).mkdir(parents=True, exist_ok=True)
    
    deletion_thread = threading.Thread(target=schedule_deletion, daemon=True)
    deletion_thread.start()
    
    frame_status_clear_thread = threading.Thread(target=lambda: 
        schedule.run_pending() if app_state.running else None, 
        daemon=True
    )
    frame_status_clear_thread.start()
    monitor_thread = threading.Thread(target=monitor_offline_cameras, args=(cameras,), daemon=True)
    monitor_thread.start()
    logging.info("Camera monitoring thread started.")
    
    api_sender_thread_ref = {}
    api_sender_thread = threading.Thread(target=synchronized_api_sender, daemon=True)
    api_sender_thread.start()
    api_sender_thread_ref['thread'] = api_sender_thread
   # logging.info("Synchronized API sender thread started.")
    
    api_monitor_thread = threading.Thread(
        target=monitor_api_sender_thread, 
        args=(api_sender_thread_ref,), 
        daemon=True
    )
    api_monitor_thread.start()
   # logging.info("API sender monitor thread started.")
    
    camera_threads = []
    
    if "True" == masked:
        for entry in cameras:
            camid = entry['id']
            url = entry['url']
            # Get camera-specific threshold or use global default
            camera_threshold = entry.get('person_detection_threshold', settings.get('person_detection_threshold', 0.6))
            
            #logging.info(f"Starting thread for URL: {url} with ID: {camid} and threshold: {camera_threshold}")
        
            polygons = []
            str_camera_id = str(camid)
            if str_camera_id in mask_config:
                polygons = polygons_by_camera.get(str_camera_id, [])
                
            if not polygons:
                polygons = load_polygon_mask('Mask_Config.json', camid)
                
            if polygons:
               # logging.info(f"Polygon coordinates for Camera ID {camid} loaded successfully: {len(polygons)} polygon(s)")
                t = threading.Thread(target=camera_worker, args=(camid, url, polygons, camera_threshold), daemon=True)
                camera_threads.append(t)
                t.start()
            else:
               # logging.info(f"No polygon coordinates found for Camera ID {camid}, processing without masking")
                t = threading.Thread(target=camera_worker, args=(camid, url, None, camera_threshold), daemon=True)
                camera_threads.append(t)
                t.start()
    else:
        for entry in cameras:
            camid = entry['id']
            url = entry['url']
            # Get camera-specific threshold or use global default
            camera_threshold = entry.get('person_detection_threshold', settings.get('person_detection_threshold', 0.6))
            
           # logging.info(f"Starting thread for URL: {url} with ID: {camid} and threshold: {camera_threshold}")
            t = threading.Thread(target=camera_worker, args=(camid, url, None, camera_threshold), daemon=True)
            camera_threads.append(t)
            t.start()
    try:
        while any(t.is_alive() for t in camera_threads) and app_state.running:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Received keyboard interrupt, shutting down...")
        app_state.running = False
    
    for thread in camera_threads:
        thread.join(timeout=5.0)
    
    logging.info("Application shutdown complete")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Heatmap Generation System')
    parser.add_argument('--config', type=str, help='Path to configuration file')
    args = parser.parse_args()
    
    main(args.config)