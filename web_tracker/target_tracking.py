import gc
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

from HikvisionAPI import HikvisionAPI
from pysot.core.config import cfg
from pysot.models.model_builder import ModelBuilder
from pysot.tracker.tracker_builder import build_tracker

gc.enable()


class TargetTracking:
    def __init__(self):
        self.trackers = []
        project_path = os.getcwd()
        self.config_file = project_path + "\siamrpn_alex_dwxcorr\config.yaml"
        self.model_snapshot = project_path + "\siamrpn_alex_dwxcorr\model.pth"
        torch.set_num_threads(10)
        self._load_config()
        self._load_model()
        self.lock = threading.Lock()
        self.pending_trackers = []
        self.frames_queue = queue.Queue(maxsize=10)
        self.running = True
        self.prev_bbox_centers = {}
        self.last_movement_direction = None
        self.movement_direction_queue = queue.Queue()

    def _load_config(self):
        cfg.merge_from_file(self.config_file)
        cfg.CUDA = torch.cuda.is_available()

    def _load_model(self):
        self.model = ModelBuilder()
        self.model.load_state_dict(torch.load(self.model_snapshot,
                                              map_location=lambda storage, loc: storage.cuda()))
        if torch.cuda.is_available():
            self.model = self.model.to(torch.device('cuda:0'))

    def draw_chinese_text(self, image, text, position, font_path='C:/Windows/Fonts/Dengb.ttf',
                          font_size=35, color=(255, 255, 255)):
        img_pil = Image.fromarray(image)
        draw = ImageDraw.Draw(img_pil)
        font = ImageFont.truetype(font_path, font_size)
        draw.text(position, text, font=font, fill=color)
        return np.array(img_pil)

    def track_frame(self, tracker, frame, label):
        outputs = tracker.track(frame)
        bbox = list(map(int, outputs['bbox']))
        center_x = bbox[0] + bbox[2] // 2
        center_y = bbox[1] + bbox[3] // 2
        return (bbox, label, (center_x, center_y))

    def add_target(self, init_rect, label):
        with self.lock:
            tracker = build_tracker(self.model)
            self.pending_trackers.append((tracker, init_rect, label))

    def stop_tracking(self):
        with self.lock:
            self.trackers = []
            self.pending_trackers = []

    def stop_play(self):
        with self.lock:
            self.running = False
            self.trackers = []
            self.pending_trackers = []

    def calculate_shift_to_center(self, frame, bbox):
        height, width, _ = frame.shape
        frame_center_x = width // 2
        frame_center_y = height // 2
        x, y, w, h = bbox
        bbox_center_x = x + w // 2
        bbox_center_y = y + h // 2
        shift_x = frame_center_x - bbox_center_x
        shift_y = frame_center_y - bbox_center_y
        return (shift_x, shift_y)

    def get_camera_movement_direction(self, shift_x, shift_y, threshold=30):
        direction = ""

        if abs(shift_x) > threshold or abs(shift_y) > threshold:
            if shift_x < threshold:
                direction += "RIGHT_"
            elif shift_x > -threshold:
                direction += "LEFT_"
            if shift_y > threshold:
                direction += "UP"
            elif shift_y < -threshold:
                direction += "DOWN"
        return direction.rstrip("_")

    # def process_frame(self, frame):
    #     with self.lock:
    #         for pending_tracker, init_rect, label in self.pending_trackers:
    #             pending_tracker.init(frame, init_rect)
    #             self.trackers.append((pending_tracker, label))
    #         self.pending_trackers = []
    #
    #     if self.trackers:
    #         with ThreadPoolExecutor(max_workers=2) as executor:
    #             tracker_list, label_list = zip(*self.trackers)
    #             results = list(executor.map(self.track_frame, tracker_list,
    #                                         [frame] * len(tracker_list),
    #                                         label_list))
    #
    #             for bbox, label, center in results:
    #                 shift_x, shift_y = self.calculate_shift_to_center(frame, bbox)
    #
    #                 movement_direction = self.get_camera_movement_direction(shift_x, shift_y)
    #                 self.movement_direction_queue.put(movement_direction)
    #
    #                 text = label
    #                 font_size = 18
    #                 position = (bbox[0], bbox[1] - font_size)
    #                 frame = self.draw_chinese_text(image=frame, text=text, position=position)
    #
    #     self.frames_queue.put(frame)

    def tracking_object(self, rtsp_url):
        try:
            cap = cv2.VideoCapture(rtsp_url)
            skip_frames = 3  # 跳过帧数
            desired_fps = 30
            cap.set(cv2.CAP_PROP_FPS, desired_fps)
            while cap.isOpened() and self.running:
                prev_time = cap.get(cv2.CAP_PROP_POS_MSEC)

                for _ in range(skip_frames):  # 跳过一定数量的帧
                    ret, frame = cap.read()
                    if not ret:
                        break
                if not ret:
                    break
                # 缩放帧分辨率
                # frame = cv2.resize(frame, None, fx=0.5, fy=0.5)

                with self.lock:
                    for pending_tracker, init_rect, label in self.pending_trackers:
                        pending_tracker.init(frame, init_rect)
                        self.trackers.append((pending_tracker, label))
                    self.pending_trackers = []

                if self.trackers:
                    with ThreadPoolExecutor(max_workers=5) as executor:
                        tracker_list, label_list = zip(*self.trackers)
                        results = list(executor.map(self.track_frame, tracker_list,
                                                    [frame] * len(tracker_list),
                                                    label_list))

                        for bbox, label, center in results:
                            shift_x, shift_y = self.calculate_shift_to_center(frame, bbox)

                            movement_direction = self.get_camera_movement_direction(shift_x, shift_y)
                            self.movement_direction_queue.put(movement_direction)

                            text = label
                            font_size = 18
                            position = (bbox[0], bbox[1] - font_size)
                            frame = self.draw_chinese_text(image=frame, text=text, position=position)

                self.frames_queue.put(frame)

            cap.release()
        except Exception as e:
            print(f'Error in capture loop: {repr(e)}')

    # def tracking_object(self, rtsp_url):
    #     try:
    #         cap = cv2.VideoCapture(rtsp_url)
    #         skip_frames = 2  # 跳过帧数
    #
    #         with ThreadPoolExecutor(max_workers=2) as executor:
    #             while cap.isOpened() and self.running:
    #                 # prev_time = cap.get(cv2.CAP_PROP_POS_MSEC)
    #
    #                 for _ in range(skip_frames):  # 跳过一定数量的帧
    #                     ret, frame = cap.read()
    #                     if not ret:
    #                         break
    #
    #                 if not ret:
    #                     break
    #
    #                 # next_time = cap.get(cv2.CAP_PROP_POS_MSEC)
    #                 # interval = next_time - prev_time
    #                 # cv2.waitKey(int(interval))
    #
    #                 executor.submit(self.process_frame, frame)
    #
    #         cap.release()
    #     except Exception as e:
    #         print(f'Error in capture loop: {repr(e)}')

    def controlling(self, data):
        while True:
            direction_queue = self.movement_direction_queue.get()
            if direction_queue:
                self.frame_controlling(data, 0, direction_queue)
            else:
                self.frame_controlling(data, 1)

    def frame_controlling(self, data, action, direction_queue="LEFT"):
        if self.last_movement_direction != direction_queue:
            controlling = {"cameraIndexCode": data['cameraIndexCode'], "action": action,
                           "command": direction_queue,
                           "speed": 16, "presetIndex": 0}
            controlling_api = HikvisionAPI(uapi=data['uapi'], appKey=data['appKey'],
                                           appSecret=data['appSecret'],
                                           headers_url="/artemis/api/video/v1/ptzs/controlling",
                                           data=controlling)
            controlling_api.request()
            self.last_movement_direction = direction_queue

    def get_frame(self):
        while True:
            frame = self.frames_queue.get()
            ret, jpeg = cv2.imencode('.jpg', frame)
            data = jpeg.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + data + b'\r\n')
