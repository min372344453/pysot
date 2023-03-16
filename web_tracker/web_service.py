import json

import cv2
import torch
from flask import Flask, render_template, Response, request

from pysot.core.config import cfg
from pysot.models.model_builder import ModelBuilder
from pysot.tracker.tracker_builder import build_tracker


# from web_tracker.platform import HikvisionAPI


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
            width = data['width']
            height = data['height']
            print(width, height)

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
            return "停止跟踪"

        @self.app.route('/StopPlay')
        def StopPlay():
            print("停止播放")

        @self.app.route('/SetCamera', methods=['POST'])
        def SetCamera():
            data = request.get_data()
            data = json.loads(data)
            address = data['address']
            port = data['port']
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
            # previewURLs = HikvisionAPI(uapi='https//' + address + ':' + port,
            #                            appKey=appkey,
            #                            appSecret=secret,
            #                            headers_url="/artemis/api/video/v1/cameras/previewURLs",
            #                            data=previewURLs)
            # previewURLs = previewURLs.request()
            # previewURLs = previewURLs['data']['url']
            # self.rtsp_url = previewURLs

    def get_direction(self, target_x, target_y, target_width, target_height):
        # 计算屏幕中心点坐标
        screen_width = 680
        screen_height = 480
        screen_center_x = screen_width / 2
        screen_center_y = screen_height / 2

        # 计算目标框中心点坐标
        target_center_x = target_x + target_width / 2
        target_center_y = target_y + target_height / 2

        # 计算目标框中心点与屏幕中心点的水平距离和垂直距离
        dx = target_center_x - screen_center_x
        dy = target_center_y - screen_center_y

        # 如果水平距离和垂直距离均为0，则目标框已经在屏幕中心，无需移动
        if dx == 0 and dy == 0:
            return None

        # 如果水平距离为0，垂直距离不为0，则目标框需要向上或向下移动
        if dx == 0:
            if dy < 0:
                print('x向上移动')
                return 'up'
            else:
                print('x下移动')
                return 'down'
        # 如果垂直距离为0，水平距离不为0，则目标框需要向左或向右移动
        if dy == 0:
            if dx < 0:
                print("y左移动")
                return 'left'
            else:
                print("y右移动")
                return 'right'

        # 如果水平距离和垂直距离均不为0，则目标框需要向水平和垂直距离更短的方向移动
        if abs(dx) > abs(dy):
            if dx < 0:
                print("不为0 y左移动")
                return 'left'
            else:
                print("不为0 y右移动")
                return 'right'
        else:
            if dy < 0:
                print("不为0 上移动")
                return 'up'
            else:
                print("不为0 下移动")
                return 'down'

    def get_frame(self):
        # 从默认摄像头捕获视频

        cap = cv2.VideoCapture(0)
        while True:
            # 从视频流中读取一帧
            ret, frame = cap.read()

            if not ret:
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
                    self.get_direction(bbox[0], bbox[1], bbox[2], bbox[3])
                    cv2.rectangle(frame, (bbox[0], bbox[1]), (bbox[0] + bbox[2], bbox[1] + bbox[3]), (0, 255, 0), 1, 1)
                    # 将图像转换为字符串
                    img_str = cv2.imencode('.jpg', frame)[1].tobytes()
                    # 产生图像字节作为响应
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + img_str + b'\r\n')

    def run(self):
        self.app.run(debug=True)


if __name__ == '__main__':
    tracker = VideoStreamer("D:/Projects/python/pysot/experiments/siamrpn_alex_dwxcorr/config.yaml",
                            "D:/Projects/python/pysot/experiments/siamrpn_alex_dwxcorr/model.pth")
    tracker.run()
