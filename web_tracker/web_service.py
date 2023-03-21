import json
import queue
import threading

import cv2
import torch
from flask import Flask, render_template, Response, request
from web_tracker.platform import HikvisionAPI

from pysot.core.config import cfg
from pysot.models.model_builder import ModelBuilder
from pysot.tracker.tracker_builder import build_tracker


class VideoStreamer:
    def __init__(self, config_file, model_snapshot):
        self.app = Flask(__name__)
        self.rtsp_url = None
        self.config_file = config_file
        self.model_snapshot = model_snapshot

        torch.set_num_threads(3)

        self._load_config()
        self._load_model()
        self._build_tracker()
        self.rtsp_url = None
        self.init_rect = None
        self.img_array = None
        self.last_rect = None
        self.previous = None
        self.StopPlay = True
        self.address = None
        self.appkey = None
        self.secret = None
        self.cameraIndexCode = None
        self.init_rect = None
        self.last_rect = None
        self.frame_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.tracker = None
        self.cap_thread = None
        self.process_thread = None

    def _load_config(self):
        cfg.merge_from_file(self.config_file)
        cfg.CUDA = torch.cuda.is_available() and cfg.CUDA

    def _load_model(self):
        self.model = ModelBuilder()
        self.model.load_state_dict(torch.load(self.model_snapshot,
                                              map_location=lambda storage, loc: storage.cpu()))
        self.model.eval().to(torch.device('cuda') if cfg.CUDA else torch.device('cpu'))

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
                "startX": startX / 2.67,
                "startY": startY / 1.76,
                "endX": endX / 2.67,
                "endY": endY / 1.76
            }
            # 聚焦
            selZoom = HikvisionAPI(uapi=self.address,
                                   appKey=self.appkey,
                                   appSecret=self.secret,
                                   headers_url="/artemis/api/video/v1/ptzs/selZoom",
                                   data=selZoom)
            zoom_request = selZoom.request()
            if zoom_request.get('code') == '0':
                return "Success"

        @self.app.route('/StartTracking', methods=['POST'])
        def StartTracking():
            data = request.get_data()
            data = json.loads(data)
            print(data['init_rect'])
            # 设置跟踪目标
            self.init_rect = list(data['init_rect'].values())
            return "跟踪成功"

        @self.app.route('/StopTracking')
        def StopTracking():
            self.init_rect = None
            # 控制摄像头移动
            controlling = {
                "cameraIndexCode": self.cameraIndexCode,
                "action": 0,
                "command": "GOTO_PRESET",
                "speed": 4,
                "presetIndex": 1
            }

            # 发送控制命令
            controlling_api = HikvisionAPI(uapi=self.address,
                                           appKey=self.appkey,
                                           appSecret=self.secret,
                                           headers_url="/artemis/api/video/v1/ptzs/controlling",
                                           data=controlling)
            request = controlling_api.request()
            return "Success"

        @self.app.route('/StopPlay')
        def StopPlay():
            self.cap_thread = None
            self.process_thread = None
            self.StopPlay = False
            # self.process_thread.join()
            # self.cap_thread.join()

            # 向捕获线程发出停止信号并等待其加入
            self.StopPlay  # 向处理线程发出停止并等待其加入的信号

            # 清除处理和结果队列
            self.frame_queue.queue.clear()
            self.result_queue.queue.clear()
            print("停止播放")

            return "Success"

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
                "transmode": 1,
                "expand": "streamform=rtp"
            }

            res = HikvisionAPI(uapi=self.address,
                               appKey=self.appkey,
                               appSecret=self.secret,
                               headers_url="/artemis/api/video/v1/cameras/previewURLs",
                               data=previewURLs)
            data = res.request()
            print(data)
            data = data['data']['url']
            self.rtsp_url = data
            #  启动视频捕获和帧处理线程
            if self.cap_thread is None and self.process_thread is None:
                self.StopPlay = True
                self.cap_thread = threading.Thread(target=self._capture_loop)
                self.process_thread = threading.Thread(target=self._process_loop)
                self.cap_thread.start()
                self.process_thread.start()
            return "Success"

    # 获取目标在屏幕中心时的坐标
    def get_center_coordinate(self, target_coordinate, screen_size):
        screen_width, screen_height = screen_size
        target_x, target_y = target_coordinate
        center_x = screen_width / 2
        center_y = screen_height / 2
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
            "action": 1,
            "command": "",
            "speed": 4,
            "presetIndex": 0
        }

        if delta_x <= 0 and abs(delta_x) > abs(delta_y):
            controlling["command"] = "LEFT"
            if self.previous != controlling["command"]:
                self.previous = controlling["command"]
            else:
                print('LEFT')
                return
        elif delta_x >= 0 and abs(delta_x) > abs(delta_y):
            controlling["command"] = "RIGHT"
            if self.previous != controlling["command"]:
                self.previous = controlling["command"]
            else:
                print('RIGHT')
                return
        elif delta_y <= 0 and abs(delta_y) > abs(delta_x):
            controlling["command"] = "UP"
            if self.previous != controlling["command"]:
                self.previous = controlling["command"]
            else:
                print('UP')
                return
        elif delta_y >= 0 and abs(delta_y) > abs(delta_x):
            controlling["command"] = "DOWN"
            if self.previous != controlling["command"]:
                self.previous = controlling["command"]

            else:
                print('DOWN')
                return
        else:
            print("结束了")
            self.previous = controlling["command"]
            self.previous = controlling["action"] = 1

        # 调整速度和预置位
        controlling["speed"] = 18
        controlling["presetIndex"] = 0

        # 发送控制命令
        controlling_api = HikvisionAPI(uapi=self.address,
                                       appKey=self.appkey,
                                       appSecret=self.secret,
                                       headers_url="/artemis/api/video/v1/ptzs/controlling",
                                       data=controlling)
        request = controlling_api.request()

        if request.get('code') == '0':
            print('Success!')
        else:
            print(request.get('msg'))

    def _capture_loop(self):
        # 初始化循环外的视频捕获对象
        cap = cv2.VideoCapture(self.rtsp_url)
        while self.StopPlay:
            # 从视频流中读取帧
            ret, frame = cap.read()

            if not ret or not self.StopPlay:
                break

            # 将图像大小调整为较小的尺寸
            frame = cv2.resize(frame, (680, 480), fx=0.5, fy=0.5)

            # 将帧添加到处理队列
            self.frame_queue.put(frame)

    def _process_loop(self):
        self.tracker = build_tracker(self.model)
        while True:
            if not self.StopPlay:
                break
            # 从处理队列中获取帧
            frame = self.frame_queue.get()

            if self.init_rect is None:
                # 没有目标
                result = (frame, None)
                self.result_queue.put(result)
            else:
                # 目标与上一个目标比较
                if self.init_rect != self.last_rect:
                    # 初始化跟踪器
                    self.tracker.init(frame, self.init_rect)
                    self.matching(frame)
                    # 标记目标
                    self.last_rect = self.init_rect
                else:
                    # 绘制目标框
                    self.matching(frame)

    def matching(self, frame):
        outputs = self.tracker.track(frame)
        bbox = list(map(int, outputs['bbox']))
        cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[0] + bbox[2], bbox[1] + bbox[3]), (0, 255, 0), 2)
        result = (frame, bbox)
        self.result_queue.put(result)

    def get_frame(self):
        while True:
            # 从结果队列中获取结果
            frame, bbox = self.result_queue.get()
            print("get_frame", frame)
            # 将帧转换为 JPEG 编码的字节字符串
            ret, jpeg = cv2.imencode('.jpg', frame)
            data = jpeg.tobytes()
            # 将字节字符串作为响应返回
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + data + b'\r\n')

    def run(self):
        self.app.run(debug=True)


if __name__ == '__main__':
    tracker = VideoStreamer("../experiments/siamrpn_alex_dwxcorr/config.yaml",
                            "../experiments/siamrpn_alex_dwxcorr/model.pth")
    tracker.run()
