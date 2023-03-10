import cv2
import numpy as np
import torch

from pysot.core.config import cfg
from pysot.models.model_builder import ModelBuilder
from pysot.tracker.tracker_builder import build_tracker


class ObjectTracker:
    def __init__(self, config_file, model_snapshot):
        self.config_file = config_file
        self.model_snapshot = model_snapshot

        torch.set_num_threads(3)

        self._load_config()
        self._load_model()
        self._build_tracker()

        self.first_frame = True

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

    def _get_frames(self, video_uri):
        cap = cv2.VideoCapture(video_uri)
        while True:
            ret, frame = cap.read()
            if ret:
                cv2.resize(frame, (640, 480))
                yield frame
            else:
                break

    def track_object(self, video_uri):
        for frame in self._get_frames(video_uri):
            if self.first_frame:
                try:
                    init_rect = cv2.selectROI("Tracking", frame, False, False)
                except:
                    exit()
                self.tracker.init(frame, init_rect)
                self.first_frame = False
            else:
                outputs = self.tracker.track(frame)
                if 'polygon' in outputs:
                    polygon = np.array(outputs['polygon']).astype(np.int32)
                    cv2.polylines(frame, [polygon.reshape((-1, 1, 2))],
                                  True, (0, 255, 0), 3)
                    mask = ((outputs['mask'] > cfg.TRACK.MASK_THERSHOLD) * 255)
                    mask = mask.astype(np.uint8)
                    mask = np.stack([mask, mask * 255, mask]).transpose(1, 2, 0)
                    cv2.addWeighted(frame, 0.77, mask, 0.23, -1)
                else:
                    bbox = list(map(int, outputs['bbox']))
                    cv2.rectangle(frame, (bbox[0], bbox[1]),
                                  (bbox[0] + bbox[2], bbox[1] + bbox[3]),
                                  (0, 255, 0), 3, 1)
                cv2.imshow('Tracking', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
        cv2.destroyAllWindows()
# if __name__ == '__main__':
#     tracker = ObjectTracker("pysot/experiments/siamrpn_alex_dwxcorr/config.yaml",
#                             "pysot/experiments/siamrpn_alex_dwxcorr/model.pth")
#     tracker.track_object("rtsp://192.168.1.10:554/live/ch0")