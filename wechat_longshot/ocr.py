"""Text recognition with Apple's Vision framework (no network, no extra models)."""

from __future__ import annotations

import cv2
import Foundation
import Vision

from .types import Frame, Rect, TextBox


def recognize_text(
    frame: Frame, languages: tuple[str, ...] = ("zh-Hans", "en-US"), fast: bool = False
) -> list[TextBox]:
    """Run VNRecognizeTextRequest on a BGR frame; boxes are in image pixels, top-left origin."""
    h, w = frame.shape[:2]
    ok, png = cv2.imencode(".png", frame)
    if not ok:
        return []
    data = Foundation.NSData.dataWithBytes_length_(png.tobytes(), len(png))

    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(
        Vision.VNRequestTextRecognitionLevelFast
        if fast
        else Vision.VNRequestTextRecognitionLevelAccurate
    )
    req.setUsesLanguageCorrection_(False)
    req.setRecognitionLanguages_(list(languages))

    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    ok2, err = handler.performRequests_error_([req], None)
    if not ok2:
        return []

    out: list[TextBox] = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        bb = obs.boundingBox()  # normalised, origin bottom-left
        x = int(bb.origin.x * w)
        y = int((1.0 - bb.origin.y - bb.size.height) * h)
        bw = int(bb.size.width * w)
        bh = int(bb.size.height * h)
        out.append(TextBox(str(cand[0].string()), Rect(x, y, bw, bh), float(cand[0].confidence())))
    out.sort(key=lambda t: (t.rect.y, t.rect.x))
    return out
