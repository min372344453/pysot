import json
import os
import queue
import threading

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, render_template, Response, request, jsonify

from HikvisionAPI import HikvisionAPI
from pysot.core.config import cfg
from pysot.models.model_builder import ModelBuilder
from pysot.tracker.tracker_builder import build_tracker


class VideoStreamer:
    def __init__(self, config_file, model_snapshot):
        self.app = Flask(__name__, static_folder='templates/static')
        self.config_file = config_file
        self.model_snapshot = model_snapshot

        torch.set_num_threads(3)

        self._load_config()
        self._load_model()
        self._build_tracker()
        self.rtsp_url = None
        self.init_rect = None
        self.last_rect = None
        self.previous = None
        self.StopPlay = True
        self.address = None
        self.appkey = None
        self.secret = None
        self.cameraIndexCode = None
        self.init_rect = None
        self.last_rect = None
        self.frame_queue = queue.Queue(maxsize=100)
        self.result_queue = queue.Queue(maxsize=100)
        self.tracker = None
        self.cap_thread = None
        self.process_thread = None
        self.speed = None
        self.last_feature = None
        self.up_image = None
        self.interval = None
        self.width = None
        self.height = None

    def _load_config(self):
        cfg.merge_from_file(self.config_file)
        cfg.CUDA = torch.cuda.is_available()  # 检查是否有可用的GPU

    def _load_model(self):
        self.model = ModelBuilder()
        self.model.load_state_dict(torch.load(self.model_snapshot,
                                              map_location=lambda storage, loc: storage.cuda()))
        if torch.cuda.is_available():
            self.model = self.model.to(torch.device('cuda:0'))  # 将模型移动到GPU 0上
        self.model.eval()

    def _build_tracker(self):

        @self.app.route('/')
        def index():
            # 渲染HTML模板
            return render_template('index.html')

        @self.app.route('/video_feed')
        def video_feed():
            # 返回带有视频流的响应
            return Response(self.get_frame(), mimetype='multipart/x-mixed-replace; boundary=frame')

        @self.app.route('/SetDisplaySize', methods=['POST'])
        def SetDisplaySize():
            data = request.get_data()
            data = json.loads(data)
            print(data)
            startX = data['selZoom']['startX']
            startY = data['selZoom']['startY']
            endX = data['selZoom']['endX']
            endY = data['selZoom']['endY']
            selZoom = {
                "cameraIndexCode": self.cameraIndexCode,
                "startX": startX / 5,
                "startY": startY / 2.82,
                "endX": endX / 5,
                "endY": endY / 2.82
            }
            # 聚焦
            selZoom = HikvisionAPI(uapi=self.address,
                                   appKey=self.appkey,
                                   appSecret=self.secret,
                                   headers_url="/artemis/api/video/v1/ptzs/selZoom",
                                   data=selZoom)
            zoom_request = selZoom.request()
            if zoom_request.get('code') == '0':
                return jsonify("True")
            else:
                return "False"

        @self.app.route('/StartTracking', methods=['POST'])
        def StartTracking():
            data = request.get_data()
            data = json.loads(data)
            print(data['init_rect'])
            # 设置跟踪目标
            self.init_rect = list(data['init_rect'].values())
            return jsonify("True")

        @self.app.route('/StopTracking')
        def StopTracking():
            self.init_rect = None
            request = self.stopMove()
            if request.get('code') == '0':
                return jsonify("True")
            else:
                return jsonify("False")

        @self.app.route('/StopPlay')
        def StopPlay():
            self.cap_thread = None
            self.process_thread = None
            self.StopPlay = False
            # 清空队列
            while not self.frame_queue.empty():
                self.frame_queue.get()
            while not self.result_queue.empty():
                self.result_queue.get()
            # 清除处理和结果队列
            # self.frame_queue.queue.clear()
            # self.result_queue.queue.clear()
            # self.frame_queue.join()
            # self.result_queue.join()

            return jsonify("True")

        @self.app.route('/SetMovementSpeed', methods=['POST'])
        def SetMovementSpeed():
            data = request.get_data()
            data = json.loads(data)
            self.speed = data['speed']
            return jsonify("True")

        @self.app.route('/SetCamera', methods=['POST'])
        def SetCamera():
            data = request.get_data()
            data = json.loads(data)
            self.address = data['address']
            self.appkey = data['appkey']
            self.secret = data['secret']
            self.cameraIndexCode = data['id']
            previewURLs = {
                "cameraIndexCode": self.cameraIndexCode,
                "streamType": 0,
                "protocol": "rtsp",
                "transmode": 0,
                "expand": "streamform=rtp"
            }
            # self.rtsp_url = 'rtsp://admin:Admin12345@192.168.0.65:554/h264/ch33/main/av_stream'
            res = HikvisionAPI(uapi=self.address,
                               appKey=self.appkey,
                               appSecret=self.secret,
                               headers_url="/artemis/api/video/v1/cameras/previewURLs",
                               data=previewURLs)
            data = res.request()

            rtsp_url = data['data']['url']
            self.rtsp_url = rtsp_url
            #  启动视频捕获和帧处理线程
            if self.cap_thread is None and self.process_thread is None:
                self.StopPlay = True
                self.cap_thread = threading.Thread(target=self._capture_loop)
                self.process_thread = threading.Thread(target=self._process_loop)
                self.cap_thread.start()
                self.process_thread.start()
            if data.get('code') == '0':
                return jsonify("True")
            else:
                return jsonify("False")

    def stopMove(self):
        # 控制摄像头移动
        controlling = {
            "cameraIndexCode": self.cameraIndexCode,
            "action": 0,
            "command": "GOTO_PRESET",
            "speed": 4,
            "presetIndex": 0
        }
        # 发送控制命令
        controlling_api = HikvisionAPI(uapi=self.address,
                                       appKey=self.appkey,
                                       appSecret=self.secret,
                                       headers_url="/artemis/api/video/v1/ptzs/controlling",
                                       data=controlling)
        request = controlling_api.request()
        return request

    # 获取目标在屏幕中心时的坐标
    def get_center_coordinate(self, target_coordinate, screen_size):
        screen_width, screen_height = screen_size
        target_x, target_y = target_coordinate
        center_x = int(screen_width / 2)
        center_y = int(screen_height / 2)
        delta_x = target_x - center_x
        delta_y = target_y - center_y
        return delta_x, delta_y

    def set_parameter(self, controlling):
        if self.previous != controlling["command"]:
            self.previous = controlling["command"]
        else:
            return

    # 控制摄像头移动到保持目标在屏幕中心
    def move_camera_to_center(self, target_coordinate, screen_size):
        # 获取目标在屏幕中心时的坐标
        delta_x, delta_y = self.get_center_coordinate(target_coordinate, screen_size)

        # 控制摄像头移动
        controlling = {
            "cameraIndexCode": self.cameraIndexCode,
            "action": 0,
            "command": "",
            "speed": 4,
            "presetIndex": 0
        }

        if delta_x <= 0 and abs(delta_x) > abs(delta_y):
            controlling["command"] = "LEFT"
            if self.previous != controlling["command"]:
                self.previous = controlling["command"]
            else:
                return
        elif delta_x >= 0 and abs(delta_x) > abs(delta_y):
            controlling["command"] = "RIGHT"
            if self.previous != controlling["command"]:
                self.previous = controlling["command"]
            else:
                return
        elif delta_y <= 0 and abs(delta_y) > abs(delta_x):
            controlling["command"] = "UP"
            if self.previous != controlling["command"]:
                self.previous = controlling["command"]
            else:
                return
        elif delta_y >= 0 and abs(delta_y) > abs(delta_x):
            controlling["command"] = "DOWN"
            if self.previous != controlling["command"]:
                self.previous = controlling["command"]

            else:
                return
        else:
            print("结束了")
            self.previous = controlling["command"]
            self.previous = controlling["action"] = 1

        # 调整速度和预置位
        controlling["speed"] = self.speed
        controlling["presetIndex"] = 0

        # 发送控制命令
        controlling_api = HikvisionAPI(uapi=self.address,
                                       appKey=self.appkey,
                                       appSecret=self.secret,
                                       headers_url="/artemis/api/video/v1/ptzs/controlling",
                                       data=controlling)
        controlling_api.request()

    def automatic_stop(self, bbox, frame):
        if bbox[0] < 0:
            bbox[0] = 0
            self.init_rect = None
            self.stopMove()
        if bbox[1] < 0:
            bbox[1] = 0
            self.init_rect = None
            self.stopMove()
        if bbox[0] + bbox[2] > frame.shape[1]:
            bbox[2] = frame.shape[1] - bbox[0]
            self.init_rect = None
            self.stopMove()
        if bbox[1] + bbox[3] > frame.shape[0]:
            bbox[3] = frame.shape[0] - bbox[1]
            self.init_rect = None
            self.stopMove()

    def _capture_loop(self):
        try:
            cap = cv2.VideoCapture(self.rtsp_url)
            # 循环读取视频帧并计算时间间隔
            while cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    prev_time = cap.get(cv2.CAP_PROP_POS_MSEC)
                    ret, frame = cap.read()
                    if ret:
                        next_time = cap.get(cv2.CAP_PROP_POS_MSEC)
                        self.interval = next_time - prev_time
                        cv2.waitKey(int(self.interval * 1.2))
                        self.frame_queue.put(frame)
                    else:
                        break
                else:
                    break
            # while self.StopPlay:
            #     prev_time = cap.get(cv2.CAP_PROP_POS_MSEC)
            #     ret, frame = cap.read()
            #
            #     if not ret:
            #         break
            #     # 将图像大小调整为较小的尺寸
            #     frame = cv2.resize(frame, (1280, 740))
            #     # next_time = cap.get(cv2.CAP_PROP_POS_MSEC)
            #     # interval = next_time - prev_time
            #     # cv2.waitKey(int(interval*1))
            #     self.frame_queue.put(frame)
            #
            # cap.release()
        except Exception as e:
            print('Error in capture loop: {repr(e)}', e)

    def _process_loop(self):

        self.tracker = build_tracker(self.model)
        while True:
            if not self.StopPlay:
                break

            frame = self.frame_queue.get()
            if self.init_rect is None:
                result = (frame, None)
                self.result_queue.put(result)
            else:
                if self.init_rect != self.last_rect:
                    self.tracker.init(frame, self.init_rect)
                outputs = self.tracker.track(frame)
                bbox = list(map(int, outputs['bbox']))
                self.automatic_stop(bbox, frame)
                cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[0] + bbox[2], bbox[1] + bbox[3]), (0, 255, 0), 1)

                # 给目标打上标签
                # text = '目标'
                # font_size = 18
                # position = (bbox[0], bbox[1] - font_size)
                # frame = self.draw_chinese_text(image=frame, text=text, position=position)

                result = (frame, bbox)
                self.result_queue.put(result)

                self.last_rect = self.init_rect

                # 模拟获取目标坐标和屏幕尺寸
                target_coordinate = (bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2)

                screen_size = (self.width, self.height)

                # 移动摄像头到保持目标在屏幕中心
                self.move_camera_to_center(target_coordinate, screen_size)

    def draw_chinese_text(self, image, text, position, font_path='C:/Windows/Fonts/Dengb.ttf',
                          font_size=35, color=(255, 255, 255)):
        img_pil = Image.fromarray(image)
        draw = ImageDraw.Draw(img_pil)
        font = ImageFont.truetype(font_path, font_size)
        draw.text(position, text, font=font, fill=color)
        return np.array(img_pil)

    def get_frame(self):
        while True:
            frame, bbox = self.result_queue.get()
            ret, jpeg = cv2.imencode('.jpg', frame)
            data = jpeg.tobytes()
            del (frame)
            del (bbox)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + data + b'\r\n')

    def run(self):
        self.app.run(debug=True)


if __name__ == '__main__':
    project_path = os.getcwd()

    # tracker = VideoStreamer(project_path + "\siamrpn_alex_dwxcorr\config.yaml",
    #                         project_path + "\siamrpn_alex_dwxcorr\model.pth")
    tracker = VideoStreamer(project_path + "\siamrpn_r50_l234_dwxcorr_otb\config.yaml",
                            project_path + "\siamrpn_r50_l234_dwxcorr_otb\model.pth")
    tracker.run()
