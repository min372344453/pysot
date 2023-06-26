import asyncio
import json
import threading

from flask import Flask, request, jsonify, Response, render_template
from flask_cors import CORS

from HikvisionAPI import HikvisionAPI
from target_tracking import TargetTracking

tracking = TargetTracking()

app = Flask(__name__)
CORS(app)


@app.route('/')
def index():
    # 渲染HTML模板
    return render_template('lable.html')


# 设置目标进行跟踪
@app.route('/StartTracking', methods=['POST'])
def StartTracking():
    data = request.get_data()
    trackingLocation = json.loads(data)
    label_ = trackingLocation['label']
    HikvisionKey = trackingLocation['HikvisionKey']
    trackingLocation = [trackingLocation['init_rect']["x"], trackingLocation['init_rect']["y"],
                        trackingLocation['init_rect']["width"], trackingLocation['init_rect']["height"]]
    tracking.add_target(trackingLocation, label_)
    controlling = threading.Thread(target=tracking.controlling, args=(HikvisionKey,))
    controlling.start()
    # 设置跟踪目标
    return jsonify("True")


# 停止跟踪
@app.route('/StopTracking', methods=['POST'])
def StopTracking():
    data = request.get_data()
    data = json.loads(data)
    tracking.frame_controlling(data, 1)
    tracking.stop_tracking()
    return jsonify("True")


# 停止播放
@app.route('/StopPlay')
def StopPlay():
    tracking.stop_play()
    return jsonify("True")


# 停止摄像头移动
@app.route('/SetMovementSpeed', methods=['POST'])
def SetMovementSpeed():
    data = request.get_data()
    data = json.loads(data)
    speed = data['speed']
    return jsonify("True")


@app.route('/video_feed', methods=['GET'])
def video_feed():
    # 返回带有视频流的响应
    return Response(tracking.get_frame(), mimetype='multipart/x-mixed-replace; boundary=frame')


# 获得rtsp硫
@app.route('/SetCamera', methods=['POST'])
def SetCamera():
    data = request.get_data()
    data = json.loads(data)
    res = HikvisionAPI(uapi=data['uapi'],
                       appKey=data['appKey'],
                       appSecret=data['appSecret'],
                       headers_url="/artemis/api/video/v1/cameras/previewURLs",
                       data=data)
    data_request = res.request()
    url = data_request['data']['url']
    if data_request.get('code') == '0':
        tracking.running = True
        tracking_thread = threading.Thread(target=tracking.tracking_object,
                                           args=(url,))
        tracking_thread.start()

        return jsonify("True")
    else:
        return jsonify("False")


async def start_flask_app():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, app.run)


def main():
    # 并行启动 Flask
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(
        start_flask_app(),
    ))
    loop.run_forever()


if __name__ == "__main__":
    main()
