import json

import cv2
from flask import Flask, render_template, Response, request

from web_tracker.platform import HikvisionAPI
from web_tracker.tracker_service import ObjectTracker

app = Flask(__name__)


def get_frame(target):
    # 从默认摄像头捕获视频
    cap = cv2.VideoCapture(0)
    while True:
        # 从视频流中读取一帧
        ret, frame = cap.read()

        if not ret:
            break

        # 缩小图像以提高性能
        small = cv2.resize(frame, (680, 480), fx=0.5, fy=0.5)

        if target:
            # 绘制目标框
            cv2.rectangle(small, (target['x'], target['y']),
                          (target['x'] + target['width'], target['y'] + target['height']),
                          (0, 255, 0), 2)

        # 将图像转换为字符串
        img_str = cv2.imencode('.jpg', small)[1].tostring()

        # 产生图像字节作为响应
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + img_str + b'\r\n')


@app.route('/')
def index():
    # 渲染HTML模板
    return render_template('index.html')


@app.route('/video_feed')
def video_feed():
    # 返回带有视频流的响应
    return Response(get_frame(target), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/SetDisplaySize', methods=['POST'])
def SetDisplaySize():
    data = request.get_data()
    data = json.loads(data)
    width = data['width']
    height = data['height']
    print(width, height)


@app.route('/StartTracking')
def StartTracking():
    pass


@app.route('/StopTracking')
def StopTracking():
    pass


@app.route('/StopPlay')
def StopPlay():
    pass


@app.route('/SetCamera', methods=['POST'])
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
    previewURLs = HikvisionAPI(uapi='https//' + address + ':' + port,
                               appKey=appkey,
                               appSecret=secret,
                               headers_url="/artemis/api/video/v1/cameras/previewURLs",
                               data=previewURLs)
    previewURLs = previewURLs.request()
    previewURLs = previewURLs['data']['url']
    print(previewURLs)
    ObjectTracker._get_frames()


if __name__ == '__main__':
    target = None
    app.run(debug=True)
