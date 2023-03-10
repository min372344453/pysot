from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import argparse  # module to parse command line arguments

import cv2  # module for computer vision tasks
import numpy as np  # module for numerical computations in Python
import torch  # PyTorch deep learning library

# Importing specific functions from custom modules
from pysot.core.config import cfg
from pysot.models.model_builder import ModelBuilder
from pysot.tracker.tracker_builder import build_tracker

#  PyTorch设置线程的数量
torch.set_num_threads(3)

# 创建一个参数解析器对象
parser = argparse.ArgumentParser(description='tracking demo')
# 将参数添加到解析器
parser.add_argument('--config', default='../experiments/siamrpn_alex_dwxcorr_otb/config.yaml', type=str,
                    help='config file')
parser.add_argument('--snapshot', default='../experiments/siamrpn_alex_dwxcorr_otb/model.pth', type=str,
                    help='model name')
parser.add_argument('--rtsp_uri', default='rtsp://119.7.8.7:554/openUrl/NNvTgL6', type=str,
                    help='video stream')
# 解析命令行参数和存储他们的参数变量
args = parser.parse_args()


# 从RTSP流函数得到视频帧
def get_frames(rtsp_uri):
    cap = cv2.VideoCapture(rtsp_uri)
    while True:
        ret, frame = cap.read()
        if ret:
            cv2.resize(frame, (640, 480))
            yield frame
        else:
            break


# 主要功能运行跟踪演示
def main():
    # 加载配置文件跟踪
    cfg.merge_from_file(args.config)
    # 检查CUDA (GPU)是否可用,并相应地设置配置
    cfg.CUDA = torch.cuda.is_available() and cfg.CUDA
    device = torch.device('cuda')  # 设置设备使用GPU如果可用

    # 创建一个 SiameseRPN model
    model = ModelBuilder()

    # pre-trained 加载到模型
    model.load_state_dict(torch.load(args.snapshot,
                                     map_location=lambda storage, loc: storage.cpu()))
    model.eval().to(device)  # 设置模型来评价模式和使用GPU如果可用

    # 建立跟踪使用加载模型
    tracker = build_tracker(model)

    # 为第一帧设置True
    first_frame = True
    # 创建一个窗口来显示全屏模式的跟踪结果
    cv2.namedWindow("Tracking", cv2.WND_PROP_FULLSCREEN)

    # 遍历每一帧的RTSP流
    for frame in get_frames(args.rtsp_uri):
        if first_frame:
            try:
                # 提示用户选择使用一个边界框对象跟踪
                init_rect = cv2.selectROI("Tracking", frame, False, False)
            except:
                exit()
            # 初始化跟踪第一帧和选定的对象
            tracker.init(frame, init_rect)
            first_frame = False  # 初始化跟踪后标志设置为False
        else:
            # 对当前帧执行对象跟踪
            outputs = tracker.track(frame)
            if 'polygon' in outputs:
                # 如果一个多边形对象被跟踪,在框架上绘制多边
                polygon = np.array(outputs['polygon']).astype(np.int32)
                cv2.polylines(frame, [polygon.reshape((-1, 1, 2))],
                              True, (0, 255, 0), 3)
                # 获得遮蔽跟踪对象
                mask = ((outputs['mask'] > cfg.TRACK.MASK_THERSHOLD) * 255)
                # 转换 mask 成 uint8 格式
                mask = mask.astype(np.uint8)
                # Stack mask 通道
                mask = np.stack([mask, mask * 255, mask]).transpose(1, 2, 0)
                # 覆盖 mask 在边框
                cv2.addWeighted(frame, 0.77, mask, 0.23, -1)
            else:
                #  得到边界框的坐标跟踪对象
                bbox = list(map(int, outputs['bbox']))

                # 画边界框在跟踪对象
                cv2.rectangle(frame, (bbox[0], bbox[1]),
                              (bbox[0] + bbox[2], bbox[1] + bbox[3]),
                              (0, 255, 0), 3)
                cv2.imshow("Tracking", frame)  # 显示跟踪结果
                # 判断目标的水平移动方向
                if bbox[0] > init_rect[0] + 20:
                    print("目标向右移动")
                elif bbox[0] < init_rect[0] - 20:
                    print("目标向左移动")

                # 判断目标的垂直移动方向
                if bbox[1] > init_rect[1] + 20:
                    print("目标向下移动")
                elif bbox[1] < init_rect[1] - 20:
                    print("目标向上移动")
                if cv2.waitKey(1) & 0xFF == ord('q'):  # 按q键结束
                    break
#
#
# if __name__ == '__main__':
#     main()
