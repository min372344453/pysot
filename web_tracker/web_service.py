import json

import cv2
import torch
from flask import Flask, render_template, Response, request

from pysot.core.config import cfg
from pysot.models.model_builder import ModelBuilder
from pysot.tracker.tracker_builder import build_tracker
from web_tracker.platform import HikvisionAPI


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

    def _load_config(self):
        cfg.merge_from_file(self.config_file)
        cfg.CUDA = torch.cuda.is_available() and cfg.CUDA

    def _load_model(self):
        self.model = ModelBuilder()
        self.model.load_state_dict(torch.load(self.model_snapshot,
                                              map_location=lambda storage, loc: storage.cpu()))
        self.model.eval().to(torch.device('cuda') if cfg.CUDA else torch.device('cpu'))

    def _build_tracker(self):
        self.tracker = build_tracker(self.model)

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
                "cameraIndexCode": "e57f2bfacb0c4ef793279e9aabc8b3c1",
                "startX": startX / 2.67,
                "startY": startY / 1.76,
                "endX": endX / 2.67,
                "endY": endY / 1.76
            }
            # 聚焦
            selZoom = HikvisionAPI(uapi='192.168.0.96:443',
                                   appKey='26324374',
                                   appSecret='Ai2HjDzjn2rtyPzRQRqg',
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
                "cameraIndexCode": "e57f2bfacb0c4ef793279e9aabc8b3c1",
                "action": 0,
                "command": "GOTO_PRESET",
                "speed": 4,
                "presetIndex": 1
            }

            # 发送控制命令
            controlling_api = HikvisionAPI(uapi='192.168.0.96:443',
                                           appKey='26324374',
                                           appSecret='Ai2HjDzjn2rtyPzRQRqg',
                                           headers_url="/artemis/api/video/v1/ptzs/controlling",
                                           data=controlling)
            request = controlling_api.request()
            return "Success"

        @self.app.route('/StopPlay')
        def StopPlay():
            self.StopPlay = False
            print("停止播放")
            return "Success"

        @self.app.route('/SetCamera', methods=['POST'])
        def SetCamera():
            data = request.get_data()
            data = json.loads(data)
            address = data['address']
            appkey = data['appkey']
            secret = data['secret']
            id = data['id']
            previewURLs = {
                "cameraIndexCode": id,
                "streamType": 1,
                "protocol": "rtsp",
                "transmode": 1,
                "expand": "streamform=rtp"
            }
            res = HikvisionAPI(uapi=address,
                               appKey=appkey,
                               appSecret=secret,
                               headers_url="/artemis/api/video/v1/cameras/previewURLs",
                               data=previewURLs)
            data = res.request()
            data = data['data']['url']
            self.rtsp_url = data

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

    # 控制摄像头移动到保持目标在屏幕中心
    def move_camera_to_center(self, target_coordinate, screen_size):
        # 获取目标在屏幕中心时的坐标
        delta_x, delta_y = self.get_center_coordinate(target_coordinate, screen_size)

        # 控制摄像头移动
        controlling = {
            "cameraIndexCode": "e57f2bfacb0c4ef793279e9aabc8b3c1",
            "action": 0,
            "command": "",
            "speed": 4,
            "presetIndex": 0
        }
        if delta_x < 0 and abs(delta_x) > abs(delta_y):
            controlling["command"] = "LEFT"
            if self.previous != controlling["command"]:
                self.previous = controlling["command"]
            else:
                return
        elif delta_x > 0 and abs(delta_x) > abs(delta_y):
            controlling["command"] = "RIGHT"
            if self.previous != controlling["command"]:
                self.previous = controlling["command"]
            else:
                return
        elif delta_y < 0 and abs(delta_y) > abs(delta_x):
            controlling["command"] = "UP"
            if self.previous != controlling["command"]:
                self.previous = controlling["command"]
            else:
                return
        elif delta_y > 0 and abs(delta_y) > abs(delta_x):
            controlling["command"] = "DOWN"
            if self.previous != controlling["command"]:
                self.previous = controlling["command"]
            else:
                return
        else:
            print("执行了")
            self.previous = controlling["command"]
            self.previous = controlling["action"] = 1

        # 调整速度和预置位
        controlling["speed"] = 10
        controlling["presetIndex"] = 0

        # 发送控制命令
        controlling_api = HikvisionAPI(uapi='192.168.0.96:443',
                                       appKey='26324374',
                                       appSecret='Ai2HjDzjn2rtyPzRQRqg',
                                       headers_url="/artemis/api/video/v1/ptzs/controlling",
                                       data=controlling)
        request = controlling_api.request()
        if request.get('code') == '0':
            print('Success!')
        else:
            print(request.get('msg'))

    def get_frame(self):
        # 从默认摄像头捕获视频

        cap = cv2.VideoCapture(self.rtsp_url)
        while True:
            # 从视频流中读取一帧
            if self.StopPlay:
                ret, frame = cap.read()

                if not ret and self.StopPlay:
                    break

                # 缩小图像以提高性能
                frame = cv2.resize(frame, (680, 480), fx=0.5, fy=0.5)
                # 判断是否绘制目标
                if self.init_rect is None:
                    # 没有绘制目标
                    # 将图像转换为字符串
                    img_str = cv2.imencode('.jpg', frame)[1].tobytes()

                    # 产生图像字节作为响应
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + img_str + b'\r\n')
                # 绘制目标
                else:
                    # 判断和上一个目标不一样
                    if self.init_rect != self.last_rect:
                        # 不一样初始化跟踪器
                        self.tracker.init(frame, self.init_rect)
                        # 记录这一次目标坐标
                        self.last_rect = self.init_rect
                    else:
                        # 和上一个目标一样绘制目标
                        outputs = self.tracker.track(frame)
                        bbox = list(map(int, outputs['bbox']))
                        # 模拟获取目标坐标和屏幕尺寸
                        target_coordinate = (bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2)
                        screen_size = (680, 480)

                        # 移动摄像头到保持目标在屏幕中心
                        self.move_camera_to_center(target_coordinate, screen_size)

                        cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[0] + bbox[2], bbox[1] + bbox[3]), (0, 255, 0), 1,1)
                        # 将图像转换为字符串
                        img_str = cv2.imencode('.jpg', frame)[1].tobytes()
                        # 产生图像字节作为响应
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + img_str + b'\r\n')
            else:
                self.StopPlay = True
                break

    def run(self):
        self.app.run(debug=True)


if __name__ == '__main__':
    tracker = VideoStreamer("../experiments/siamrpn_alex_dwxcorr/config.yaml",
                            "../experiments/siamrpn_alex_dwxcorr/model.pth")
    tracker.run()
