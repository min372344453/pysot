import asyncio
import json


class WebSocketHandler:
    def __init__(self, target_tracking):
        self.target_tracking = target_tracking

    async def send_frames_from_queue(self, websocket):
        while True:
            if not self.target_tracking.frames_queue.empty():
                frames = self.target_tracking.frames_queue.get()
                json_frames = json.dumps(frames)  # 将frames转换为JSON格式的字符串
                await websocket.send(json_frames)  # 发送JSON格式的字符串
            else:
                await asyncio.sleep(0.00001)  # 等待一段时间再次尝试获取 frames

    async def send_frames(self, websocket, path):
        while True:
            message = await websocket.recv()  # 等待前端发送消息
            print(f"Received message: {message}")  # 输出接收到的消息

            # 启动从队列获取并发送 frames 的任务
            asyncio.ensure_future(self.send_frames_from_queue(websocket))
